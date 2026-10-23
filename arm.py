"""Arm wrapper for a top-down pill pick. Motion calls are stubs until the SO-101 port.

The pure parts (grip_theta, PillArm.check, the plan-before-move ordering, the pose log, the gripper
command) are tested offline by overriding the _hw_* methods. Each _hw_* method raises
NotImplementedError, so nothing can move before the port lands.

Usage (after the SO-101 port):
  python arm.py ping                connect only: list resources
  python arm.py where               print the TCP pose
  python arm.py teach NAME          save the TCP xyz as a named pose (photo, Mon-AM, ..., reject, touch-0)
  python arm.py plan X Y Z THETA    plan-only, never moves
  python arm.py jaw THETA           move to the photo pose with this theta, for the jaw photo

Secrets come from the environment only: VIAM_ADDRESS, VIAM_API_KEY_ID, VIAM_API_KEY.
"""
import asyncio
import json
import math
import os
import sys
import time
from pathlib import Path

from config import CAMERA, CAMERA_SOURCE, POSES

LOG_DIR = Path(__file__).parent / "logs"

# T4 measures these two. jaw line angle (robot frame, CCW from +x seen from above) =
# THETA_SIGN * theta + JAW_AT_THETA0_DEG. Until measured, every yaw is a guess.
THETA_SIGN = 1.0
JAW_AT_THETA0_DEG = 0.0
FIXED_THETA = 0.0          # wrist yaw when yaw alignment is off (T6 control) or the pill is round

HOVER_MM = 40.0            # above the mat; the wrist only rotates up here
GRASP_ABOVE_MAT_MM = 1.5   # fingertip height at close; pills are 3-5 mm tall
FLOOR_ABOVE_MAT_MM = 0.0   # refuse anything lower; put foam under the paper before lowering this
SLOT_HOVER_MM = 8.0        # open this far above the saved funnel mouth; higher drops bounce out (measure on site)
ACCURACY_MM = 2.0
STOP_TIMEOUT_S = 10.0

# The SO-101 gripper is set by percentage; grab() is never used. Placeholders until measured on the rig.
GRIPPER_OPEN_PCT = 100     # TODO(SO-101): unmeasured
GRIPPER_CLOSE_PCT = 0      # TODO(SO-101): unmeasured; the candy grip needs a measured value


class MoveRefused(RuntimeError):
    pass


def gripper_command(action: str) -> dict:
    """Viam do_command for the SO-101 gripper. Pure, so the command shape is testable offline."""
    pct = GRIPPER_OPEN_PCT if action == "open" else GRIPPER_CLOSE_PCT
    return {"command": "set_position", "percentage": pct}


def grip_theta(axis_deg: float | None, current_theta: float, sign: float = None, jaw0: float = None) -> float:
    """Wrist theta that closes the jaws across the pill's short axis.
    The jaw line must be perpendicular to the long axis; a parallel gripper is symmetric under
    180 deg, so always use the equivalent in [-90, 90). Choosing "nearest to the current theta"
    lets the commanded yaw drift pick after pick toward joint-6 limits and the wrap."""
    sign = THETA_SIGN if sign is None else sign
    jaw0 = JAW_AT_THETA0_DEG if jaw0 is None else jaw0
    if axis_deg is None:  # round pill: any angle grips, so don't rotate
        return current_theta
    base = sign * (axis_deg + 90.0 - jaw0)
    return (base + 90.0) % 180.0 - 90.0


def load_poses() -> dict:
    return json.loads(POSES.read_text()) if POSES.exists() else {}


