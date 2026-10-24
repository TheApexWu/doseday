"""Record the white arm at a fixed rate (joints, tip, jaw) with wrist-camera frames grabbed in parallel.

usage: python scripts/record_fast.py <seconds> <out_dir> [hz=15]
Joints and camera run as separate loops, so a slow frame never lowers the joint rate. Every call times out and
reconnects on failure; gaps go to gaps.csv. samples.csv and frames.csv share unix timestamps for syncing.
"""
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from viam.components.arm import Arm
from viam.components.camera import Camera
from viam.components.gripper import Gripper
from armctl import connect

TIMEOUT = 3.0


async def joints_loop(get_robot, out: Path, t_end: float, hz: float, gaps):
    rows = open(out / "samples.csv", "w", buffering=1)
    rows.write("n,unix_time,F0,F1,F2,F3,F4,x,y,z,o_x,o_y,o_z,theta,jaw_pct\n")
    n, period = 0, 1.0 / hz
    while time.time() < t_end:
        t0 = time.time()
        try:
            robot = await get_robot()
            arm = Arm.from_robot(robot, "follower-arm")
            f = (await asyncio.wait_for(arm.get_joint_positions(), TIMEOUT)).values
            p = await asyncio.wait_for(arm.get_end_position(), TIMEOUT)
            jaw = (await asyncio.wait_for(Gripper.from_robot(robot, "follower-gripper").do_command({"command": "get_position"}), TIMEOUT))["position_percentage"]
            rows.write(f"{n},{time.time():.3f}," + ",".join(f"{v:.3f}" for v in list(f) + [p.x, p.y, p.z, p.o_x, p.o_y, p.o_z, p.theta, jaw]) + "\n")
            n += 1
        except Exception as e:
            gaps.write(f"{time.time():.3f},joints,{type(e).__name__}: {str(e)[:80]}\n")
            await asyncio.sleep(0.5)
        await asyncio.sleep(max(0.0, period - (time.time() - t0)))
    return n


async def camera_loop(get_robot, out: Path, t_end: float, gaps):
    frames = out / "frames"
    frames.mkdir(parents=True, exist_ok=True)
    log = open(out / "frames.csv", "w", buffering=1)
    log.write("frame,unix_time\n")
    n = 0
    while time.time() < t_end:
        try:
            robot = await get_robot()
            res = await asyncio.wait_for(Camera.from_robot(robot, "follower-cam").get_images(), TIMEOUT)
            (frames / f"{n:05d}.jpg").write_bytes((res[0] if isinstance(res, tuple) else res)[0].data)
            log.write(f"{n},{time.time():.3f}\n")
            n += 1
        except Exception as e:
            gaps.write(f"{time.time():.3f},camera,{type(e).__name__}: {str(e)[:80]}\n")
            await asyncio.sleep(0.5)
    return n


async def main(seconds: float, out: Path, hz: float):
    out.mkdir(parents=True, exist_ok=True)
    gaps = open(out / "gaps.csv", "w", buffering=1)
    gaps.write("unix_time,loop,error\n")
    def client():
        """A connection per loop, so a dead arm read never cuts the camera stream (24 Oct)."""
        state = {"robot": None}

        async def get_robot(reset=False):
            if reset and state["robot"] is not None:
                try:
                    await asyncio.wait_for(state["robot"].close(), 3)
                except Exception:
                    pass
                state["robot"] = None
            if state["robot"] is None:
                state["robot"] = await asyncio.wait_for(connect(), 15)
            return state["robot"]
        return get_robot, state

    (gj, sj), (gc, sc) = client(), client()
    t_end = time.time() + seconds
    try:
        nj, nf = await asyncio.gather(joints_loop(gj, out, t_end, hz, gaps), camera_loop(gc, out, t_end, gaps))
    finally:
        for st in (sj, sc):
            if st["robot"] is not None:
                await st["robot"].close()
    print(f"done: {nj} joint samples ({nj / seconds:.1f}/s), {nf} frames -> {out}", flush=True)


if __name__ == "__main__":
    asyncio.run(main(float(sys.argv[1]), Path(sys.argv[2]), float(sys.argv[3]) if len(sys.argv) > 3 else 15.0))
