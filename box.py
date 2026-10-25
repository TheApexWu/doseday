"""The pillbox as a frame. Every lid and compartment pose is computed from where the box sits, so a new table costs
one registration (two touched points) instead of re-teaching each pose by hand.

  python box.py mark mon        manual mode: rest the closed claw tip on Monday's lid, front edge, centred; run this
  python box.py mark fri        same on Friday (Sunday and Saturday stay untouched)
  python box.py fit             box.json from the two marks; refuses marks that disagree with the measured pitch
  python box.py today           box.json from the 23 Oct lid-closing demo (run 04) instead of marks
  python box.py poses           drop_<day>_hover joint poses for Mon-Fri into taught_joints.json
  python box.py show            the box, and each day's stroke as jaw-tip points
  python box.py stroke wed thu [--raise 25]   run strokes; --raise N runs them N mm clear of the box (dry run)

Geometry, measured 23 Oct:
- The arm's reported pose is the wrist-roll joint: Viam's SO-101 kinematics has no tool offset. The jaw grasp point
  is 98 mm further along the claw axis (gripper_frame in the SO-101 URDF). Forward kinematics from
  so101_kinematics.json reproduces the arm's own reported poses to a median 0.3 mm (run 04, 112 rows).
- Lid pitch 32.7 mm by tape measure. Lids hinge at the back; the latch is at the front, facing the arm.
- Lid-closing stroke: Alex's demonstrations, run 04 (popped lids, 86-117 s: start ~60 mm beyond the front edge
  and ~48 mm up leaning ~15 deg away from the base, rake toward the arm, finish on the front edge leaning ~5 deg
  back) and run 02 (open lids by teleop: strokes start near the upright lid's top edge).
"""
import asyncio
import json
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).parent
KINEMATICS = HERE / "so101_kinematics.json"  # arm.get_kinematics() from pi-arm1, 23 Oct
BOX_FILE = HERE / "box.json"
MARKS_FILE = HERE / "box_marks.json"

JAW_LEN = 98.0          # mm from the wrist-roll joint to the jaw grasp point, along the claw axis
PITCH = 30.6            # mm between lid centres in the arm frame: Alex's camera-centred lid pushes, 24 Oct (tape said 32.7; the error grew to 10 mm by Saturday)
DAYS = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"]
ROBOT_DAYS = DAYS  # all seven: on 24 Oct the end lids open and need closing too (day 1 had them taped down)
MARK_DAYS = ("mon", "fri")
MARK_TOL = 12.0         # mm: Mon-Fri marks must sit 4 pitches apart within this
LEVEL_TOL = 10.0        # mm: and at nearly the same height
# 24 Oct lid midpoints along the box (arm-frame y), where Alex centred the claw by eye on each lid in lid-teach-13;
# a straight-line fit put Sunday 8 mm off. Stored per box (Box.lid_y), never applied to a freshly registered box.
LID_Y_24OCT = {"sun": 67.0, "mon": 44.0, "tue": 13.0, "wed": -10.5, "thu": -45.0, "fri": -75.0, "sat": -110.0}
HEADING = -103.0        # wrist roll minus base yaw: Alex's lid-demo angle (24 Oct), jaws along the box, camera level (day 1 used 3)

