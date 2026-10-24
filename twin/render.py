"""Stills and clips from the twin. Offscreen on macOS needs MUJOCO_GL=cgl (set here).

    python twin/render.py still RUN_CSV T OUT_DIR     every camera at time T of a recorded run
"""
from __future__ import annotations

import csv
import os
import sys
from pathlib import Path

os.environ.setdefault("MUJOCO_GL", "cgl")
import imageio.v2 as imageio  # noqa: E402
import mujoco  # noqa: E402
import numpy as np  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from twin.scene import Twin  # noqa: E402

CAMERAS = ["user", "front", "side", "top", "box", "wrist"]
SIZE = {"wrist": (480, 640)}  # the real wrist camera is 640x480


def read_run(path) -> list[dict]:
    return [{k: float(v) for k, v in r.items() if v not in ("", None)} for r in csv.DictReader(Path(path).open())]


def row_at(rows, t):
    return min(rows, key=lambda r: abs(r["t"] - t))


def joints(r):
    return [r[f"F{i}"] for i in range(5)]


class Camera:
    def __init__(self, twin: Twin, height=720, width=1280):
        self.twin = twin
        self.renderers = {}
        self.height, self.width = height, width

    def frame(self, cam: str) -> np.ndarray:
        h, w = SIZE.get(cam, (self.height, self.width))
        if (h, w) not in self.renderers:
            self.renderers[(h, w)] = mujoco.Renderer(self.twin.model, height=h, width=w)
        r = self.renderers[(h, w)]
        r.update_scene(self.twin.data, camera=cam)
        return r.render()


def still(run_csv, t, out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    twin = Twin()
    r = row_at(read_run(run_csv), float(t))
    twin.set_arm(joints(r), r.get("jaw_pct"))
    mujoco.mj_forward(twin.model, twin.data)
    cam = Camera(twin)
    for c in CAMERAS:
        imageio.imwrite(out / f"{c}_{float(t):.1f}.png", cam.frame(c))
    print(f"t={r['t']:.1f} joints {np.round(joints(r), 1).tolist()} jaw {r.get('jaw_pct')} tip {np.round(twin.tip(), 1).tolist()}")


if __name__ == "__main__":
    if sys.argv[1] == "still":
        still(*sys.argv[2:5])
