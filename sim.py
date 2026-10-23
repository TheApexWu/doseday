"""Simulated arm and mat for rehearsing the live loop with no hardware: python demo.py run --sim

A fixed camera looks down at a 150 x 100 mm matte black mat (white and bright-coloured pills). The
gripper holds a pill only when the jaws close within GRIP_TOL_MM of its centre and across its long
axis (within GRIP_TOL_DEG; round pills grip at any angle). These tolerances are assumptions, not
measurements: the sim tests the code path and the logic, never the physics. --sim-theta-sign -1
makes the simulated wrist turn the other way, which is what an unmeasured T4 looks like.
"""
import random

import cv2
import numpy as np

import arm
from calib import Calibration
from pills import Registry, features, from_samples
import vision

PX_PER_MM = 4.0
OFF_PX = (20.0, 40.0)               # mat origin in the image
MAT_MM = (150.0, 100.0)
T_MAT_TO_ROBOT = (250.0, -100.0)    # robot = mat + this (no rotation)
TABLE_Z = 0.0
GRIP_TOL_MM = 2.5
GRIP_TOL_DEG = 20.0
SLOT_DROP_TOL_MM = 30.0
TYPES = {  # length mm, width mm, BGR, mat half
    "oval": (10.0, 4.0, (235, 235, 235), "black"),
    "capsule": (14.0, 5.0, (200, 60, 20), "black"),   # bright blue: dark pills vanish on black
}


def calibration() -> Calibration:
    k, (ox, oy) = PX_PER_MM, OFF_PX
    px_from_mat = np.array([[k, 0, ox], [0, k, oy], [0, 0, 1]], float)
    photo = {"x": T_MAT_TO_ROBOT[0] + MAT_MM[0] / 2, "y": T_MAT_TO_ROBOT[1] + MAT_MM[1] / 2, "z": 300.0}
    return Calibration(H=np.linalg.inv(px_from_mat).tolist(), theta_deg=0.0, t=list(T_MAT_TO_ROBOT),
                       table_z=TABLE_Z, photo_pose=photo)


class World:
    def __init__(self, counts: dict, seed: int = 0):
        self.rng = random.Random(seed)
        self.pills: list[dict] = []
        self.slots: dict[str, list[str]] = {}
        for kind, n in counts.items():
            for _ in range(n):
                self.pills.append(self._place(kind))

    def _place(self, kind):
        x0, x1 = 12, MAT_MM[0] - 12
        for _ in range(200):  # keep pills apart so the sim does not test the merged-blob path by accident
            p = {"type": kind, "x": self.rng.uniform(x0, x1), "y": self.rng.uniform(12, MAT_MM[1] - 12),
                 "a": self.rng.uniform(0, 180)}
            if all(np.hypot(p["x"] - q["x"], p["y"] - q["y"]) > 18 for q in self.pills):
                return p
        raise RuntimeError("mat too crowded for the sim")

    def render(self, only=None) -> np.ndarray:
        img = np.full((480, 640, 3), 15, np.uint8)
        for p in (only if only is not None else self.pills):
            L, W, color, _ = TYPES[p["type"]]
            c = (int(OFF_PX[0] + p["x"] * PX_PER_MM), int(OFF_PX[1] + p["y"] * PX_PER_MM))
            cv2.ellipse(img, c, (int(L * PX_PER_MM / 2), int(W * PX_PER_MM / 2)), p["a"], 0, 360, color, -1)
        noise = np.random.default_rng(len(self.pills)).normal(0, 2, img.shape)
        return np.clip(img + noise, 0, 255).astype(np.uint8)


def slot_poses(schedule: dict) -> dict:
    """A row of funnels just past the mat's far edge, one per slot."""
    poses = {}
    for i, slot in enumerate(schedule):
        poses[slot] = {"x": T_MAT_TO_ROBOT[0] + 10 + i * 20.0, "y": T_MAT_TO_ROBOT[1] - 40.0, "z": TABLE_Z + 30.0}
    return poses