class PillArm:
    def __init__(self, robot=None, table_z: float | None = None, limits: dict | None = None,
                 yaw_align: bool = True, log_path=None):
        self.robot = robot
        self.table_z = table_z
        self.limits = limits or {}           # {"x": [lo, hi], "y": [lo, hi], "z_max": v}
        self.yaw_align = yaw_align           # False = T6 negative control
        self.theta = FIXED_THETA             # last COMMANDED theta; read-back theta is unreliable at o=(0,0,-1)
        path = Path(log_path) if log_path else LOG_DIR / f"arm-{time.strftime('%Y%m%d-%H%M%S')}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        self.log_path = path

    def log(self, entry: dict):
        with self.log_path.open("a") as f:
            f.write(json.dumps(dict(entry, t=round(time.time(), 3))) + "\n")

    def check(self, target: dict) -> str | None:
        """Why this target is unsafe, or None. Runs before the planner sees it."""
        if (target["o_x"], target["o_y"], target["o_z"]) != (0.0, 0.0, -1.0):
            return "orientation must be straight down (0,0,-1)"
        if not all(math.isfinite(target[k]) for k in ("x", "y", "z", "theta")):
            return "non-finite target"
        if self.table_z is None:
            return "no table_z: run calibration first"
        floor = self.table_z + FLOOR_ABOVE_MAT_MM
        if target["z"] < floor:
            return f"z {target['z']:.1f} below floor {floor:.1f}"
        for ax in ("x", "y"):
            lo, hi = self.limits.get(ax, (-math.inf, math.inf))
            if not lo <= target[ax] <= hi:
                return f"{ax} {target[ax]:.0f} outside [{lo}, {hi}]"
        if target["z"] > self.limits.get("z_max", math.inf):
            return f"z {target['z']:.0f} above z_max"
        return None

    async def move(self, x: float, y: float, z: float, theta: float | None = None, label: str = "",
                   straight: bool = False) -> dict:
        """Check -> plan-only -> move -> read back. Every step is logged with the commanded theta."""
        theta = self.theta if theta is None else float(theta)
        target = {"x": float(x), "y": float(y), "z": float(z), "o_x": 0.0, "o_y": 0.0, "o_z": -1.0, "theta": theta}
        why = self.check(target)
        if why:
            self.log({"label": label, "target": target, "refused": why})
            raise MoveRefused(why)
        try:
            await self._hw_plan(target, straight)
        except Exception as e:  # noqa: BLE001 - any planner failure means do not move
            self.log({"label": label, "target": target, "refused": f"plan: {type(e).__name__}: {e}"[:300]})
            raise MoveRefused(f"plan failed: {e}") from e
        self.log({"label": label, "target": target, "phase": "planned", "straight": straight})
        await self._hw_move(target, straight)
        self.theta = theta
        reached = await self._hw_where()
        err = math.dist((x, y, z), (reached["x"], reached["y"], reached["z"]))
        self.log({"label": label, "target": target, "reached": reached, "err_mm": round(err, 2)})
        if err > ACCURACY_MM:
            print(f"warning: {label} off by {err:.1f} mm", file=sys.stderr)
        return reached

    async def pick(self, x: float, y: float, axis_yaw_deg: float | None, label: str = "pick") -> float:
        """Open -> hover (rotating in the air) -> straight descent -> close -> straight lift.
        Returns the theta used, so the caller can log yaw error against the detected axis."""
        theta = grip_theta(axis_yaw_deg, self.theta) if self.yaw_align else FIXED_THETA
        hover, grasp = self.table_z + HOVER_MM, self.table_z + GRASP_ABOVE_MAT_MM
        self.log({"label": label, "axis_yaw_deg": axis_yaw_deg, "theta": theta, "yaw_align": self.yaw_align})
        await self.gripper_open()
        await self.move(x, y, hover, theta, f"{label}/hover")
        await self.move(x, y, grasp, theta, f"{label}/descend", straight=True)
        await self.gripper_close()
        await self.move(x, y, hover, theta, f"{label}/lift", straight=True)
        return theta

    async def drop(self, slot: dict, label: str = "drop"):
        """Saved funnel pose: only xyz is trusted; keep the current theta so the wrist doesn't spin."""
        await self.move(slot["x"], slot["y"], slot["z"] + SLOT_HOVER_MM, None, f"{label}/over")
        await self.gripper_open()
        self.log({"label": label, "released": True})

    async def gripper_open(self):
        await self._hw_gripper("open")

    async def gripper_close(self):
        await self._hw_gripper("close")

    async def photo(self):
        """BGR frame from the camera. Only valid for calibration if taken at the saved photo pose."""
        from viam.components.camera import Camera
        from camera import decode_viam
        cam = Camera.from_robot(self.robot, CAMERA)
        imgs, _ = await (cam.get_images(filter_source_names=[CAMERA_SOURCE]) if CAMERA_SOURCE else cam.get_images())
        return decode_viam(imgs)

    async def holding(self) -> bool | None:
        """None: the SO-101 gripper reports no grip state yet, so the photo check decides.
        TODO(SO-101): return a bool if the gripper exposes one."""
        return None

    async def stop(self):
        """Every exit path: halt the arm, then open the jaws so no pill stays clamped.
        Each step on its own: one failing must not skip the rest."""
        for name, call in (("arm.stop", self._hw_stop), ("open", lambda: self._hw_gripper("open"))):
            try:
                await asyncio.wait_for(call(), STOP_TIMEOUT_S)
                self.log({"stop": name, "ok": True})
            except Exception as e:  # noqa: BLE001
                self.log({"stop": name, "ok": False, "error": f"{type(e).__name__}: {str(e)[:120]}"})

    # ── hardware boundary: stubs until the SO-101 port ─────────────────────────
    async def _hw_plan(self, target: dict, straight: bool):
        raise NotImplementedError("TODO(SO-101): plan-only call to the motion service")

    async def _hw_move(self, target: dict, straight: bool):
        raise NotImplementedError("TODO(SO-101): move call to the motion service")

    async def _hw_where(self) -> dict:
        raise NotImplementedError("TODO(SO-101): read the TCP pose")

    async def _hw_gripper(self, action: str):
        raise NotImplementedError(f"TODO(SO-101): send {gripper_command(action)} to the gripper")

    async def _hw_stop(self):
        raise NotImplementedError("TODO(SO-101): halt the arm")


