"""Save camera frames to logs/snaps-<time>/ once per interval. Never moves anything.
usage: python snap.py [seconds=180] [camera=follower-cam] [interval=1.0]"""
import asyncio, sys, time
from datetime import datetime
from viam.robot.client import RobotClient
from viam.components.camera import Camera
from record_teleop import load_env, HERE

async def main(seconds, cam_name, interval):
    env = load_env()
    robot = await RobotClient.at_address(env["VIAM_ADDRESS"], RobotClient.Options.with_api_key(api_key=env["VIAM_API_KEY"], api_key_id=env["VIAM_API_KEY_ID"]))
    out = HERE / "logs" / f"snaps-{datetime.now():%H%M%S}"
    out.mkdir(parents=True, exist_ok=True)
    cam, t0, n = Camera.from_robot(robot, cam_name), time.monotonic(), 0
    try:
        while (t := time.monotonic() - t0) < seconds:
            try:
                imgs, _ = await cam.get_images()
                (out / f"{t:06.1f}s.jpg").write_bytes(imgs[0].data)
                n += 1
            except Exception as e:
                print(f"{t:5.1f}s snap failed: {str(e)[:80]}", flush=True)
            await asyncio.sleep(max(0, interval - (time.monotonic() - t0 - t)))
    finally:
        await robot.close()
        print(f"saved {n} frames to {out}", flush=True)

a = sys.argv[1:]
asyncio.run(main(float(a[0]) if a else 180, a[1] if len(a) > 1 else "follower-cam", float(a[2]) if len(a) > 2 else 1.0))