# (behind the front edge, above the lid top, claw lean away from the base) in mm, mm, deg.
# Open lids stand near-upright on a hinge ~40 mm behind the front edge and are ~42 mm long (wrist-camera frames,
# 23 Oct, scaled by the 32.7 mm pitch). The stroke comes down behind the standing lid, swings it forward on a
# 32 mm arc around the hinge (inside the lid's length, so the tip stays on its face), then presses the front edge.
# A popped lid (front raised ~15 deg, run 04) meets the same arc near its end and gets pressed shut.
STROKE = [
    # Alex's hand on Mon/Tue, lid-teach-1608 (24 Oct): arrive vertical behind the lid, catch it low, drag it to the
    # front edge with the claw trailing toward the arm. (behind front edge, above closed lid top, lean; - = trailing)
    ("pre", 20.0, 78.0, 28.0),     # transit: high in front of the box (tilted as on day 1; vertical here breaks the wrist limit)
    ("hover", 45.0, 14.0, 0.0),    # hand arrived at x 240-249, z 38-42, claw vertical
    ("catch", 42.0, -1.0, -4.0),   # x 240-243, z 25-28, trailing 4-6
    ("arc1", 25.0, -11.0, -10.0),  # x 225, z 17
    ("arc2", 16.0, -13.0, -12.0),  # x 216, z 15
    ("arc3", 12.0, -11.0, -13.0),  # x 212, z 17 (the hand went to 205; the deep vertical push needs x >= ~208 mid-box)
    ("press", 14.0, -11.0, -12.0), # x 214, z 17: hand held at 216; the deep vertical push follows from here
]
LIFT = ("lift", 14.0, 50.0, 12.0)  # leaned like the demo: a vertical claw this high needs the wrist past 95 deg
STROKE_TORQUE = 600   # of 1000: 350 sagged 2-6 mm at this reach (try 1, 23 Oct) and could not swing the lid
STROKE_SPEED = 25.0   # deg/s, the whole stroke is one continuous trajectory: no stops in front of an audience
DROP = ("drop_hover", 22.0, 30.0, 5.0)  # over the compartment centre, lid open behind it


# ---- kinematics ---------------------------------------------------------------------------------------------

def _euler(r, p, y):
    cr, sr, cp, sp, cy, sy = np.cos(r), np.sin(r), np.cos(p), np.sin(p), np.cos(y), np.sin(y)
    return (np.array([[cy, -sy, 0], [sy, cy, 0], [0, 0, 1]]) @ np.array([[cp, 0, sp], [0, 1, 0], [-sp, 0, cp]])
            @ np.array([[1, 0, 0], [0, cr, -sr], [0, sr, cr]]))