async def connect():
    """HARDWARE-ONLY. The SDK is imported here so dry runs and tests never need it."""
    from viam.robot.client import RobotClient
    opts = RobotClient.Options.with_api_key(api_key=os.environ["VIAM_API_KEY"],
                                            api_key_id=os.environ["VIAM_API_KEY_ID"])
    return await RobotClient.at_address(os.environ["VIAM_ADDRESS"], opts)


async def _main(argv):
    t0 = time.time()
    try:
        robot = await asyncio.wait_for(connect(), 45)
    except asyncio.TimeoutError:
        raise SystemExit("connect timed out after 45 s: venue Wi-Fi may block WebRTC; try the phone hotspot")
    print(f"connected in {time.time() - t0:.1f} s")
    try:
        poses = load_poses()
        a = PillArm(robot, table_z=poses.get("table_z"), limits=poses.get("limits"))
        cmd = argv[0] if argv else "ping"
        if cmd == "ping":
            print("resources:", sorted(r.name for r in robot.resource_names))
        elif cmd == "where":
            print(await a._hw_where())
        elif cmd == "teach":
            if len(argv) < 2:
                raise SystemExit("usage: arm.py teach NAME   (photo, touch-0, Mon-AM, reject, ...)")
            p = await a._hw_where()
            poses[argv[1]] = {k: p[k] for k in ("x", "y", "z")}
            POSES.write_text(json.dumps(poses, indent=2))
            print("saved", argv[1], poses[argv[1]], "(theta not saved: read-back theta is unreliable pointing down)")
        elif cmd == "plan":
            x, y, z, th = map(float, argv[1:5])
            target = {"x": x, "y": y, "z": z, "o_x": 0.0, "o_y": 0.0, "o_z": -1.0, "theta": th}
            why = a.check(target)
            if why:
                print("refused:", why)
            else:
                await a._hw_plan(target, False)
                print("plan OK")
        elif cmd == "jaw":
            ph = poses["photo"]
            await a.move(ph["x"], ph["y"], ph["z"], float(argv[1]), f"jaw-test/{argv[1]}")
        else:
            print(__doc__)
    finally:
        await robot.close()


if __name__ == "__main__":
    asyncio.run(_main(sys.argv[1:]))