class SimArm(arm.PillArm):
    def __init__(self, world: World, theta_sign: float | None = None, slip: float = 0.0, seed: int = 0,
                 lite: bool = False, **kw):
        super().__init__(robot=None, **kw)
        self.lite = lite  # Lite gripper: no grip feedback, so holding() cannot tell
        self.world, self.slip, self.rng = world, slip, random.Random(seed)
        self.true_sign = arm.THETA_SIGN if theta_sign is None else theta_sign
        self.at = {"x": 0.0, "y": 0.0, "z": 300.0, "theta": 0.0}
        self.held = None
        self.slot_poses: dict = {}

    async def setup(self):
        self.log({"setup": "sim"})

    async def _hw_plan(self, target, straight):
        if target["z"] < TABLE_Z - 0.1:
            raise RuntimeError("sim: below the table")

    async def _hw_move(self, target, straight):
        self.at = dict(target)

    async def _hw_where(self):
        return dict(self.at)

    async def _hw_gripper(self, action):
        if action == "close":
            self.held = self._grab()
        elif action == "open" and self.held is not None:
            self._release()
        self.log({"gripper": action, "sim_held": self.held["type"] if self.held else None})

    def _grab(self):
        if self.at["z"] > TABLE_Z + 3.0:
            return None
        mx, my = self.at["x"] - T_MAT_TO_ROBOT[0], self.at["y"] - T_MAT_TO_ROBOT[1]
        near = min(self.world.pills, key=lambda p: np.hypot(p["x"] - mx, p["y"] - my), default=None)
        if near is None or np.hypot(near["x"] - mx, near["y"] - my) > GRIP_TOL_MM:
            return None
        L, W, *_ = TYPES[near["type"]]
        if L / W >= vision.ROUND_ASPECT:
            jaw = self.true_sign * self.at["theta"] + arm.JAW_AT_THETA0_DEG
            off = abs(((jaw - (near["a"] + 90.0)) + 90.0) % 180.0 - 90.0)
            if off > GRIP_TOL_DEG:
                return None
        if self.rng.random() < self.slip:
            return None
        self.world.pills.remove(near)
        return near

    def _release(self):
        for slot, p in self.slot_poses.items():
            if np.hypot(p["x"] - self.at["x"], p["y"] - self.at["y"]) <= SLOT_DROP_TOL_MM:
                self.world.slots.setdefault(slot, []).append(self.held["type"])
                break
        else:  # dropped somewhere else: back on the mat where it fell
            self.world.pills.append({**self.held, "x": self.at["x"] - T_MAT_TO_ROBOT[0],
                                     "y": self.at["y"] - T_MAT_TO_ROBOT[1]})
        self.held = None

    async def holding(self):
        return None if self.lite else self.held is not None

    async def photo(self):
        return self.world.render()

    async def stop(self):
        self.log({"stop": "sim"})


def enroll(cal: Calibration, n: int = 10, seed: int = 99) -> Registry:
    """Enroll each type from sim frames, the way capture + enroll would on the real camera."""
    types = []
    for kind in TYPES:
        w = World({}, seed)
        feats = []
        for i in range(n):
            p = w._place(kind)
            pill = vision.detect(w.render(only=[p]))[0]
            px = (pill.cx, pill.cy)
            sq = cal.px_to_mat([(px[0] - 5, px[1] - 5), (px[0] + 5, px[1] - 5), (px[0] + 5, px[1] + 5), (px[0] - 5, px[1] + 5)])
            feats.append(features(pill, float(cv2.contourArea(sq.astype(np.float32))) / 100.0))
        types.append(from_samples(kind, feats, "mm", camera="sim"))
    return Registry(types)


def build(args, inv):
    """(arm, calibration, poses, registry) for demo.live --sim."""
    cal = calibration()
    need: dict = {}
    for slot in inv.schedule.values():
        for kind, n in slot.items():
            need[kind] = need.get(kind, 0) + n
    world = World(need, seed=args.sim_seed)
    a = SimArm(world, theta_sign=args.sim_theta_sign, slip=args.sim_slip, seed=args.sim_seed, lite=args.sim_lite,
               table_z=cal.table_z, yaw_align=not args.no_yaw)
    poses = {"photo": dict(cal.photo_pose), "table_z": TABLE_Z, **slot_poses(inv.schedule)}
    a.slot_poses = {k: v for k, v in poses.items() if k in inv.schedule}
    return a, cal, poses, enroll(cal)