class Kinematics:
    ORDER = ["base", "1", "shoulder", "2", "upper_arm", "3", "lower_arm", "4", "wrist", "5", "tool"]

    def __init__(self, path: Path = KINEMATICS):
        k = json.loads(path.read_text())
        self.links = {l["id"]: self._link(l) for l in k["links"]}
        self.axes = {j["id"]: np.array([j["axis"]["x"], j["axis"]["y"], j["axis"]["z"]], float) for j in k["joints"]}
        self.limits = [(j["min"], j["max"]) for j in k["joints"]]

    @staticmethod
    def _link(l):
        m = np.eye(4)
        t = l.get("translation", {})
        m[:3, 3] = [t.get("x", 0.0), t.get("y", 0.0), t.get("z", 0.0)]
        o = l.get("orientation", {}).get("value", {})
        m[:3, :3] = _euler(o.get("roll", 0.0), o.get("pitch", 0.0), o.get("yaw", 0.0))
        return m

    @staticmethod
    def _rot(axis, deg):
        a = axis / np.linalg.norm(axis)
        k = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
        th = np.radians(deg)
        m = np.eye(4)
        m[:3, :3] = np.eye(3) + np.sin(th) * k + (1 - np.cos(th)) * k @ k
        return m

    def wrist(self, q) -> np.ndarray:
        """4x4 pose of the tool frame (the arm's reported pose): position in mm, column 2 = claw axis."""
        m, qi = np.eye(4), iter(q)
        for n in self.ORDER:
            m = m @ (self.links[n] if n in self.links else self._rot(self.axes[n], next(qi)))
        return m

    def tip(self, q):
        """Jaw grasp point and claw axis (unit, pointing out of the jaws)."""
        m = self.wrist(q)
        return m[:3, 3] + JAW_LEN * m[:3, 2], m[:3, 2]

    def pan_axis(self) -> np.ndarray:
        return self.links["base"][:3, 3]

    def approach(self, tip, lean_deg) -> np.ndarray:
        """Claw axis pointing down, leaned lean_deg away from the base (negative: back toward it)."""
        r = np.asarray(tip[:2], float) - self.pan_axis()[:2]
        r /= np.linalg.norm(r)
        s, c = np.sin(np.radians(lean_deg)), np.cos(np.radians(lean_deg))
        return np.array([s * r[0], s * r[1], -c])

    def ik(self, tip, lean_deg, seed, heading=HEADING, iters=200):
        """Joints putting the jaw grasp point at `tip` with the given lean; wrist roll holds `heading`.
        Damped least squares from `seed`. Raises ValueError when the pose is out of reach or past a limit."""
        want_tip, want_axis = np.asarray(tip, float), self.approach(tip, lean_deg)
        q = np.array(seed, float)

        def resid(q):
            p, a = self.tip(q)
            return np.concatenate([p - want_tip, 100.0 * (a - want_axis)])  # 1 unit of axis ~ 100 mm

        for _ in range(iters):
            q[4] = q[0] + heading
            r = resid(q)
            if np.linalg.norm(r[:3]) < 0.2 and np.linalg.norm(r[3:]) < 0.5:
                break
            jac = np.zeros((6, 4))
            for i in range(4):
                dq = q.copy()
                dq[i] += 1e-3
                dq[4] = dq[0] + heading
                jac[:, i] = (resid(dq) - r) / 1e-3
            step = np.linalg.solve(jac.T @ jac + 1e-2 * np.eye(4), -jac.T @ r)
            q[:4] += np.clip(step, -5.0, 5.0)
        q[4] = q[0] + heading
        p, a = self.tip(q)
        miss = float(np.linalg.norm(p - want_tip))
        lean_miss = float(np.degrees(np.arccos(np.clip(a @ want_axis, -1, 1))))
        if miss > 1.5 or lean_miss > 2.0:
            raise ValueError(f"cannot reach tip {np.round(want_tip, 1).tolist()} leaning {lean_deg} deg "
                             f"(off by {miss:.1f} mm, {lean_miss:.1f} deg)")
        for v, (lo, hi), n in zip(q, self.limits, range(5)):
            if not lo + 0.5 <= v <= hi - 0.5:
                raise ValueError(f"joint {n} would be at {v:.1f} deg, outside its limits {lo:.0f}..{hi:.0f}")
        return [round(float(v), 2) for v in q]


# ---- the box ------------------------------------------------------------------------------------------------

@dataclass
class Box:
    mon: list          # jaw-tip point on Monday's lid: front edge, centred, on the lid top
    along: list        # unit, horizontal, Sunday -> Saturday
    source: str = ""
    lid_y: dict = None  # optional measured midpoint per day (arm-frame y), overriding the pitch

    @property
    def away(self) -> np.ndarray:
        """Unit, horizontal, from the front edge toward the hinge (away from the arm)."""
        a = np.asarray(self.along, float)
        n = np.array([-a[1], a[0], 0.0])
        return n if n[:2] @ np.asarray(self.mon[:2], float) > 0 else -n  # the box sits in front of the base

    def point(self, day: str, behind: float, above: float) -> np.ndarray:
        k = DAYS.index(day) - DAYS.index("mon")
        p = np.asarray(self.mon, float) + k * PITCH * np.asarray(self.along, float) + behind * self.away + [0, 0, above]
        if self.lid_y and day in self.lid_y:
            p[1] = self.lid_y[day]
        return p

    @classmethod
    def from_marks(cls, mon, fri, source="marks"):
        mon, fri = np.asarray(mon, float), np.asarray(fri, float)
        d = fri - mon
        span = float(np.linalg.norm(d[:2]))
        if abs(span - 4 * PITCH) > MARK_TOL:
            raise ValueError(f"Monday and Friday marks are {span:.0f} mm apart; 4 lids should be {4 * PITCH:.0f} mm. "
                             "Re-mark: tip on each lid's front edge, centred")
        if abs(d[2]) > LEVEL_TOL:
            raise ValueError(f"the marks differ by {d[2]:.0f} mm in height; is the box level and the claw on the lid top?")
        along = np.append(d[:2] / span, 0.0)
        mid = (mon + fri) / 2  # average the two marks along the box, keep each lid's own spacing
        mon_fit = mid - 2 * PITCH * along
        mon_fit[2] = (mon[2] + fri[2]) / 2
        return cls(mon=[round(float(v), 1) for v in mon_fit], along=[round(float(v), 4) for v in along], source=source)

    def save(self, path: Path = BOX_FILE):
        path.write_text(json.dumps(asdict(self), indent=1) + "\n")

    @classmethod
    def load(cls, path: Path = BOX_FILE):
        return cls(**json.loads(path.read_text()))


