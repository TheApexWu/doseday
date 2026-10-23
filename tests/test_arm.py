import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest

import arm
from arm import MoveRefused, PillArm, grip_theta


class FakeArm(PillArm):
    """Replaces the three Viam calls; everything else is the real code path."""

    def __init__(self, plan_ok=True, **kw):
        super().__init__(robot=None, **kw)
        self.calls, self.plan_ok, self.at = [], plan_ok, None

    async def _hw_plan(self, target, straight):
        self.calls.append(("plan", target["z"], target["theta"]))
        if not self.plan_ok:
            raise RuntimeError("no path")

    async def _hw_move(self, target, straight):
        self.calls.append(("move", target["z"], target["theta"]))
        self.at = target

    async def _hw_where(self):
        return dict(self.at)

    async def _hw_gripper(self, action):
        self.calls.append(("grip", action))


def lines(a):
    return [json.loads(x) for x in a.log_path.read_text().splitlines()]


def test_importable_without_viam():
    """Fresh interpreter: importing arm must not pull in the SDK, so dry runs work on any laptop."""
    code = "import arm, sys; assert not any(m.split('.')[0] == 'viam' for m in sys.modules)"
    subprocess.run([sys.executable, "-c", code], cwd=Path(arm.__file__).parent, check=True)


def test_grip_theta_perpendicular_and_bounded():
    """Always in [-90, 90): no drift toward the wrist's limits however many picks run."""
    for axis in (0, 10, 45, 89, 135, 179):
        for cur in (-170, -30, 0, 60, 170, 260):
            th = grip_theta(axis, cur, sign=1, jaw0=0)
            assert (th - (axis + 90)) % 180 == pytest.approx(0, abs=1e-9) or \
                (th - (axis + 90)) % 180 == pytest.approx(180, abs=1e-9)
            assert -90 <= th < 90


def test_grip_theta_round_keeps_wrist():
    assert grip_theta(None, 37.0) == 37.0


def test_grip_theta_sign_flip_changes_answer():
    """Negative control for T4: a wrong sign gives a different wrist angle for an oblique pill."""
    assert grip_theta(30, 0, sign=1, jaw0=0) != pytest.approx(grip_theta(30, 0, sign=-1, jaw0=0))


def test_plan_failure_means_no_move(tmp_path):
    a = FakeArm(plan_ok=False, table_z=10.0, log_path=tmp_path / "a.jsonl")
    with pytest.raises(MoveRefused):
        asyncio.run(a.move(300, 0, 100, 0, "x"))
    assert [c[0] for c in a.calls] == ["plan"]
    assert "refused" in lines(a)[-1]


def test_floor_refused_before_planner(tmp_path):
    a = FakeArm(table_z=10.0, log_path=tmp_path / "a.jsonl")
    with pytest.raises(MoveRefused):
        asyncio.run(a.move(300, 0, 9.0, 0, "too low"))
    assert a.calls == []


def test_no_table_z_refuses(tmp_path):
    a = FakeArm(table_z=None, log_path=tmp_path / "a.jsonl")
    with pytest.raises(MoveRefused):
        asyncio.run(a.move(300, 0, 100, 0))


def test_pick_sequence_and_log(tmp_path):
    a = FakeArm(table_z=10.0, log_path=tmp_path / "a.jsonl")
    theta = asyncio.run(a.pick(300, 20, axis_yaw_deg=30.0))
    hover, grasp = 10 + arm.HOVER_MM, 10 + arm.GRASP_ABOVE_MAT_MM
    seq = [c for c in a.calls if c[0] != "plan"]
    assert seq == [("grip", "open"), ("move", hover, theta), ("move", grasp, theta),
                   ("grip", "close"), ("move", hover, theta)]
    every_move = [e for e in lines(a) if "reached" in e]
    assert len(every_move) == 3 and all(e["target"]["theta"] == theta for e in every_move)
    assert a.calls.index(("plan", grasp, theta)) < a.calls.index(("move", grasp, theta))


def test_yaw_off_control_uses_fixed_theta(tmp_path):
    a = FakeArm(table_z=10.0, yaw_align=False, log_path=tmp_path / "a.jsonl")
    assert asyncio.run(a.pick(300, 20, axis_yaw_deg=30.0)) == arm.FIXED_THETA


def test_gripper_is_set_by_percentage_and_grab_is_never_used():
    """SO-101 gripper: set_position by percentage. grab() stops on contact and is never called."""
    assert arm.gripper_command("open") == {"command": "set_position", "percentage": arm.GRIPPER_OPEN_PCT}
    assert arm.gripper_command("close") == {"command": "set_position", "percentage": arm.GRIPPER_CLOSE_PCT}
    assert ".grab(" not in Path(arm.__file__).read_text()
