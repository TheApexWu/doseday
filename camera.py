"""One frame source for every rig: Viam camera (arm or fixed), a USB/laptop webcam, or a folder.

  viam            Viam camera named by PILL_CAMERA (needs VIAM_* env vars)
  webcam[:N]      OpenCV device N (default 0): laptop webcam today, a USB cam on a stand Friday
  dir:PATH        replay saved frames in order (rehearsal, offline debugging)

The camera id goes into every frame's sidecar. What matters is that enrollment and the run use
the SAME camera at the SAME height: sizes and colours do not transfer between cameras.
"""
import asyncio
from pathlib import Path

import cv2
import numpy as np

from config import CAMERA, CAMERA_SOURCE  # one set of names for every path


def decode_viam(imgs) -> np.ndarray:
    """First colour frame from a get_images reply; refuses depth and undecodable bytes instead of
    passing None downstream."""
    if not imgs:
        raise RuntimeError("camera returned no images")
    im = imgs[0]
    mime = str(getattr(im, "mime_type", ""))
    if "dep" in mime:
        raise RuntimeError(f"got a depth frame ({mime}); set PILL_CAMERA_SOURCE to the colour stream")
    img = cv2.imdecode(np.frombuffer(im.data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise RuntimeError(f"could not decode camera frame ({mime or 'unknown type'})")
    return img


def camera_id(source: str) -> str:
    if source == "viam":
        return "viam:" + CAMERA
    if source == "webcam":  # open_source treats a bare webcam as index 0
        return "webcam:0"
    return source


class Webcam:
    def __init__(self, index: int = 0, width: int = 1920, height: int = 1080):
        self.cap = cv2.VideoCapture(index)
        if not self.cap.isOpened():
            raise SystemExit(f"webcam {index} not available (macOS: allow camera access for the terminal)")
        # ask for the most pixels the device offers; it silently falls back if unsupported
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        for _ in range(10):  # auto-exposure settles over the first frames
            self.cap.read()

    def frame(self) -> np.ndarray:
        ok, img = self.cap.read()
        if not ok:
            raise RuntimeError("webcam read failed")
        return img

    def close(self):
        self.cap.release()


class Folder:
    def __init__(self, path: str):
        self.files = sorted(Path(path).glob("*.png")) + sorted(Path(path).glob("*.jpg"))
        if not self.files:
            raise SystemExit(f"no frames in {path}")
        self.i = 0

    def frame(self) -> np.ndarray:
        img = cv2.imread(str(self.files[self.i % len(self.files)]))
        self.i += 1
        return img

    def close(self):
        pass


class ViamCam:
    """HARDWARE-ONLY. Works for an arm-mounted or a fixed camera; no arm required."""
    def __init__(self):
        from arm import connect
        self.loop = asyncio.new_event_loop()
        self.robot = self.loop.run_until_complete(connect())

    def frame(self) -> np.ndarray:
        from viam.components.camera import Camera
        cam = Camera.from_robot(self.robot, CAMERA)
        imgs, _ = self.loop.run_until_complete(
            cam.get_images(filter_source_names=[CAMERA_SOURCE]) if CAMERA_SOURCE else cam.get_images())
        return decode_viam(imgs)

    def close(self):
        try:
            self.loop.run_until_complete(self.robot.close())
        finally:
            self.loop.close()


def open_source(source: str):
    if source == "viam":
        return ViamCam()
    if source.startswith("webcam"):
        return Webcam(int(source.split(":")[1]) if ":" in source else 0)
    if source.startswith("dir:"):
        return Folder(source[4:])
    raise SystemExit(f"unknown source {source!r}: use viam, webcam[:N] or dir:PATH")
