"""Grab labelled frames from the camera you will RUN with. Works today on a laptop webcam.

  python capture.py oval -n 10                         webcam 0 (default), Enter between shots
  python capture.py oval -n 10 --source viam           Viam camera (fixed or on the arm), no arm motion
  python capture.py oval -n 10 --source viam --arm-photo-pose   eye-in-hand: move to the taught photo pose first
  python capture.py scene -n 1 --no-prompt
  python capture.py --list

Every frame gets a sidecar with the camera id; enroll / run refuse images without one, and a run
refuses pills enrolled on a different camera. Never feed phone photos taken on the side.
"""
import argparse
import asyncio
import time
from pathlib import Path

import cv2

import provenance
from camera import camera_id, open_source

HERE = Path(__file__).parent
DATA = HERE / "data"
PHOTO_POSE_TOL_MM = 1.0


def move_to_photo_pose() -> dict:
    """HARDWARE-ONLY. Eye-in-hand rigs: calibration only holds at the taught photo pose."""
    from arm import FIXED_THETA, PillArm, connect, load_poses

    async def go():
        poses = load_poses()
        ph = poses["photo"]
        robot = await connect()
        try:
            a = PillArm(robot, table_z=poses["table_z"])
            await a.move(ph["x"], ph["y"], ph["z"], FIXED_THETA, "photo")
            where = await a._hw_where()
        finally:
            await robot.close()
        off = max(abs(where[k] - ph[k]) for k in ("x", "y", "z"))
        if off > PHOTO_POSE_TOL_MM:
            raise SystemExit(f"REFUSED: arm is {off:.1f} mm off the photo pose; calibration would not hold")
        return where

    return asyncio.run(go())


def grab(label: str, n: int, source: str, prompt: bool, pose: dict | None, out_root: Path = DATA) -> list:
    cam = open_source(source)
    out = out_root / label
    out.mkdir(parents=True, exist_ok=True)
    saved = []
    try:
        for i in range(n):
            if prompt:
                input(f"[{i + 1}/{n}] place/move the pill, Enter to shoot ")
            img = cam.frame()
            path = out / f"{time.strftime('%H%M%S')}_{i:02d}.png"
            cv2.imwrite(str(path), img)
            provenance.write(path, provenance.CAPTURED, camera=camera_id(source), label=label,
                             pose=pose, width=img.shape[1], height=img.shape[0])
            print(f"saved {path} {img.shape[1]}x{img.shape[0]} [{camera_id(source)}]")
            saved.append(path)
    finally:
        cam.close()
    return saved


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("label", nargs="?")
    ap.add_argument("-n", type=int, default=10)
    ap.add_argument("--source", default="webcam:0", help="viam | webcam[:N] | dir:PATH")
    ap.add_argument("--arm-photo-pose", action="store_true", help="move the arm to the taught photo pose first")
    ap.add_argument("--no-prompt", action="store_true", help="shoot n frames back to back")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args(argv)
    if args.list or not args.label:
        for d in sorted(p for p in DATA.glob("*") if p.is_dir()):
            print(f"{d.name}: {len(list(d.glob('*.png')))} frames")
        return
    pose = move_to_photo_pose() if args.arm_photo_pose else None
    return grab(args.label, args.n, args.source, not args.no_prompt, pose)


if __name__ == "__main__":
    main()
