"""actions.Station on fake hardware: move order, gentle presses, refusals that keep the wrong pill out."""
import asyncio

import pytest

import actions
import fakes


@pytest.fixture(autouse=True)
def no_sdk(monkeypatch):
    monkeypatch.setattr(actions, "joint_positions", lambda v: v)
    monkeypatch.setattr(actions, "SETTLE_POLL_S", 0.0)
    monkeypatch.setattr(actions, "PRESS_HOLD_S", 0.0)


def rig(tmp_path, label="tums", stops_at=12.0, poses=None, allow_open=True, **kw):
    arm, grip = fakes.FakeArm(), fakes.FakeGripper(stops_at)
    st = actions.Station(arm, grip, fakes.FakeCamera(), poses or fakes.poses(), fakes.LIMITS,
                         tmp_path / "s.jsonl", identify=fakes.tray(label), allow_open=allow_open, **kw)
    return st, arm, grip


def visited(st, arm):
    by_joints = {tuple(st.clamp(j)): n for n, j in st.poses.items()}
    return [by_joints[tuple(m)] for m in arm.moves]


def run(coro):
    return asyncio.run(coro)


def torque(arm):
    return [c["value"] for c in arm.commands if c.get("command") == "set_torque_limit"]


def test_open_presses_the_days_tab_gently_and_restores_torque(tmp_path):
    st, arm, grip = rig(tmp_path, stops_at=1.0)
    assert run(st.run({"action": "open", "day": "Wednesday"})) == {"ok": True, "say": "Wednesday is open"}
    assert visited(st, arm) == ["tab_wed_hover", "tab_wed_press", "tab_wed_hover"]
    assert torque(arm) == [actions.PRESS_TORQUE, actions.FULL_TORQUE]
    assert {"set_speed": actions.PRESS_SPEED} in arm.commands
    assert grip.sets == [actions.CLOSED_PCT]  # closed jaw is the fingertip
    assert st.lid["wed"] == "open"


def test_torque_is_restored_when_the_press_fails(tmp_path):
    st, arm, _ = rig(tmp_path)
    arm.fail_on = st.clamp(st.poses["tab_mon_press"])
    with pytest.raises(RuntimeError):
        run(st.run({"action": "open", "day": "mon"}))
    assert torque(arm)[-1] == actions.FULL_TORQUE


def test_close_uses_the_lid_poses(tmp_path):
    st, arm, _ = rig(tmp_path)
    assert run(st.run({"action": "close", "day": "sat"}))["say"] == "Saturday is closed"
    assert visited(st, arm) == ["lid_sat_hover", "lid_sat_press", "lid_sat_hover"]


def test_missing_pose_refuses_by_name_and_does_not_move(tmp_path):
    p = fakes.poses()
    del p["tab_fri_press"]
    st, arm, _ = rig(tmp_path, poses=p)
    assert run(st.run({"action": "open", "day": "fri"})) == {"ok": False, "say": "position tab_fri_press is not taught yet"}
    assert arm.moves == []


def test_unknown_day_and_action_refuse(tmp_path):
    st, arm, _ = rig(tmp_path)
    assert run(st.run({"action": "open", "day": "funday"}))["ok"] is False
    assert run(st.run({"action": "dance"}))["ok"] is False
    assert arm.moves == []


def test_opening_is_off_by_default_and_lids_start_open(tmp_path):
    st, arm, _ = rig(tmp_path, allow_open=False)
    assert set(st.lid.values()) == {"open"}
    r = run(st.run({"action": "open", "day": "wed"}))
    assert r == {"ok": False, "say": "I don't open lids; please open Wednesday by hand"} and arm.moves == []


def test_place_into_a_closed_day_refuses_until_marked_open_by_hand(tmp_path):
    st, arm, _ = rig(tmp_path, allow_open=False)
    run(st.run({"action": "close", "day": "thu"}))
    n = len(arm.moves)
    assert run(st.run({"action": "place", "pill": "tums", "day": "thu"}))["say"] == "Thursday is closed; open it by hand first"
    assert not any(m for m in visited(st, arm)[n:] if m.startswith(("tray_down", "drop_")))
    assert run(st.run({"action": "opened", "day": "thu"}))["say"] == "Thursday marked open"
    assert run(st.run({"action": "place", "pill": "tums", "day": "thu"}))["ok"] is True


def test_place_right_pill_grips_and_drops_in_that_day(tmp_path):
    st, arm, grip = rig(tmp_path, label="tums", stops_at=12.0)
    assert run(st.run({"action": "place", "pill": "Tums", "day": "tue"})) == {"ok": True, "say": "tums placed in Tuesday"}
    seq = visited(st, arm)
    assert "tab_tue_press" not in seq and seq.index("tray_down") < seq.index("drop_tue_hover")
    assert seq[-1] == "tray_hover"
    assert 12.0 - actions.GRIP_SQUEEZE_PCT in grip.sets  # backed off to where the pill stopped the jaw


