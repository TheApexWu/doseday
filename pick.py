"""Scripted pick-and-place from taught joint poses: hover, descend, close, lift, check the wrist camera, drop.

usage: python pick.py --trials 10 [--poses taught_joints.json | --switches] [--speed 50] [--descend-speed 30]
                      [--accel N] [--open 18]

Poses are 5 joint angles in degrees (base, shoulder, elbow, wrist pitch, wrist roll) named pick_hover, pick_down,
drop_hover, as {"pick_hover": [b, s, e, wp, wr], ...}. Teach pick_hover at least 60 mm above pick_down.
They come from a JSON file taught by teleop (`armctl.py where`), or with --switches from the
arm-position-saver switches of the same names, read with {"cfg": true} (stored in radians) and moved by this script
so the shoulder clamp applies.

Joint moves go straight to move_to_joint_positions, not through PillArm.move: PillArm plans Cartesian targets with
the motion service, which is still a stub, and joint moves are what ran on the arm on 23 Oct.
Every commanded and read-back joint vector is logged to logs/pick-<time>.jsonl.
"""
import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

import cv2
import numpy as np

from analyze_run import HOLD, hold_score

POSE_NAMES = ("pick_hover", "pick_down", "drop_hover")
SHOULDER_MIN = -104.8  # calibrated limit is -104.88; the rest pose (-105.05) is past it and the arm refuses it
SPEED_RANGE = (12.0, 180.0)  # below 12 deg/s the servos do not hold the commanded speed (module docs)
OPEN_PCT, CLOSED_PCT = 18.0, 0.0  # 18% fit every M&M in run 01 and costs ~4 s less per cycle than 95%
# Once candy stops the jaw, re-command just inside where it stopped: a 0% goal held against candy stalls the
# servo for the whole carry, and stalled STS3215s overheat.
GRIP_SQUEEZE_PCT = 1.0
# Run 01: with empty jaws 20-35 mm over the mat, candy lying below scored 0.22-0.31; from 60 mm up, empty
# scored <= 0.12 and held >= 0.20. So the hover must sit at least this far above the pick.
MIN_CHECK_RISE_MM = 55.0
SETTLE_TOL, SETTLE_READS, SETTLE_POLL_S, SETTLE_TIMEOUT_S = 0.5, 3, 0.1, 6.0


class PickRefused(RuntimeError):
    pass


def clamp(joints) -> list[float]:
    """Five joints in degrees, shoulder raised to its limit."""
    j = [float(v) for v in joints]
    if len(j) != 5:
        raise PickRefused(f"expected 5 joints, got {len(j)}")
    j[1] = max(j[1], SHOULDER_MIN)
    return j


def load_poses(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"no poses file at {path}: teach {', '.join(POSE_NAMES)} first")
    return check_poses(json.loads(path.read_text()))


def check_poses(poses: dict) -> dict:
    missing = [n for n in POSE_NAMES if n not in poses]
    if missing:
        raise SystemExit(f"poses file lacks {missing}")
    return {n: clamp(poses[n]) for n in POSE_NAMES}


def from_switch_cfg(cfg: dict) -> list[float]:
    """arm-position-saver stores the Go-side joint inputs, which are radians. A value past pi means the units
    are not what we think, so refuse rather than convert."""
    rad = cfg.get("joints") or []
    if len(rad) != 5 or max(abs(v) for v in rad) > 3.2:
        raise PickRefused(f"switch joints {rad} are not 5 radian values")
    return clamp(np.degrees(rad))


def joint_positions(values):
    """HARDWARE-ONLY. Tests replace this so they never import the SDK."""
    from viam.proto.component.arm import JointPositions
    return JointPositions(values=values)


