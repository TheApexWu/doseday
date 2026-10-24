"""Hover the claw over each pick spot of a recorded run, without grabbing, saving a wrist-camera frame at each.

usage: python scripts/hover_spots.py <plan.json> <frames_dir> [start_step]
The plan holds joint targets from box.Kinematics.ik. The wrist roll is held at its current reading so the roll
servo never turns: the claw tip lies on the roll axis, so its position does not depend on roll.
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from viam.components.arm import Arm
from viam.components.camera import Camera
from viam.proto.component.arm import JointPositions
from armctl import connect, joint_limits, wait_arrival

SPEED = 30.0
DWELL_S = 3.0


async def main(plan_path: Path, frames: Path, start: int = 0):
    plan = json.loads(plan_path.read_text())
    frames.mkdir(parents=True, exist_ok=True)
    robot = await connect()
    follower = Arm.from_robot(robot, "follower-arm")
    cam = Camera.from_robot(robot, "follower-cam")
    try:
        wrist = (await follower.get_joint_positions()).values[4]
        lims = await joint_limits(follower)
        if not lims[4][0] + 5 <= wrist <= lims[4][1] - 5:
            sys.exit(f"wrist reads {wrist:.1f}, outside {lims[4]}: re-zero it before moving")
        targets = [p["joints"][:4] + [wrist] for p in plan]
        for t in targets:
            bad = [n for n, (v, (lo, hi)) in enumerate(zip(t, lims)) if not lo + 0.5 <= v <= hi - 0.5]
            if bad:
                sys.exit(f"target {t} breaks joint limits {bad}: nothing moved")
        await follower.do_command({"set_speed": SPEED})
        for k, (p, t) in enumerate(zip(plan, targets)):
            if k < start:
                continue
            await follower.move_to_joint_positions(JointPositions(values=t))
            if not await wait_arrival(follower, t, SPEED):
                # gravity sags the extended arm about 1 deg; stopped within 2 deg counts as arrived
                now = (await follower.get_joint_positions()).values
                if await follower.is_moving() or max(abs(a - b) for a, b in zip(now, t)) > 2.0:
                    sys.exit(f"step {k} ({p['pill']} {p['tag']}) did not arrive: stopping")
            if p["tag"] == "hover":
                await asyncio.sleep(DWELL_S)
                res = await cam.get_images()
                (frames / f"{k:02d}-{p['pill'].replace(' ', '-')}.jpg").write_bytes((res[0] if isinstance(res, tuple) else res)[0].data)
            print(f"step {k:2d} {p['pill']:17s} {p['tag']:7s} ok", flush=True)
    except BaseException:
        await follower.stop()
        raise
    finally:
        await follower.do_command({"set_speed": 50})
        await robot.close()


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3]) if len(sys.argv) > 3 else 0))
