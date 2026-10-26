"""Replay a teleop recording (scripts/record_demo.py) on the follower, on a loop, at the recorded pace.

usage: python scripts/loop_replay.py <run_dir> [loops] [--speed 45] [--until S] [--from S] [--rate X] [--jaw-open PCT] [--dry-run]
  --from S / --rate X  start S seconds in, and play X times faster (0.5-2.0)
  --until S       replay only the first S seconds (the rest of a recording is often the arm parked)
  --jaw-open PCT  any recorded opening over 5% becomes PCT, anything under closes fully: teleop mirrored
                  only a few % of the leader's opening on arm3, too little to release a pill
  loops 0 = until Ctrl-C. Teleop is stopped first. Every target is clamped to the follower's joint limits,
  each loop starts with a slow move to the recording's first pose, and Ctrl-C leaves the arm holding still.
HARDWARE-ONLY. Same arm and same table as the recording: joint replay does not look for anything.
"""
import asyncio
import csv
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

STEP_S = 0.2        # 5 targets a second: smooth enough, and the bus keeps up
APPROACH_SPEED = 20  # deg/s for the move to the start pose
JAW_STEP = 3.0      # % change before the jaw is commanded again


def load(run: Path, until: float = 1e9, jaw_open: float | None = None, start: float = 0.0, rate: float = 1.0):
    rows = list(csv.DictReader((run / "samples.csv").open()))
    t0 = float(rows[0]["unix_time"])
    out, last = [], -STEP_S
    for r in rows:
        t = float(r["unix_time"]) - t0
        if t < start:
            continue
        if t > until:
            break
        if t - last >= STEP_S:
            g = float(r["jaw_pct"])
            if r.get("leader_jaw_pct") not in (None, "", "nan"):
                g = float(r["leader_jaw_pct"])  # what the hand did, not the follower's partial mirror
            if jaw_open is not None:
                g = jaw_open if g > 5.0 else 0.0
            out.append(((t - start) / rate, [float(r[f"F{k}"]) for k in range(5)], g))
            last = t
    return out


async def main(run: Path, loops: int, speed: float, dry: bool, until: float = 1e9, jaw_open: float | None = None,
               start: float = 0.0, rate: float = 1.0):
    path = load(run, until, jaw_open, start, rate)
    print(f"{len(path)} targets over {path[-1][0]:.0f} s from {run.name}")
    if dry:
        return
    from viam.components.arm import Arm
    from viam.components.gripper import Gripper
    from viam.proto.component.arm import JointPositions
    from viam.services.generic import Generic
    from armctl import connect, joint_limits, wait_arrival

    robot = await connect()
    arm = Arm.from_robot(robot, "follower-arm")
    jaw = Gripper.from_robot(robot, "follower-gripper")
    lims = await joint_limits(arm)

    def clamp(js):
        return [min(max(v, lo + 0.5), hi - 0.5) for v, (lo, hi) in zip(js, lims)]

    try:
        print("teleop:", await Generic.from_robot(robot, os.environ.get("PILL_TELEOP", "teleop")).do_command({"command": "stop"}))
        n = 0
        while loops == 0 or n < loops:
            n += 1
            await arm.do_command({"set_speed": APPROACH_SPEED})
            first = clamp(path[0][1])
            await arm.move_to_joint_positions(JointPositions(values=first))
            await wait_arrival(arm, first, APPROACH_SPEED)
            await jaw.do_command({"command": "set_position", "percentage": path[0][2]})
            await arm.do_command({"set_speed": speed})
            print(f"loop {n}", flush=True)
            start, last_jaw = time.monotonic(), path[0][2]
            for t, js, g in path:
                await asyncio.sleep(max(0.0, t - (time.monotonic() - start)))
                await arm.move_to_joint_positions(JointPositions(values=clamp(js)))
                if abs(g - last_jaw) >= JAW_STEP:
                    await jaw.do_command({"command": "set_position", "percentage": g})
                    last_jaw = g
            await asyncio.sleep(1.0)
    finally:
        await arm.do_command({"set_speed": 50})
        await arm.stop()
        await robot.close()
        print("stopped; arm holding")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    def opt(name, default):
        return float(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default
    speed, until, jaw_open = opt("--speed", 45.0), opt("--until", 1e9), opt("--jaw-open", None)
    start, rate = opt("--from", 0.0), opt("--rate", 1.0)
    if not 0.5 <= rate <= 2.0:
        sys.exit("rate must be 0.5-2.0")
    if not 12 <= speed <= 60:
        sys.exit("speed must be 12-60 deg/s")
    flags = {sys.argv[i + 1] for i, a in enumerate(sys.argv[:-1]) if a in ("--speed", "--until", "--jaw-open", "--from", "--rate")}
    args = [a for a in args if a not in flags]
    try:
        asyncio.run(main(Path(args[0]), int(args[1]) if len(args) > 1 else 0, speed, "--dry-run" in sys.argv, until, jaw_open, start, rate))
    except KeyboardInterrupt:
        pass