def test_place_wrong_known_pill_leaves_it_and_never_reaches_a_compartment(tmp_path):
    st, arm, _ = rig(tmp_path, label="magnesium")
    r = run(st.run({"action": "place", "pill": "tums", "day": "tue"}))
    assert r == {"ok": False, "say": "that pill is magnesium, not tums; I left it on the tray"}
    assert not any(n.startswith(("drop_", "tab_", "tray_down")) for n in visited(st, arm))


def test_place_unknown_pill_goes_to_the_reject_cup(tmp_path):
    st, arm, _ = rig(tmp_path, label="unknown")
    r = run(st.run({"action": "place", "pill": "tums", "day": "tue"}))
    assert r["ok"] is False and "reject cup" in r["say"]
    seq = visited(st, arm)
    assert "reject_hover" in seq and not any(n.startswith("drop_") for n in seq)


def test_place_refuses_after_two_failed_grips(tmp_path):
    st, arm, grip = rig(tmp_path, stops_at=[1.0, 1.0])  # closed on nothing twice
    st.lid["wed"] = "open"
    r = run(st.run({"action": "place", "pill": "tums", "day": "wed"}))
    assert r == {"ok": False, "say": "I could not grip the pill after two tries"}
    assert visited(st, arm).count("tray_down") == 2 and "drop_wed_hover" not in visited(st, arm)


def test_second_grip_attempt_can_succeed(tmp_path):
    st, arm, _ = rig(tmp_path, stops_at=[1.0, 11.0])
    st.lid["wed"] = "open"
    assert run(st.run({"action": "place", "pill": "tums", "day": "wed"}))["ok"] is True
    assert visited(st, arm).count("tray_down") == 2 and "drop_wed_hover" in visited(st, arm)


def test_no_enrolled_photos_refuses_unless_running_unverified(tmp_path):
    st, arm, _ = rig(tmp_path)
    st.identify = None
    assert "enrolled" in run(st.run({"action": "place", "pill": "tums", "day": "wed"}))["say"]
    st.unverified, st.lid["wed"] = True, "open"
    assert run(st.run({"action": "place", "pill": "tums", "day": "wed"}))["ok"] is True


def test_shoulder_is_clamped_to_the_live_limits(tmp_path):
    p = fakes.poses()
    p["home"] = [0.0, -104.3, 0.0, 99.8, 0.0]  # the leader's folded pose, past the follower's limits
    st, arm, _ = rig(tmp_path, poses=p)
    run(st.run({"action": "home"}))
    assert arm.moves[-1] == [0.0, -99.5, 0.0, 94.5, 0.0]


def test_halt_stops_and_restores_torque(tmp_path):
    st, arm, _ = rig(tmp_path)
    run(st.halt())
    assert arm.stopped and torque(arm) == [actions.FULL_TORQUE]


class CapWriteFails(fakes.FakeArm):
    """The first capped write changes the register and then the reply fails, as a serial timeout can."""
    def __init__(self):
        super().__init__()
        self.torque, self.failed = actions.FULL_TORQUE, False

    async def do_command(self, cmd):
        if cmd.get("command") == "set_torque_limit":
            self.torque = cmd["value"]
            if cmd["value"] == actions.PRESS_TORQUE and not self.failed:
                self.failed = True
                raise RuntimeError("serial timeout")
        return await super().do_command(cmd)


def test_a_failed_capped_write_still_restores_full_torque(tmp_path):
    arm = CapWriteFails()
    st = actions.Station(arm, fakes.FakeGripper(), fakes.FakeCamera(), fakes.poses(), fakes.LIMITS,
                         tmp_path / "s.jsonl", allow_open=True)
    with pytest.raises(RuntimeError):
        run(st.run({"action": "open", "day": "wed"}))
    assert arm.torque == actions.FULL_TORQUE


def test_place_restores_full_torque_before_its_first_move(tmp_path):
    st, arm, _ = rig(tmp_path)
    run(st.run({"action": "place", "pill": "tums", "day": "wed"}))
    assert torque(arm)[:1] == [actions.FULL_TORQUE]


def test_close_checks_the_lid_poses_before_the_jaw_moves(tmp_path):
    p = fakes.poses()
    del p["lid_mon_press"]
    st, arm, grip = rig(tmp_path, poses=p)
    assert run(st.run({"action": "close", "day": "mon"})) == {"ok": False, "say": "position lid_mon_press is not taught yet"}
    assert grip.sets == [] and arm.moves == []


def test_open_checks_the_tab_poses_before_the_jaw_moves(tmp_path):
    p = fakes.poses()
    del p["tab_wed_press"]
    st, arm, grip = rig(tmp_path, poses=p)
    assert run(st.run({"action": "open", "day": "wed"}))["ok"] is False
    assert grip.sets == [] and arm.moves == []