def plan(kin: Kinematics, box: Box, day: str, seed, steps=STROKE, raise_mm: float = 0.0):
    """Joint waypoints for one lid stroke (and the lift), seeded from `seed` so the arm takes the nearest solution.
    raise_mm lifts the whole stroke for a dry run with no contact."""
    if day not in ROBOT_DAYS:
        raise ValueError(f"{day} is taped down; the robot does not touch Sunday or Saturday")
    out, q = [], list(seed)
    for name, behind, above, lean in [*steps, LIFT]:
        tip = box.point(day, behind, above + raise_mm)
        q = kin.ik(tip, lean, q)
        out.append({"name": name, "tip": [round(float(v), 1) for v in tip], "lean": lean, "joints": q})
    return out


def demo_box() -> Box:
    """Box from Alex's run-04 demonstration. The press bottoms fit a front edge x = 243.3 -0.109*y (jaw tip, mm):
    the box sat 6.2 deg off square. Treating it as square left the Thu/Fri presses 3-6 mm in front of the
    lid edge and those lids sprang back open (23 Oct). Lid centres from the 32.7 mm pitch, Wednesday at y 0."""
    return Box(mon=[236.2, 65.0, 28.0], along=[0.1086, -0.9941, 0.0], source="run 04 demo fit, 6 deg skew, 23 Oct")


def densify(points, max_step: float = 2.0) -> list:
    """Joint-space points no more than max_step degrees apart: the arm blends through sparse waypoints and cut
    10-15 mm corners off the stroke (try 2, 23 Oct); dense points leave it nothing to cut."""
    out = [list(points[0])]
    for a, b in zip(points, points[1:]):
        n = max(1, int(np.ceil(max(abs(np.subtract(b, a))) / max_step)))
        out += [[round(float(v), 2) for v in np.add(a, np.subtract(b, a) * k / n)] for k in range(1, n + 1)]
    return out


async def run_stroke(arm, waypoints, torque: int = STROKE_TORQUE, speed: float = STROKE_SPEED, timeout: float = 25.0):
    """Everything up to the press is one continuous dense trajectory, which ends on the press (a call's endpoint is
    always reached); hold, then lift. Torque capped throughout and always restored. True when the press was reached."""
    from viam.proto.component.arm import JointPositions, MoveOptions
    from actions import FULL_TORQUE, PRESS_HOLD_S, wait_arrival

    names = [w["name"] for w in waypoints]
    k = names.index("press")
    path = densify([w["joints"] for w in waypoints[:k + 1]])
    await arm.do_command({"command": "set_torque_limit", "value": torque})
    try:
        await asyncio.wait_for(arm.move_through_joint_positions([JointPositions(values=q) for q in path],
                                                                options=MoveOptions(max_vel_degs_per_sec=speed)), timeout)
        pressed = await wait_arrival(arm, path[-1], speed, timeout=2.0)
        await asyncio.sleep(PRESS_HOLD_S)
        lift = waypoints[k + 1]["joints"]
        await arm.move_through_joint_positions([JointPositions(values=lift)], options=MoveOptions(max_vel_degs_per_sec=speed))
        await wait_arrival(arm, lift, speed)
        return pressed
    except asyncio.TimeoutError:
        await arm.stop()
        return False
    finally:
        await arm.do_command({"command": "set_torque_limit", "value": FULL_TORQUE})