class Picker:
    def __init__(self, arm, gripper, camera, log_path: Path, open_pct=OPEN_PCT, speed=50.0, descend_speed=30.0):
        for v in (speed, descend_speed):
            if not SPEED_RANGE[0] <= v <= SPEED_RANGE[1]:
                raise PickRefused(f"speed {v} outside {SPEED_RANGE}")
        self.arm, self.gripper, self.camera = arm, gripper, camera
        self.log_path, self.open_pct = log_path, open_pct
        self.speed, self.descend_speed = speed, descend_speed

    def log(self, entry: dict):
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a") as f:
            f.write(json.dumps({"t": round(time.time(), 3), **entry}) + "\n")

    async def joints(self) -> list[float]:
        return [round(v, 2) for v in (await self.arm.get_joint_positions()).values]

    async def move(self, joints, label: str, speed: float):
        target = clamp(joints)
        await self.arm.do_command({"set_speed": speed})
        self.log({"move": label, "commanded": target, "speed": speed})
        try:
            await self.arm.move_to_joint_positions(joint_positions(target))
        except Exception as e:
            # a refused move can still have moved another joint, so the log records where the arm really is
            self.log({"move": label, "error": f"{type(e).__name__}: {str(e)[:160]}", "at": await self.joints()})
            raise
        self.log({"move": label, "at": await self.joints()})

    async def jaw_to(self, pct: float) -> float:
        """set_position returns before the jaw settles on this deployment, so poll until the reading stops."""
        await self.gripper.do_command({"command": "set_position", "percentage": pct})
        last, still, t0 = await self.jaw(), 0, time.monotonic()
        while still < SETTLE_READS and time.monotonic() - t0 < SETTLE_TIMEOUT_S:
            await asyncio.sleep(SETTLE_POLL_S)
            now = await self.jaw()
            still = still + 1 if abs(now - last) < SETTLE_TOL else 0
            last = now
        self.log({"jaw": pct, "settled": round(last, 1), "s": round(time.monotonic() - t0, 2)})
        return last

    async def jaw(self) -> float:
        return float((await self.gripper.do_command({"command": "get_position"}))["position_percentage"])

    async def held(self) -> float:
        imgs, _ = await self.camera.get_images()
        img = cv2.imdecode(np.frombuffer(imgs[0].data, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise PickRefused("camera frame did not decode")
        return hold_score(img)

    async def pick_and_place(self, poses: dict, trial: int) -> int:
        """Returns the attempt that held (1 or 2). Refuses when the camera sees nothing after the retry."""
        await self.jaw_to(self.open_pct)
        await self.move(poses["pick_hover"], "pick_hover", self.speed)
        for attempt in (1, 2):
            await self.move(poses["pick_down"], "pick_down", self.descend_speed)
            z_down = (await self.arm.get_end_position()).z
            stopped = await self.jaw_to(CLOSED_PCT)
            if stopped > CLOSED_PCT + GRIP_SQUEEZE_PCT:
                await self.jaw_to(stopped - GRIP_SQUEEZE_PCT)
            await self.move(poses["pick_hover"], "lift", self.descend_speed)
            rise = (await self.arm.get_end_position()).z - z_down
            if rise < MIN_CHECK_RISE_MM:
                raise PickRefused(f"pick_hover is {rise:.0f} mm above pick_down; the camera check needs {MIN_CHECK_RISE_MM:.0f}")
            score = await self.held()
            self.log({"trial": trial, "attempt": attempt, "hold_score": round(score, 2)})
            if score > HOLD:
                break
            await self.jaw_to(self.open_pct)
        else:
            raise PickRefused(f"trial {trial}: camera sees nothing between the jaws after a retry")
        await self.move(poses["drop_hover"], "drop_hover", self.speed)
        await self.jaw_to(self.open_pct)
        await self.move(poses["pick_hover"], "return", self.speed)
        return attempt

    async def run(self, poses: dict, trials: int) -> list[int]:
        self.log({"start": await self.joints(), "poses": poses})
        done = []
        try:
            for n in range(1, trials + 1):
                done.append(await self.pick_and_place(poses, n))
                self.log({"trial": n, "ok": True, "attempts": done[-1]})
        except Exception as e:
            self.log({"stopped": f"{type(e).__name__}: {str(e)[:160]}", "after_trials": len(done)})
            await self.arm.stop()
            self.log({"stopped_at": await self.joints()})
            raise SystemExit(f"stopped after {len(done)} trials: {e}")
        return done


async def _main(args):
    """HARDWARE-ONLY."""
    from viam.components.arm import Arm
    from viam.components.camera import Camera
    from viam.components.gripper import Gripper
    from viam.components.switch import Switch

    from arm import connect
    from record_teleop import load_env

    for k, v in load_env().items():  # keys live in .env, arm.connect reads the environment
        os.environ.setdefault(k, v)
    robot = await connect()
    try:
        arm = Arm.from_robot(robot, "follower-arm")
        if args.switches:
            poses = {n: from_switch_cfg(await Switch.from_robot(robot, n).do_command({"cfg": True})) for n in POSE_NAMES}
        else:
            poses = load_poses(args.poses)
        if args.accel:
            await arm.do_command({"set_acceleration": args.accel})
        p = Picker(arm, Gripper.from_robot(robot, "follower-gripper"), Camera.from_robot(robot, "follower-cam"),
                   Path("logs") / f"pick-{time.strftime('%H%M%S')}.jsonl", args.open, args.speed, args.descend_speed)
        print("motion params:", await arm.do_command({"get_motion_params": True}))
        done = await p.run(poses, args.trials)
        print(f"{len(done)} trials, first-try holds {done.count(1)}, log {p.log_path}")
    finally:
        await robot.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--trials", type=int, default=1)
    ap.add_argument("--poses", type=Path, default=Path("taught_joints.json"))
    ap.add_argument("--switches", action="store_true")
    ap.add_argument("--speed", type=float, default=50.0)
    ap.add_argument("--descend-speed", type=float, default=30.0)
    ap.add_argument("--accel", type=float)
    ap.add_argument("--open", type=float, default=OPEN_PCT)
    asyncio.run(_main(ap.parse_args(sys.argv[1:])))
