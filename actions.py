"""Doseday robot actions: open or close a day's lid, place a pill in a day. Every move goes to a taught pose.

Poses live in taught_joints.json (joint degrees). Save one with `python armctl.py teach <name>` while teleop or
manual mode holds the arm there. Names (days: sun mon tue wed thu fri sat):
  home
  tray_hover, tray_down              the pick slot; the wrist camera at tray_hover sees the slot
  reject_hover                       above the reject cup
  tab_<day>_hover, tab_<day>_press   fingertip on the latch tab's black dot (opening is off unless allow_open)
  lid_<day>_hover, lid_<day>_press   on the open lid: pressing it shuts the lid
  drop_<day>_hover                   above the open compartment
An action whose poses are not taught yet refuses and names the missing pose.
"""
import asyncio
import json
import time
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).parent
POSES = HERE / "taught_joints.json"
DAYS = ("sun", "mon", "tue", "wed", "thu", "fri", "sat")
DAY_NAMES = dict(zip(DAYS, ("Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday")))

MOVE_SPEED = 50.0       # deg/s, the arm's configured default
PRESS_SPEED = 15.0      # slow fingertip; below 12 the servos stop honouring the speed (module docs)
DESCEND_SPEED = 30.0    # pick descent: below ~27 the coordinated straight-down move drifts (run 01 analysis)
PRESS_TORQUE = 350      # of 1000 while pressing: a stiff tab stalls the arm instead of snapping (near-snap 23 Oct)
FULL_TORQUE = 1000
PRESS_HOLD_S = 0.3
PRESS_TIMEOUT_S = 5.0   # a press that stalls against the tab never settles; lift anyway
OPEN_PCT, CLOSED_PCT, GRIP_SQUEEZE_PCT = 30.0, 0.0, 1.0
SETTLE_TOL, SETTLE_READS, SETTLE_POLL_S, SETTLE_TIMEOUT_S = 0.5, 3, 0.1, 6.0
# The wrist camera's frames trail the arm: after a move returns, frames kept changing for 1.0-1.9 s before matching the
# settled view (23 Oct, two 25-degree base turns). Any photo the station acts on waits this long after a move.
CAMERA_SETTLE_S = 2.0
# Grip check by where the closing jaw stopped. Empty closes end at 0.7-2.0% (23 Oct); a rigid pill stops the jaw
# higher (to confirm with a Tums on the arm). The wrist-camera hold score cannot judge white pills: the white
# jaws fill 35-92% of its gap region on empty frames (23 Oct), so it only ever worked for coloured candy.
JAW_HELD_MIN = 3.0


# move_to_joint_positions sometimes returns before the arm has started: on 23 Oct, 2 of 6 timed 15-degree returns came
# back in 0.03-0.08 s with the arm still 15 deg from target, then it arrived on its own. Trust the joints, not the call.
ARRIVE_TOL_DEG, ARRIVE_STEADY_READS, ARRIVE_POLL_S = 1.0, 3, 0.1


async def wait_arrival(arm, target, speed: float, timeout: float | None = None) -> bool:
    """Poll joint angles until every joint is within ARRIVE_TOL_DEG of target for ARRIVE_STEADY_READS reads in a row.
    False if that does not happen within the time the move should take, with margin."""
    now = list((await arm.get_joint_positions()).values)
    budget = timeout or max(abs(t - c) for t, c in zip(target, now)) / max(speed, 1.0) * 1.5 + 2.0
    t0, steady = time.monotonic(), 0
    while steady < ARRIVE_STEADY_READS:
        if time.monotonic() - t0 > budget:
            return False
        await asyncio.sleep(ARRIVE_POLL_S)
        now = list((await arm.get_joint_positions()).values)
        steady = steady + 1 if max(abs(t - c) for t, c in zip(target, now)) <= ARRIVE_TOL_DEG else 0
    return True


class Refused(Exception):
    """A reason the station says out loud instead of acting."""


def load_poses(path: Path = POSES) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}


def check_day(day: str) -> str:
    d = (day or "").strip().lower()[:3]
    if d not in DAYS:
        raise Refused(f"I don't know the day {day!r}")
    return d


def joint_positions(values):
    """HARDWARE-ONLY. Tests replace this so they never import the SDK."""
    from viam.proto.component.arm import JointPositions
    return JointPositions(values=values)


