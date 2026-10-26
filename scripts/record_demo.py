"""Record the follower's joints, tip, jaw and wrist-camera frames together, surviving connection stalls.

usage: python scripts/record_demo.py <seconds> <out_dir>
Every robot call times out after 3 s; on failure the client reconnects and the gap is written to gaps.csv,
so a stalled link shows up as a logged gap instead of a recording that silently stops.
"""
import asyncio
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from viam.components.arm import Arm
from viam.components.camera import Camera
from viam.components.gripper import Gripper
from armctl import connect

CALL_TIMEOUT = 3.0
HZ = float(os.environ.get("RECORD_HZ", 20))


async def sample(robot, frames: Path, n: int):
    follower = Arm.from_robot(robot, "follower-arm")
    leader = Arm.from_robot(robot, "leader-arm")
    cam = Camera.from_robot(robot, os.environ.get("PILL_CAMERA", "follower-cam"))

    async def grip(name):
        try:  # the hand's intent: teleop on arm3 mirrors only part of the leader's opening onto the follower
            return (await Gripper.from_robot(robot, name).do_command({"command": "get_position"}))["position_percentage"]
        except Exception:
            return float("nan")
    # all reads in parallel: one round trip per sample instead of six, which is what 20 frames a second needs
    f, l, p, jaw, lead, res = await asyncio.wait_for(asyncio.gather(
        follower.get_joint_positions(), leader.get_joint_positions(), follower.get_end_position(),
        grip("follower-gripper"), grip("leader-gripper"), cam.get_images()), CALL_TIMEOUT)
    (frames / f"{n:05d}.jpg").write_bytes((res[0] if isinstance(res, tuple) else res)[0].data)
    return list(f.values) + list(l.values) + [p.x, p.y, p.z, p.o_x, p.o_y, p.o_z, p.theta, jaw, lead]


async def main(seconds: float, out: Path):
    frames = out / "frames"
    frames.mkdir(parents=True, exist_ok=True)
    rows = open(out / "samples.csv", "w", buffering=1)
    gaps = open(out / "gaps.csv", "w", buffering=1)
    rows.write("frame,unix_time,F0,F1,F2,F3,F4,L0,L1,L2,L3,L4,x,y,z,o_x,o_y,o_z,theta,jaw_pct,leader_jaw_pct\n")
    gaps.write("start,end,error\n")
    t0, n, robot = time.time(), 0, None
    while time.time() - t0 < seconds:
        try:
            if robot is None:
                robot = await asyncio.wait_for(connect(), 15)
            tick = time.time()
            vals = await sample(robot, frames, n)
            rows.write(f"{n},{time.time():.3f}," + ",".join(f"{v:.3f}" for v in vals) + "\n")
            n += 1
            await asyncio.sleep(max(0.0, 1 / HZ - (time.time() - tick)))
            if n % 50 == 0:
                print(f"{time.time() - t0:5.0f}s  {n} samples", flush=True)
        except Exception as e:
            gap_start = time.time()
            if robot is not None:
                try:
                    await asyncio.wait_for(robot.close(), 3)
                except Exception:
                    pass
            robot = None
            gaps.write(f"{gap_start:.3f},{time.time():.3f},{type(e).__name__}: {str(e)[:80]}\n")
            print(f"{time.time() - t0:5.0f}s  gap, reconnecting ({type(e).__name__})", flush=True)
    if robot is not None:
        await robot.close()
    print(f"done: {n} samples in {time.time() - t0:.0f}s -> {out}", flush=True)


if __name__ == "__main__":
    asyncio.run(main(float(sys.argv[1]), Path(sys.argv[2])))
