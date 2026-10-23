"""actions.Station on fake hardware: move order, gentle presses, refusals that keep the wrong pill out."""
import asyncio
import json
from types import SimpleNamespace

import pytest

import actions
import fakes


@pytest.fixture(autouse=True)
def no_sdk(monkeypatch):
    monkeypatch.setattr(actions, "joint_positions", lambda v: v)
    monkeypatch.setattr(actions, "cartesian_pose", lambda _end, x, y, z: SimpleNamespace(x=x, y=y, z=z))
    monkeypatch.setattr(actions, "SETTLE_POLL_S", 0.0)
    monkeypatch.setattr(actions, "PRESS_HOLD_S", 0.0)
    monkeypatch.setattr(actions, "CAMERA_SETTLE_S", 0.0)


def rig(tmp_path, label="tums", stops_at=12.0, poses=None, allow_open=True, **kw):
    arm, grip = fakes.FakeArm(), fakes.FakeGripper(stops_at)
    st = actions.Station(arm, grip, fakes.FakeCamera(), poses or fakes.poses(), fakes.LIMITS,
                         tmp_path / "s.jsonl", identify=fakes.tray(label), allow_open=allow_open, **kw)
    return st, arm, grip


def nudge_rig(tmp_path, stops_at, **kw):
    st, arm, _ = rig(tmp_path, stops_at=stops_at, **kw)
    arm.tcp[tuple(st.clamp(st.poses["tray_down"]))] = (212.0, -6.0, 181.0)  # the fingertip measures here at tray_down
    return st, arm


def visited(st, arm):
    by_joints = {tuple(st.clamp(j)): n for n, j in st.poses.items()}
    return [by_joints[tuple(m)] for m in arm.moves]


def texts(st):
    return [e["text"] for e in st.events]


def logged(st):
    return [json.loads(line) for line in st.log_path.read_text().splitlines()]


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


def test_place_refuses_after_three_failed_grips(tmp_path):
    st, arm, _ = rig(tmp_path, stops_at=[1.0, 1.0, 1.0])  # closed on nothing three times
    st.lid["wed"] = "open"
    r = run(st.run({"action": "place", "pill": "tums", "day": "wed"}))
    assert r == {"ok": False, "say": "I could not grip the pill after 3 tries"}
    assert visited(st, arm).count("tray_down") == 3 and "drop_wed_hover" not in visited(st, arm)
    assert texts(st) == ["Missed it. Trying again.", "Missed it. Trying again.", "Missed it."]


def test_a_miss_then_a_hold_on_the_third_try_narrates_each_retry(tmp_path):
    st, arm, _ = rig(tmp_path, stops_at=[1.0, 1.0, 11.0])
    r = run(st.run({"action": "place", "pill": "tums", "day": "wed"}))
    assert r == {"ok": True, "say": "tums placed in Wednesday"}
    assert texts(st) == ["Missed it. Trying again.", "Missed it. Trying again.", "Got it."]
    assert [e["grip"] for e in logged(st) if "grip" in e] == [1, 2, 3]
    assert "drop_wed_hover" in visited(st, arm)


def test_a_miss_that_empties_the_tray_refuses_before_the_next_try(tmp_path):
    st, arm, _ = rig(tmp_path, stops_at=[1.0, 11.0])
    seen = iter([[{"label": "tums"}], []])  # the pill is there at the first look and gone after the miss
    st.identify = lambda _img: next(seen)
    r = run(st.run({"action": "place", "pill": "tums", "day": "wed"}))
    assert r == {"ok": False, "say": "the tray is empty"}
    assert visited(st, arm).count("tray_down") == 1 and "drop_wed_hover" not in visited(st, arm)
    assert texts(st) == ["Missed it. Trying again."]


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


def test_identification_photo_waits_for_the_camera_to_catch_up(tmp_path, monkeypatch):
    monkeypatch.setattr(actions, "CAMERA_SETTLE_S", 0.05)
    events = []
    st, arm, _ = rig(tmp_path)
    real_sleep, real_images = actions.asyncio.sleep, st.camera.get_images

    async def sleep(s):
        events.append(("sleep", s))
        await real_sleep(0)

    async def images():
        events.append(("frame",))
        return await real_images()

    monkeypatch.setattr(actions.asyncio, "sleep", sleep)
    st.camera.get_images = images
    run(st.run({"action": "place", "pill": "tums", "day": "wed"}))
    i = events.index(("frame",))
    assert events[i - 1] == ("sleep", 0.05)  # the frame is taken only after the settle wait


def test_events_keep_only_the_newest_lines(tmp_path, monkeypatch):
    monkeypatch.setattr(actions, "EVENTS_KEPT", 3)
    st, _, _ = rig(tmp_path)
    for i in range(5):
        st.say(f"line {i}")
    assert [(e["id"], e["text"]) for e in st.events] == [(3, "line 2"), (4, "line 3"), (5, "line 4")]


def test_a_retry_moves_3mm_from_the_taught_tray_down_by_default(tmp_path):
    st, arm = nudge_rig(tmp_path, stops_at=[1.0, 11.0])
    assert run(st.run({"action": "place", "pill": "tums", "day": "wed"}))["ok"] is True
    assert arm.cartesian == [(215.0, -6.0, 181.0)]  # +3 mm in x from the measured pose; the height is kept


def test_retries_nudge_by_the_cap_and_never_dip_below_tray_down(tmp_path, monkeypatch):
    monkeypatch.setattr(actions, "NUDGE_MM", 10.0)  # asks for more than NUDGE_CAP_MM allows
    st, arm = nudge_rig(tmp_path, stops_at=[1.0, 1.0, 11.0])
    assert run(st.run({"action": "place", "pill": "tums", "day": "wed"}))["ok"] is True
    assert len(arm.cartesian) == 2  # one nudge per retry; the taught first try has none
    for x, y, z in arm.cartesian:
        assert max(abs(x - 212.0), abs(y + 6.0)) == pytest.approx(actions.NUDGE_CAP_MM)
        assert z >= 181.0  # the measured height at tray_down


def test_nudge_off_sends_no_cartesian_moves(tmp_path, monkeypatch):
    monkeypatch.setattr(actions, "NUDGE_MM", 0.0)
    st, arm = nudge_rig(tmp_path, stops_at=[1.0, 11.0])
    assert run(st.run({"action": "place", "pill": "tums", "day": "wed"}))["ok"] is True
    assert visited(st, arm).count("tray_down") == 2  # the retry still happens, at the taught pose
    assert arm.cartesian == []


def test_a_refused_nudge_falls_back_to_the_taught_pose(tmp_path):
    st, arm = nudge_rig(tmp_path, stops_at=[1.0, 11.0])
    arm.fail_cartesian = True
    assert run(st.run({"action": "place", "pill": "tums", "day": "wed"}))["ok"] is True
    assert arm.cartesian == []
    # attempt 1 at tray_down, the lift, attempt 2 at tray_down, then the refused nudge re-sends the taught pose
    assert visited(st, arm)[2:6] == ["tray_down", "tray_hover", "tray_down", "tray_down"]