class Station:
    def __init__(self, arm, gripper, camera, poses: dict, limits, log_path: Path, identify=None,
                 open_pct: float = OPEN_PCT, unverified: bool = False, allow_open: bool = False,
                 poses_path: Path | None = None, read_limits=None, box_path: Path | None = None, detectors=()):
        self.arm, self.gripper, self.camera = arm, gripper, camera
        # A registered box (box.py mark/fit) replaces the taught lid poses with the planned flip stroke
        self.box_path, self.box, self.kin = box_path, None, None
        self.poses, self.limits, self.log_path = poses, limits, log_path
        self.poses_path, self.read_limits = poses_path, read_limits
        self.identify, self.open_pct, self.unverified = identify, open_pct, unverified
        # Opening by pressing the latch tab is off by default: it worked by teleop (run 03) but was judged too
        # forceful to risk in a demo (23 Oct). Lids start open; the arm only closes them.
        self.allow_open = allow_open
        self.lid = {d: "open" for d in DAYS}
        # what the page shows: the frame the last pill check judged, and its verdict
        self.last_frame, self.last_look = None, None
        # async img -> [{source, label, confidence, box}]: shown on the page, never consulted for a placement
        self.detectors = list(detectors)

    def log(self, entry: dict):
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a") as f:
            f.write(json.dumps({"t": round(time.time(), 3), **entry}) + "\n")

    def need(self, *names):
        missing = [n for n in names if n not in self.poses]
        if missing:
            raise Refused(f"position {missing[0]} is not taught yet")

    def clamp(self, joints) -> list[float]:
        return [min(max(v, lo + 0.5), hi - 0.5) for v, (lo, hi) in zip(joints, self.limits)]

    async def joints(self) -> list[float]:
        return [round(v, 2) for v in (await self.arm.get_joint_positions()).values]

    async def move(self, name: str, speed: float, timeout: float | None = None) -> bool:
        """False when the move timed out (stalled) instead of reaching its pose."""
        self.need(name)
        target = self.clamp(self.poses[name])
        await self.arm.do_command({"set_speed": speed})
        self.log({"move": name, "commanded": target, "speed": speed})
        try:
            mv = self.arm.move_to_joint_positions(joint_positions(target))
            await (asyncio.wait_for(mv, timeout) if timeout else mv)
        except asyncio.TimeoutError:
            self.log({"move": name, "stalled": True, "at": await self.joints()})
            return False
        except Exception as e:
            # a refused move can still have moved another joint, so log where the arm really is
            self.log({"move": name, "error": f"{type(e).__name__}: {str(e)[:160]}", "at": await self.joints()})
            raise
        if not await wait_arrival(self.arm, target, speed, timeout):
            self.log({"move": name, "not_arrived": True, "at": await self.joints()})
            if timeout:  # a capped press is expected to stop short against the lid
                return
            raise Refused(f"the arm did not reach {name}, so I stopped")
        self.log({"move": name, "at": await self.joints()})
        return True

    async def jaw(self) -> float:
        return float((await self.gripper.do_command({"command": "get_position"}))["position_percentage"])

    async def jaw_to(self, pct: float) -> float:
        """set_position returns before the jaw settles on this deployment, so poll until the reading stops."""
        await self.gripper.do_command({"command": "set_position", "percentage": pct})
        last, still, t0 = await self.jaw(), 0, time.monotonic()
        while still < SETTLE_READS and time.monotonic() - t0 < SETTLE_TIMEOUT_S:
            await asyncio.sleep(SETTLE_POLL_S)
            now = await self.jaw()
            still = still + 1 if abs(now - last) < SETTLE_TOL else 0
            last = now
        return last

    async def frame(self) -> np.ndarray:
        await asyncio.sleep(CAMERA_SETTLE_S)  # a frame taken sooner can still show the arm mid-move
        imgs, _ = await self.camera.get_images()
        img = cv2.imdecode(np.frombuffer(imgs[0].data, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise Refused("the camera frame did not decode")
        self.last_frame = imgs[0].data
        return img

    async def press(self, kind: str, day: str, after_down=None) -> bool:
        """Lower onto the press pose, hold, lift. Returns False when the press stalled short of the pose.
        after_down(pressed) runs once the arm is on the pose and before the lift."""
        hover, down = f"{kind}_{day}_hover", f"{kind}_{day}_press"
        self.need(hover, down)
        await self.move(hover, MOVE_SPEED)
        try:
            # inside the try: a capped write that fails after changing the register must still be restored
            await self.arm.do_command({"command": "set_torque_limit", "value": PRESS_TORQUE})
            pressed = await self.move(down, PRESS_SPEED, timeout=PRESS_TIMEOUT_S)
            if after_down is not None:
                after_down(pressed)
            await asyncio.sleep(PRESS_HOLD_S)
            await self.move(hover, PRESS_SPEED)
        finally:
            # the register does not reset by itself; a capped arm cannot carry or hold reliably
            await self.arm.do_command({"command": "set_torque_limit", "value": FULL_TORQUE})
        return pressed

    async def _latch(self, kind: str, d: str, done: str):
        """The lid stays 'unknown' from the first move. It becomes `done` only once the arm is on the press
        pose, so a lift cut short after that point still leaves it unknown; a stalled press is an error."""
        self.lid[d] = "unknown"

        def on_down(pressed: bool):
            if pressed:
                self.lid[d] = done

        try:
            pressed = await self.press(kind, d, after_down=on_down)
        except BaseException:
            self.lid[d] = "unknown"
            raise
        if not pressed:
            raise Refused(f"{DAY_NAMES[d]} did not reach the press point; check it by hand")

    async def open_lid(self, day: str) -> str:
        d = check_day(day)
        if not self.allow_open:
            raise Refused(f"I don't open lids; please open {DAY_NAMES[d]} by hand")
        self.need(f"tab_{d}_hover", f"tab_{d}_press")
        await self.jaw_to(CLOSED_PCT)  # closed jaw = fingertip
        await self._latch("tab", d, "open")
        return f"{DAY_NAMES[d]} is open"

    async def close_lid(self, day: str) -> str:
        d = check_day(day)
        if self.box is not None:
            return await self._stroke_close(d)
        self.need(f"lid_{d}_hover", f"lid_{d}_press")
        await self.jaw_to(CLOSED_PCT)
        await self._latch("lid", d, "closed")
        return f"{DAY_NAMES[d]} is closed"

    async def _stroke_close(self, d: str) -> str:
        """Swing the open lid shut from behind and press it (box.py). Same lid bookkeeping as a press: unknown
        from the first move, closed only once the press point was reached."""
        import box
        try:
            waypoints = box.plan(self.kin, self.box, d, await self.joints())
        except ValueError as e:
            raise Refused(f"I can't reach {DAY_NAMES[d]}'s lid from here ({e})") from e
        await self.jaw_to(CLOSED_PCT)
        self.lid[d] = "unknown"
        self.log({"stroke": d, "waypoints": [w["name"] for w in waypoints]})
        try:
            pressed = await box.run_stroke(self.arm, waypoints)
        except BaseException:
            self.lid[d] = "unknown"
            raise
        self.log({"stroke": d, "pressed": pressed, "at": await self.joints()})
        if not pressed:
            raise Refused(f"{DAY_NAMES[d]}'s lid did not reach the press point; check it by hand")
        self.lid[d] = "closed"
        return f"{DAY_NAMES[d]} is closed"

    async def detect(self, img) -> list[dict]:
        out = []
        for d in self.detectors:
            try:
                out += await d(img)
            except Exception as e:  # a detector that fails must not stop a placement it does not gate
                self.log({"detect_error": f"{type(e).__name__}: {str(e)[:160]}"})
        return out

    def _show(self, wanted: str, img, seen, detections):
        # default=str: identifiers return numpy numbers, and /status must stay JSON
        self.last_look = json.loads(json.dumps({"t": round(time.time(), 3), "wanted": wanted, "seen": seen,
                                                "detections": detections, "size": [img.shape[1], img.shape[0]]},
                                               default=str))

    async def look(self, wanted: str) -> str:
        """Label of the single pill in the tray slot, as seen from tray_hover."""
        if self.identify is None:
            if self.unverified:
                self.log({"look": "unverified", "assumed": wanted})
                if self.detectors:  # the page still shows what the detectors see
                    img = await self.frame()
                    self._show(wanted, img, None, await self.detect(img))
                return wanted
            raise Refused("no pill photos are enrolled, so I can't check which pill this is")
        img = await self.frame()
        # a blob cut off by the frame edge may be a second pill, so it counts toward the one-pill check
        seen = [r for r in self.identify(img) if r["label"] != "not_pill" or r.get("reason") == "edge"]
        self.log({"look": seen})
        self._show(wanted, img, seen, await self.detect(img))
        if not seen:
            raise Refused("the tray is empty")
        if len(seen) > 1:
            raise Refused(f"I see {len(seen)} pills on the tray; put one at a time")
        if seen[0].get("reason") == "edge":
            raise Refused("a pill is at the edge of the tray; move it in")
        return seen[0]["label"]

    async def grip(self) -> int:
        """Pick from tray_down; held when the pill stops the closing jaw. One retry. Returns the attempt that held."""
        for attempt in (1, 2):
            await self.move("tray_down", DESCEND_SPEED)
            stopped = await self.jaw_to(CLOSED_PCT)
            self.log({"grip": attempt, "jaw_stopped": round(stopped, 1)})
            if stopped >= JAW_HELD_MIN:
                # hold just inside where the pill stopped the jaw: a 0% goal against a pill stalls the servo
                await self.jaw_to(stopped - GRIP_SQUEEZE_PCT)
                await self.move("tray_hover", DESCEND_SPEED)
                return attempt
            await self.jaw_to(self.open_pct)
            await self.move("tray_hover", DESCEND_SPEED)
        raise Refused("I could not grip the pill after two tries")

    async def place(self, pill: str, day: str) -> str:
        d = check_day(day)
        pill = (pill or "").strip().lower()
        self.need("tray_hover", "tray_down", f"drop_{d}_hover")
        # a press whose restore failed leaves the register capped; a placement must not inherit that
        await self.arm.do_command({"command": "set_torque_limit", "value": FULL_TORQUE})
        await self.jaw_to(self.open_pct)
        await self.move("tray_hover", MOVE_SPEED)
        label = await self.look(pill)
        if label == "unknown":
            self.need("reject_hover")
            await self.grip()
            await self.move("reject_hover", MOVE_SPEED)
            await self.jaw_to(self.open_pct)
            await self.move("tray_hover", MOVE_SPEED)
            raise Refused("that pill is not one I know, so it went to the reject cup")
        if label != pill:
            raise Refused(f"that pill is {label}, not {pill}; I left it on the tray")
        if self.lid[d] == "unknown":
            raise Refused(f"{DAY_NAMES[d]} lid state is unknown; check it by hand, then press Close lid or Opened by hand")
        if self.lid[d] != "open":
            raise Refused(f"{DAY_NAMES[d]} is closed; open it by hand first")
        await self.jaw_to(self.open_pct)
        await self.move("tray_hover", MOVE_SPEED)
        await self.grip()
        await self.move(f"drop_{d}_hover", MOVE_SPEED)
        await self.jaw_to(self.open_pct)
        self.log({"placed": pill, "day": d})
        await self.move("tray_hover", MOVE_SPEED)
        return f"{pill} placed in {DAY_NAMES[d]}"

    def mark_open(self, day: str) -> str:
        d = check_day(day)
        self.lid[d] = "open"
        return f"{DAY_NAMES[d]} marked open"

    async def go_home(self) -> str:
        await self.move("home", MOVE_SPEED)
        return "home"

    async def halt(self):
        """STOP button: stop the arm, then put full torque back in case a press was cut off mid-way. Both steps
        are attempted even if the first raises; the first failure is re-raised so the page never reports a stop
        that did not happen."""
        failure = None
        try:
            await self.arm.stop()
        except Exception as e:
            failure = e
            self.log({"halt_error": "stop", "error": f"{type(e).__name__}: {str(e)[:160]}"})
        try:
            await self.arm.do_command({"command": "set_torque_limit", "value": FULL_TORQUE})
        except Exception as e:
            failure = failure or e
            self.log({"halt_error": "torque", "error": f"{type(e).__name__}: {str(e)[:160]}"})
        try:
            at = await self.joints()
        except Exception:
            at = None
        self.log({"halt": at})
        if failure is not None:
            raise failure

    async def refresh(self):
        """Taught poses and joint limits can change while the station runs (armctl teach; the shoulder floor
        moved on 23 Oct), so both are read again before each action."""
        if self.poses_path is not None:
            try:
                self.poses = load_poses(self.poses_path)
            except json.JSONDecodeError as e:
                raise Refused(f"the taught poses file is unreadable ({e.msg}); not moving") from e
        if self.read_limits is not None:
            self.limits = await self.read_limits()
        if self.box_path is not None:
            import box
            if self.box_path.exists():
                self.box, self.kin = box.Box.load(self.box_path), self.kin or box.Kinematics()
            else:
                self.box = None

    async def run(self, cmd: dict) -> dict:
        action = cmd.get("action")
        try:
            await self.refresh()
            if action == "open":
                say = await self.open_lid(cmd.get("day"))
            elif action == "close":
                say = await self.close_lid(cmd.get("day"))
            elif action == "place":
                say = await self.place(cmd.get("pill"), cmd.get("day"))
            elif action == "home":
                say = await self.go_home()
            elif action == "opened":  # a person opened the lid by hand
                say = self.mark_open(cmd.get("day"))
            else:
                raise Refused(f"I don't know how to {action!r}")
            return {"ok": True, "say": say}
        except Refused as r:
            self.log({"refused": str(r), "cmd": cmd})
            return {"ok": False, "say": str(r)}
