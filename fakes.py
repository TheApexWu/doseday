"""Fake arm, gripper and camera for tests and `python app.py --fake` rehearsals. No network, no SDK."""
import asyncio
from types import SimpleNamespace

import cv2
import numpy as np

from actions import DAYS

LIMITS = [(-110.0, 110.0), (-100.0, 100.0), (-96.8, 96.8), (-95.0, 95.0), (-157.2, 162.8)]


def poses() -> dict:
    """Every pose the actions use, with distinct joints so tests can tell moves apart. z follows joint 1."""
    names = ["home", "tray_hover", "tray_down", "reject_hover"]
    for d in DAYS:
        names += [f"tab_{d}_hover", f"tab_{d}_press", f"lid_{d}_hover", f"lid_{d}_press", f"drop_{d}_hover"]
    out = {n: [float(i), 0.0, 0.0, 0.0, 0.0] for i, n in enumerate(names)}
    return out


DEFAULT_TCP = (200.0, 0.0, 200.0)  # fingertip (x, y, z) at a pose the fake was not given a tcp for


class FakeArm:
    def __init__(self, move_s: float = 0.0, tcp: dict | None = None):
        self.at, self.moves, self.commands, self.stopped, self.move_s = [0.0] * 5, [], [], False, move_s
        self.fail_on = None  # joints list that raises when commanded
        self.tcp = tcp or {}  # joints tuple -> fingertip (x, y, z) at that taught pose
        self.end = DEFAULT_TCP  # what get_end_position reports: joint moves set it, move_to_position overwrites it
        self.cartesian, self.fail_cartesian = [], False  # xyz of each move_to_position; True makes it raise

    async def get_joint_positions(self):
        return SimpleNamespace(values=list(self.at))

    async def move_to_joint_positions(self, target):
        if self.fail_on is not None and list(target) == self.fail_on:
            raise RuntimeError("servo overload")
        self.moves.append(list(target))
        if self.move_s:
            await asyncio.sleep(self.move_s)
        self.at = list(target)
        self.end = self.tcp.get(tuple(target), DEFAULT_TCP)

    async def move_to_position(self, pose, **_):
        if self.fail_cartesian:
            raise RuntimeError("cartesian move refused")
        self.cartesian.append((pose.x, pose.y, pose.z))
        self.end = (pose.x, pose.y, pose.z)

    async def get_end_position(self):
        x, y, z = self.end
        return SimpleNamespace(x=x, y=y, z=z, o_x=0.0, o_y=0.0, o_z=-1.0, theta=0.0)

    async def do_command(self, cmd):
        self.commands.append(cmd)
        return {}

    async def stop(self):
        self.stopped = True


class FakeGripper:
    """A pill stops a closing jaw at stops_at (a list gives one value per close: 1.0 = closed on nothing)."""
    def __init__(self, stops_at=12.0):
        self.pos, self.sets, self.stops_at = 0.0, [], stops_at

    async def do_command(self, cmd):
        if cmd["command"] == "set_position":
            pct = cmd["percentage"]
            self.sets.append(pct)
            if pct > 0.0:
                self.pos = pct
            elif isinstance(self.stops_at, list):
                self.pos = self.stops_at.pop(0) if self.stops_at else 1.0
            else:
                self.pos = self.stops_at
            return {"success": True}
        return {"position_percentage": self.pos}


class FakeCamera:
    async def get_images(self):
        img = np.full((480, 640, 3), 90, np.uint8)  # the black mat photographs around V 0.35
        return [SimpleNamespace(data=cv2.imencode(".jpg", img)[1].tobytes())], None


def tray(label: str):
    """An identify stand-in that always sees one pill of `label` on the tray."""
    return lambda _img: [{"label": label, "cx": 320, "cy": 240}]
