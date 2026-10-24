"""box.py: kinematics checked against the arm's own recorded poses, registration guards, and the stroke runner."""
import asyncio
import csv
from pathlib import Path

import numpy as np
import pytest

import box

RUN04 = Path(__file__).parent.parent / "runs" / "2026-10-23-manual-survey-04" / "motion.csv"


def rows(t_lo, t_hi):
    return [r for r in csv.DictReader(RUN04.open()) if t_lo <= float(r["t"]) <= t_hi]


def joints(r):
    return [float(r[f"F{i}"]) for i in range(5)]


@pytest.fixture(scope="module")
def kin():
    return box.Kinematics()


def test_forward_kinematics_matches_the_arms_reported_pose(kin):
    still = rows(125, 155)  # arm parked: joints and pose read at the same configuration
    assert still
    for r in still[::20]:
        m = kin.wrist(joints(r))
        assert np.linalg.norm(m[:3, 3] - [float(r["x"]), float(r["y"]), float(r["z"])]) < 1.0
        assert m[:3, 2] @ np.array([float(r["o_x"]), float(r["o_y"]), float(r["o_z"])]) > np.cos(np.radians(2))


def test_a_wrong_joint_angle_is_visible(kin):
    r = rows(125, 155)[0]
    q = joints(r)
    q[1] += 5
    assert np.linalg.norm(kin.wrist(q)[:3, 3] - [float(r["x"]), float(r["y"]), float(r["z"])]) > 10


def test_ik_recovers_the_recorded_joints(kin):
    pan = kin.pan_axis()
    for t in (90.0, 100.0, 105.0, 110.0):  # press bottoms of Alex's demonstration
        r = min(rows(t - 1, t + 1), key=lambda r: abs(float(r["t"]) - t))
        q = joints(r)
        tip, a = kin.tip(q)
        radial = (tip[:2] - pan[:2]) / np.linalg.norm(tip[:2] - pan[:2])
        lean = np.degrees(np.arctan2(a[:2] @ radial, -a[2]))
        got = kin.ik(tip, lean, [0.0, 15.0, -10.0, 80.0, 0.0], heading=q[4] - q[0])
        assert max(abs(np.subtract(got, q))) < 0.5


def test_ik_refuses_an_unreachable_pose(kin):
    with pytest.raises(ValueError):
        kin.ik([600.0, 0.0, 50.0], 0.0, [0.0, 15.0, -10.0, 80.0, 0.0])


def test_marks_four_lids_apart_fix_the_box():
    mon = [240.0, 65.0, 28.0]
    fri = [240.0 + 4 * box.PITCH * 0.1, 65.0 - 4 * box.PITCH * np.sqrt(1 - 0.01), 29.0]
    b = box.Box.from_marks(mon, fri)
    assert np.allclose(b.point("fri", 0, 0)[:2], fri[:2], atol=0.2)
    assert np.allclose(b.point("wed", 0, 0)[:2], np.add(mon, fri)[:2] / 2, atol=0.2)
    assert b.away @ np.array([1.0, 0.0, 0.0]) > 0.9  # away from the arm


@pytest.mark.parametrize("fri, why", [
    ([240.0, -30.0, 28.0], "apart"),           # 95 mm: someone marked Thursday
    ([240.0, 65.0 - 4 * box.PITCH, 45.0], "height"),
])
def test_bad_marks_are_refused(fri, why):
    with pytest.raises(ValueError, match=why):
        box.Box.from_marks([240.0, 65.0, 28.0], fri)


# the box as placed on 24 Oct (front edge x 200, along the y axis) with its measured lid midpoints
TODAY = box.Box(mon=[200.0, 43.6, 28.0], along=[0.0, -1.0, 0.0], source="test", lid_y=box.LID_Y_24OCT)


def test_all_seven_days_are_planned_now_the_ends_open(kin):
    assert box.ROBOT_DAYS == box.DAYS  # day 1 taped Sunday and Saturday down; on 24 Oct they open too


def test_every_robot_day_plans_inside_joint_limits(kin):
    for day in box.ROBOT_DAYS:
        wps = box.plan(kin, TODAY, day, [0.0, 15.0, -10.0, 80.0, -103.0])
        assert [w["name"] for w in wps][-2:] == ["press", "lift"]
        assert all(abs(box.Kinematics().tip(w["joints"])[0][1] - box.LID_Y_24OCT[day]) < 0.5 for w in wps[1:])
        for w in wps:
            assert all(lo < v < hi for v, (lo, hi) in zip(w["joints"], kin.limits))


def test_densify_keeps_endpoints_and_small_steps():
    pts = [[0, 0, 0, 0, 0], [10, -5, 0, 3, 0], [10, -5, 9, 3, 0]]
    out = box.densify(pts, max_step=2.0)
    assert out[0] == pts[0] and out[-1] == [float(v) for v in pts[-1]]
    assert max(max(abs(np.subtract(b, a))) for a, b in zip(out, out[1:])) <= 2.0 + 1e-9


class StrokeArm:
    def __init__(self, fail=False):
        self.calls, self.fail, self.q = [], fail, [0.0] * 5

    async def do_command(self, cmd):
        self.calls.append(("cmd", cmd))
        return {}

    async def move_through_joint_positions(self, path, options=None):
        self.calls.append(("path", len(path)))
        if self.fail:
            raise RuntimeError("serial timeout")
        self.q = list(path[-1].values)

    async def get_joint_positions(self):
        return type("J", (), {"values": self.q})()

    async def stop(self):
        self.calls.append(("stop",))


def test_stroke_is_one_continuous_path_to_the_press_then_a_lift(kin):
    arm = StrokeArm()
    wps = box.plan(kin, box.demo_box(), "wed", [0.0, 15.0, -10.0, 80.0, 3.0])
    assert asyncio.run(box.run_stroke(arm, wps))
    paths = [c for c in arm.calls if c[0] == "path"]
    assert len(paths) == 2 and paths[0][1] > len(wps)  # dense path to the press, then the lift
    torques = [c[1]["value"] for c in arm.calls if c[0] == "cmd" and c[1].get("command") == "set_torque_limit"]
    assert torques == [box.STROKE_TORQUE, 1000]


def test_torque_is_restored_when_the_stroke_fails(kin):
    arm = StrokeArm(fail=True)
    wps = box.plan(kin, box.demo_box(), "wed", [0.0, 15.0, -10.0, 80.0, 3.0])
    with pytest.raises(RuntimeError):
        asyncio.run(box.run_stroke(arm, wps))
    assert arm.calls[-1] == ("cmd", {"command": "set_torque_limit", "value": 1000})


def test_station_closes_with_the_stroke_once_a_box_is_registered(tmp_path):
    import actions
    import fakes
    (tmp_path / "box.json").write_text(__import__("json").dumps(__import__("dataclasses").asdict(TODAY)))
    arm = fakes.FakeArm()
    st = actions.Station(arm, fakes.FakeGripper(), fakes.FakeCamera(), {}, fakes.LIMITS, tmp_path / "log.jsonl",
                         box_path=tmp_path / "box.json")
    asyncio.run(st.refresh())
    assert asyncio.run(st.close_lid("wed")) == "Wednesday is closed" and st.lid["wed"] == "closed"
    assert len(arm.moves) > 10  # the dense stroke, not a two-pose press
    assert arm.commands[-1] == {"command": "set_torque_limit", "value": 1000}
    assert asyncio.run(st.close_lid("sun")) == "Sunday is closed"  # the end lids open and close on 24 Oct
