"""pick.py driven by fake arm, gripper and camera objects: no network, no SDK."""
import asyncio
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

import pick
from analyze_run import GAP

POSES = {"pick_hover": [-14.0, -33.2, 46.1, 77.1, -80.0],
         "pick_down": [-14.0, -22.8, 58.8, 54.0, -80.0],
         "drop_hover": [-21.3, 31.5, -30.6, 89.1, -80.0]}
Z = {"pick_hover": 160.0, "pick_down": 95.0, "drop_hover": 160.0}


def frame(held: bool) -> bytes:
    img = np.full((480, 640, 3), 235, np.uint8)
    if held:
        img[GAP] = (40, 40, 200)
    return cv2.imencode(".jpg", img)[1].tobytes()


class FakeArm:
    def __init__(self, z=Z, fail_on=None, poses=POSES):
        self.at, self.moves, self.commands, self.stopped = list(poses["pick_hover"]), [], [], False
        self.z, self.fail_on, self.poses = z, fail_on, poses

    async def get_joint_positions(self):
        return SimpleNamespace(values=self.at)

    async def move_to_joint_positions(self, values):
        self.moves.append(list(values))
        if self.fail_on and list(values) == self.fail_on:
            self.at = [self.at[0] + 3.0, *self.at[1:]]  # refused, but the base still moved
            raise RuntimeError("joint 2 out of range")
        self.at = list(values)

    async def get_end_position(self):
        name = next(n for n, j in self.poses.items() if pick.clamp(j) == self.at)
        return SimpleNamespace(z=self.z[name])

    async def do_command(self, cmd):
        self.commands.append(cmd)
        return {}

    async def stop(self):
        self.stopped = True


class FakeGripper:
    def __init__(self):
        self.pos, self.sets = 0.0, []

    async def do_command(self, cmd):
        if cmd["command"] == "set_position":
            self.sets.append(cmd["percentage"])
            self.pos = cmd["percentage"]
            return {"success": True}
        return {"position_percentage": self.pos}

    async def grab(self):
        raise AssertionError("grab() must never be called")


class FakeCamera:
    def __init__(self, held_seq):
        self.seq = list(held_seq)

    async def get_images(self):
        return [SimpleNamespace(data=frame(self.seq.pop(0)))], None


@pytest.fixture(autouse=True)
def no_sdk(monkeypatch):
    monkeypatch.setattr(pick, "joint_positions", lambda v: v)
    monkeypatch.setattr(pick, "SETTLE_POLL_S", 0.0)


def rig(tmp_path, held_seq, **arm_kw):
    arm, grip = FakeArm(**arm_kw), FakeGripper()
    return pick.Picker(arm, grip, FakeCamera(held_seq), tmp_path / "p.jsonl"), arm, grip


def logs(p):
    return [json.loads(x) for x in p.log_path.read_text().splitlines()]


def test_one_trial_order_and_jaw(tmp_path):
    p, arm, grip = rig(tmp_path, [True])
    assert asyncio.run(p.run(pick.check_poses(POSES), 1)) == [1]
    order = [next(n for n, j in POSES.items() if pick.clamp(j) == m) for m in arm.moves]
    assert order == ["pick_hover", "pick_down", "pick_hover", "drop_hover", "pick_hover"]
    assert grip.sets == [pick.OPEN_PCT, pick.CLOSED_PCT, pick.OPEN_PCT]
    assert {"set_speed": 30.0} in arm.commands and {"set_speed": 50.0} in arm.commands


def test_retry_once_then_hold(tmp_path):
    p, arm, _ = rig(tmp_path, [False, True])
    assert asyncio.run(p.run(pick.check_poses(POSES), 1)) == [2]


def test_refuses_when_camera_sees_nothing_after_retry(tmp_path):
    p, arm, grip = rig(tmp_path, [False, False])
    with pytest.raises(SystemExit, match="nothing between the jaws"):
        asyncio.run(p.run(pick.check_poses(POSES), 3))
    assert grip.sets.count(pick.CLOSED_PCT) == 2
    assert pick.clamp(POSES["drop_hover"]) not in arm.moves
    assert arm.stopped and "stopped_at" in logs(p)[-1]


def test_shoulder_clamped(tmp_path):
    low = dict(POSES, pick_hover=[-14.0, -105.05, 46.1, 77.1, -80.0])
    p, arm, _ = rig(tmp_path, [True], poses=low)
    asyncio.run(p.run(low, 1))  # unclamped on purpose: the move path must clamp by itself
    assert arm.moves[0][1] == pick.SHOULDER_MIN
    assert min(m[1] for m in arm.moves) >= pick.SHOULDER_MIN


def test_never_calls_grab(tmp_path):
    p, *_ = rig(tmp_path, [False, True])
    asyncio.run(p.run(pick.check_poses(POSES), 1))  # FakeGripper.grab raises if reached
    assert "grab(" not in Path(pick.__file__).read_text()


def test_error_rereads_joints(tmp_path):
    p, arm, _ = rig(tmp_path, [True], fail_on=pick.clamp(POSES["pick_down"]))
    with pytest.raises(SystemExit, match="out of range"):
        asyncio.run(p.run(pick.check_poses(POSES), 1))
    err = next(e for e in logs(p) if "error" in e)
    assert err["at"][0] == pytest.approx(POSES["pick_hover"][0] + 3.0)


def test_low_hover_refused(tmp_path):
    p, *_ = rig(tmp_path, [True], z={"pick_hover": 130.0, "pick_down": 95.0, "drop_hover": 160.0})
    with pytest.raises(SystemExit, match="camera check needs"):
        asyncio.run(p.run(pick.check_poses(POSES), 1))


def test_slow_speed_refused(tmp_path):
    with pytest.raises(pick.PickRefused):
        pick.Picker(None, None, None, tmp_path / "p.jsonl", descend_speed=8.0)


def test_switch_cfg_radians_only():
    assert pick.from_switch_cfg({"joints": [0.0, -1.84, 0.5, 1.0, -1.4]})[1] == pick.SHOULDER_MIN
    with pytest.raises(pick.PickRefused):
        pick.from_switch_cfg({"joints": [-14.0, -33.2, 46.1, 77.1, -80.0]})


def test_missing_pose_stops_before_moving(tmp_path):
    f = tmp_path / "t.json"
    f.write_text(json.dumps({"pick_hover": POSES["pick_hover"]}))
    with pytest.raises(SystemExit, match="lacks"):
        pick.load_poses(f)


def test_importable_without_viam():
    code = "import pick, sys; assert not any(m.split('.')[0] == 'viam' for m in sys.modules)"
    subprocess.run([sys.executable, "-c", code], cwd=Path(pick.__file__).parent, check=True)