MOVE_SPEED = 30.0


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "today":
        demo_box().save()
        print(json.dumps(asdict(demo_box())))
    elif cmd == "mark":
        # python box.py mark mon|fri   reads where the claw tip is now (put it there by hand in manual mode)
        from viam.components.arm import Arm
        from armctl import connect
        day = sys.argv[2] if len(sys.argv) > 2 else ""
        if day not in MARK_DAYS:
            sys.exit(f"mark one of {MARK_DAYS}: rest the closed claw tip on that lid's front edge, centred, then run this")

        async def read_tip():
            robot = await connect()
            try:
                q = [float(v) for v in (await Arm.from_robot(robot, "follower-arm").get_joint_positions()).values]
            finally:
                await robot.close()
            return Kinematics().tip(q)[0]
        tip = asyncio.run(read_tip())
        marks = json.loads(MARKS_FILE.read_text()) if MARKS_FILE.exists() else {}
        marks[day] = [round(float(v), 1) for v in tip]
        MARKS_FILE.write_text(json.dumps(marks, indent=1) + "\n")
        print(f"{day}: jaw tip at {marks[day]}  (marks so far: {sorted(marks)})")
    elif cmd == "fit":
        m = json.loads(MARKS_FILE.read_text())
        b = Box.from_marks(m["mon"], m["fri"])
        b.save()
        print(json.dumps(asdict(b)))
    elif cmd == "poses":
        # drop_<day>_hover for Mon-Fri into taught_joints.json, computed from box.json (the station's place() uses them)
        from actions import POSES, load_poses
        kin, b, poses = Kinematics(), Box.load(), load_poses()
        for d in ROBOT_DAYS:
            seed = plan(kin, b, d, [0.0, 15.0, -10.0, 80.0, HEADING])[-1]["joints"]
            name, behind, above, lean = DROP
            poses[f"drop_{d}_hover"] = kin.ik(b.point(d, behind, above), lean, seed)
            print(f"drop_{d}_hover", poses[f"drop_{d}_hover"], "tip", [round(float(v)) for v in b.point(d, behind, above)])
        POSES.write_text(json.dumps(poses, indent=1, sort_keys=True))
    elif cmd == "show":
        kin, b = Kinematics(), Box.load()
        print(json.dumps(asdict(b)))
        seed = [0.0, 15.0, -10.0, 80.0, -87.0]
        for d in ROBOT_DAYS:
            for w in plan(kin, b, d, seed):
                print(d, w["name"], w["tip"], w["lean"], w["joints"])
    elif cmd == "stroke":
        # python box.py stroke wed [--raise 25]   one or more days; --raise lifts the whole stroke clear of the box
        import asyncio
        from viam.components.arm import Arm
        from armctl import connect
        args = sys.argv[2:]
        lift = float(args[args.index("--raise") + 1]) if "--raise" in args else 0.0
        days = [a for a in args if a in DAYS]
        kin, b = Kinematics(), Box.load()

        async def main():
            robot = await connect()
            try:
                arm = Arm.from_robot(robot, "follower-arm")
                q = [round(v, 2) for v in (await arm.get_joint_positions()).values]
                for d in days:
                    wps = plan(kin, b, d, q, raise_mm=lift)
                    ok = await run_stroke(arm, wps)
                    at = [round(v, 2) for v in (await arm.get_joint_positions()).values]
                    print(d, "finished" if ok else "DID NOT FINISH", "tip", [round(float(v)) for v in kin.tip(at)[0]])
                    q = wps[-1]["joints"]
            finally:
                await robot.close()
        asyncio.run(main())
    else:
        sys.exit(__doc__)
