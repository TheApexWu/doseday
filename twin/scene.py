"""The Doseday table as a MuJoCo scene: the vendor SO-101 (checked against the arm in validate.py), the 7-day box
placed from box.py's frame with hinged lids, the black paper, and Tums on the far mat.

Measured: the lid front edge, the 32.7 mm pitch, the 6.2 deg skew and the 28 mm lid top (the arm's own presses).
Estimated from the pack-up photos and the stroke fit, about +-3 mm: everything behind the front edge (wall depth,
hinge line, lid length) and the Tums size.

    from twin.scene import Twin;  t = Twin()        # writes twin/vendor/SO101/doseday_*.xml and loads it
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import mujoco
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import box  # noqa: E402

VENDOR = ROOT / "twin" / "vendor" / "SO101"
ARM_SRC = VENDOR / "so101_new_calib_camera.xml"
# Written next to the vendor file so its mesh paths resolve; one pair per process so parallel runs can't
# load each other's geometry.
ARM_XML = VENDOR / f"doseday_arm_{os.getpid()}.xml"
SCENE_XML = VENDOR / f"doseday_scene_{os.getpid()}.xml"
ARM_JOINTS = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll"]

# Box, mm. Behind = beyond the lid's front edge, away from the arm.
LID_TOP = 28.0             # closed lid top, base frame z (run-04 fit)
LID_T = 3.0
CELL_W = 29.0              # pitch 32.7 leaves a 3.7 mm gap between compartments
CELL_FRONT = 1.0           # front wall, behind the lid's free edge
WALL = 1.5
HINGE = 25.0               # hinge line, box frame: fit to run 05's 14 recorded strokes (13/14 agree), replay.py
FRONT = -10.0              # lid free edge, box frame: the photos show ~35 mm lids; 13/14 strokes fit at -12
OPEN_DEG = 88.0            # an open lid rests on its stop, about upright: fit with HINGE (85-92 all fit)
TUMS_D, TUMS_H, TUMS_KG = 19.0, 7.0, 0.002
TABLE_Z = -2.4             # the base mesh bottoms out 2.4 mm below the base frame origin

# Jaw fingers, gripper frame mm, from the vendor meshes (inner faces at x = -7.9 and, jaw at 0 rad, +7.9).
FIXED_FINGER = ((-14.0, -7.9), (-6.0, 6.0), (-104.4, -80.0))
MOVING_FINGER_AT_ZERO = ((7.9, 14.0), (-6.0, 6.0), (-105.4, -80.0))
# Viam's jaw percentage, fit to the jaw readings: empty close ~0.5 %, Tums held ~8-11 %
JAW_LO, JAW_SPAN = -0.17453, 1.91986
LENS_OUT = 0.021           # m from the camera module's centre to just past its lens face
PROBE_MARGIN = 0.03        # m: clearances are reported for anything closer than this

DAY_RGBA = {"sun": "0.95 0.45 0.55 0.8", "mon": "1 0.62 0.2 0.8", "tue": "1 0.88 0.2 0.8",
            "wed": "0.55 0.88 0.25 0.8", "thu": "0.35 0.55 1 0.8", "fri": "0.25 0.85 0.8 0.8",
            "sat": "0.7 0.5 0.95 0.8"}
PILL, SCENERY = 'contype="2" conaffinity="2"', 'contype="3" conaffinity="3"'  # pills touch fingers, not jaw hulls


def jaw_angle(pct: float) -> float:
    return JAW_LO + JAW_SPAN * pct / 100.0


def _box_geom(name, lo_hi, rgba, extra=""):
    (x0, x1), (y0, y1), (z0, z1) = lo_hi
    c = [(x0 + x1) / 2000, (y0 + y1) / 2000, (z0 + z1) / 2000]
    h = [(x1 - x0) / 2000, (y1 - y0) / 2000, (z1 - z0) / 2000]
    return (f'<geom name="{name}" type="box" pos="{c[0]:.5f} {c[1]:.5f} {c[2]:.5f}" '
            f'size="{h[0]:.5f} {h[1]:.5f} {h[2]:.5f}" rgba="{rgba}" {extra}/>')


def _look_at(pos, target, up=(0, 0, 1)):
    f = np.subtract(target, pos, dtype=float)
    f /= np.linalg.norm(f)
    r = np.cross(f, up)
    r /= np.linalg.norm(r)
    u = np.cross(r, f)
    return " ".join(f"{v:.4f}" for v in (*r, *u))


def _moving_finger_in_jaw_frame() -> tuple:
    """The moving finger's box, measured in the gripper frame with the jaw at 0 rad, re-expressed in the jaw's frame."""
    m = mujoco.MjModel.from_xml_path(str(ARM_SRC))
    d = mujoco.MjData(m)
    mujoco.mj_kinematics(m, d)
    g, j = m.body("gripper").id, m.body("moving_jaw_so101_v1").id
    rg, rj = d.xmat[g].reshape(3, 3), d.xmat[j].reshape(3, 3)
    corners = np.array([[x, y, z] for x in MOVING_FINGER_AT_ZERO[0] for y in MOVING_FINGER_AT_ZERO[1]
                        for z in MOVING_FINGER_AT_ZERO[2]]) / 1000
    world = corners @ rg.T + d.xpos[g]
    local = (world - d.xpos[j]) @ rj * 1000
    return tuple(zip(local.min(0), local.max(0)))


def _wrist_camera(m: mujoco.MjModel) -> tuple[str, str]:
    """Pose of a camera in the wrist_camera body: at the module's centre, looking past the jaw tips with the jaws at
    the bottom of the image, as in the real frames (runs/*/frames)."""
    d = mujoco.MjData(m)
    mujoco.mj_kinematics(m, d)
    g, c = m.body("gripper").id, m.body("wrist_camera").id
    rg, rc = d.xmat[g].reshape(3, 3), d.xmat[c].reshape(3, 3)
    centre = rc @ np.array([0.0, 0.0001, 0.0158]) + d.xpos[c]   # module centroid
    target = rg @ np.array([0.0, 0.0, -0.125]) + d.xpos[g]       # a little past the jaw tips
    f = (target - centre) / np.linalg.norm(target - centre)
    eye = centre + LENS_OUT * f                                   # in front of the module, not inside it
    up = rg @ np.array([0.0, 0.0, -1.0])                         # tips toward the top, wrist toward the bottom
    up = up - (up @ f) * f
    xyaxes = _look_at(eye, target, up / np.linalg.norm(up))
    r, u = np.array(xyaxes.split()[:3], float), np.array(xyaxes.split()[3:], float)
    eye_local = rc.T @ (eye - d.xpos[c])
    return " ".join(f"{v:.5f}" for v in eye_local), " ".join(f"{v:.4f}" for v in (*(rc.T @ r), *(rc.T @ u)))


DISTAL = {"lower_arm", "wrist", "gripper", "wrist_camera_mount", "wrist_camera", "moving_jaw_so101_v1"}
COACD = VENDOR / "assets" / "coacd" / "manifest.json"


def _split_distal(src: str) -> str:
    """Swap each distal collision hull for its CoACD pieces (twin/decompose.py); the shoulder and upper arm keep
    their hulls, which never come near the box."""
    if not COACD.exists():
        raise SystemExit("run twin/decompose.py first: the hulls alone put the claw on top of open lids")
    pieces = json.loads(COACD.read_text())
    scale = dict(re.findall(r'<mesh file="([^"]+)\.stl"(?: scale="([^"]+)")?', src))
    out, stack, used = [], [], set()
    for line in src.splitlines():
        m = re.search(r'<body name="([^"]+)"', line)
        if m:
            stack.append(m.group(1))
        g = re.match(r'(\s*<geom type="mesh" class="collision"[^>]*?)mesh="([^"]+)"([^>]*/>)', line)
        if g and stack and stack[-1] in DISTAL and g.group(2) in pieces:
            for i in range(len(pieces[g.group(2)])):
                out.append(f'{g.group(1)}mesh="{g.group(2)}_c{i}"{g.group(3)}')
            used.add(g.group(2))
        else:
            out.append(line)
        if "</body>" in line:
            stack.pop()
    assets = "".join(
        f'<mesh name="{n}_c{i}" file="coacd/{f}"' + (f' scale="{scale[n]}"' if scale.get(n) else "") + "/>\n"
        for n in sorted(used) for i, f in enumerate(pieces[n]))
    return "\n".join(out).replace("</asset>", assets + "</asset>", 1)


def write_arm(wrist_fovy: float = 52.0, margin: float = 0.0) -> Path:
    src = _split_distal(ARM_SRC.read_text())
    src = src.replace('rgba="1 0.82 0.12 1"', 'rgba="0.93 0.93 0.91 1"')  # the follower is printed white
    # The arm's hulls touch the table, box and lids, never each other: they overlap at the joints (the vendor's
    # model pushes its own wrist off target otherwise). Clearances come from a separate probe copy (Twin.probe):
    # a contact margin on the physics model changed 10 of 14 replayed strokes.
    src = re.sub(r'(<default class="collision">\s*<geom group="3")',
                 rf'\1 contype="1" conaffinity="0" margin="{margin}" gap="{margin}"', src, count=1)
    m = mujoco.MjModel.from_xml_path(str(ARM_SRC))
    cam_pos, cam_xy = _wrist_camera(m)
    cam = f'<camera name="wrist" pos="{cam_pos}" xyaxes="{cam_xy}" fovy="{wrist_fovy}"/>'
    src = re.sub(r'(<body name="wrist_camera"[^>]*>)', r"\1\n" + cam, src, count=1)
    fixed = _box_geom("finger_fixed", FIXED_FINGER, "0.93 0.93 0.91 0", f'group="3" {PILL}')
    src = src.replace('<!-- Frame gripperframe -->', fixed + '\n<!-- Frame gripperframe -->', 1)
    moving = _box_geom("finger_moving", _moving_finger_in_jaw_frame(), "0.93 0.93 0.91 0", f'group="3" {PILL}')
    src = re.sub(r'(<body name="moving_jaw_so101_v1"[^>]*>)', r"\1\n" + moving, src, count=1)
    ARM_XML.write_text(src)
    return ARM_XML


def _cell(b: box.Box, day: str, lid_open: bool | None, hinge: float = HINGE, front: float = 0.0) -> str:
    """One compartment, its frame at the lid's front-edge centre on the table: x behind, y toward Sunday, z up."""
    p = b.point(day, 0.0, 0.0)
    yaw = np.degrees(np.arctan2(b.away[1], b.away[0]))
    rim = LID_TOP - LID_T - TABLE_Z
    hw = CELL_W / 2
    back = hinge  # the back wall sits under the hinge line
    f0 = front + CELL_FRONT  # front: where the lid's free edge sits in the box frame (0 = the registered edge)
    walls = [
        _box_geom(f"{day}_floor", ((f0, back), (-hw, hw), (0, WALL)), "0.96 0.96 0.97 1", SCENERY),
        _box_geom(f"{day}_front", ((f0, f0 + WALL), (-hw, hw), (0, rim)), "0.96 0.96 0.97 1", SCENERY),
        _box_geom(f"{day}_back", ((back - WALL, back), (-hw, hw), (0, rim)), "0.96 0.96 0.97 1", SCENERY),
        _box_geom(f"{day}_left", ((f0, back), (hw - WALL, hw), (0, rim)), "0.96 0.96 0.97 1", SCENERY),
        _box_geom(f"{day}_right", ((f0, back), (-hw, -hw + WALL), (0, rim)), "0.96 0.96 0.97 1", SCENERY),
        _box_geom(f"{day}_tab", ((front - 1.5, f0), (-5, 5), (rim - 9, rim - 2)), "0.15 0.15 0.15 1", SCENERY),
    ]
    lid_geoms = [  # in the lid frame: origin on the hinge line, closed lid toward -x
        _box_geom(f"{day}_lid", ((front - hinge, 0), (-hw - 0.5, hw + 0.5), (0, LID_T)), DAY_RGBA[day], SCENERY),
        _box_geom(f"{day}_lip", ((front - hinge - 0.8, front - hinge + 0.2), (-6, 6), (-3, LID_T)), DAY_RGBA[day], SCENERY),
    ]
    if lid_open is None:  # Sunday and Saturday: taped shut, no hinge
        lid = f'<body name="{day}_lidbody" pos="{hinge / 1000:.4f} 0 {rim / 1000:.4f}">{"".join(lid_geoms)}</body>'
    else:
        lid = (f'<body name="{day}_lidbody" pos="{hinge / 1000:.4f} 0 {rim / 1000:.4f}">'
               f'<joint name="{day}_hinge" type="hinge" axis="0 1 0" range="0 {np.radians(OPEN_DEG):.4f}" '
               f'damping="0.0004" frictionloss="0.0015" armature="0.00001"/>'
               f'<inertial pos="{(front - hinge) / 2000:.4f} 0 0.0015" mass="0.003" diaginertia="4e-7 4e-7 6e-7"/>'
               f'{"".join(lid_geoms)}</body>')
    return (f'<body name="{day}_cell" pos="{p[0] / 1000:.5f} {p[1] / 1000:.5f} {TABLE_Z / 1000:.5f}" '
            f'euler="0 0 {yaw:.4f}">{"".join(walls)}{lid}</body>')


def write_scene(b: box.Box | None = None, tums=((346.3, -108.1),), wrist_fovy: float = 52.0,
                hinge: float = HINGE, front: float = FRONT, margin: float = 0.0) -> Path:
    b = b or box.demo_box()
    write_arm(wrist_fovy, margin)
    cells = "".join(_cell(b, d, None if d not in box.ROBOT_DAYS else True, hinge, front) for d in box.DAYS)
    pills = "".join(
        f'<body name="tums{i}" pos="{x / 1000:.4f} {y / 1000:.4f} {(TABLE_Z + 0.3 + TUMS_H / 2) / 1000:.4f}">'
        f'<freejoint name="tums{i}_free"/><geom name="tums{i}" type="cylinder" size="{TUMS_D / 2000:.4f} '
        f'{TUMS_H / 2000:.4f}" mass="{TUMS_KG}" rgba="0.98 0.86 0.76 1" friction="0.8 0.01 0.001" '
        f'condim="4" solref="0.004 1" solimp="0.95 0.99 0.001 0.5 2" solmix="1000" {PILL}/></body>'
        for i, (x, y) in enumerate(tums))  # stiff: with default soft contact the squeezed pill passes through a finger
    cams = {
        "user": ((-0.30, 0.24, 0.42), (0.24, -0.03, 0.02), (0, 0, 1)),
        "front": ((0.72, -0.20, 0.34), (0.20, -0.01, 0.06), (0, 0, 1)),
        "side": ((0.26, -0.52, 0.20), (0.25, 0.0, 0.05), (0, 0, 1)),
        "top": ((0.25, -0.02, 0.62), (0.25, -0.02, 0.0), (1, 0, 0)),
        "box": ((0.07, -0.20, 0.20), (0.26, -0.04, 0.03), (0, 0, 1)),
    }
    cam_xml = "".join(f'<camera name="{n}" pos="{p[0]} {p[1]} {p[2]}" xyaxes="{_look_at(p, t, u)}" fovy="45"/>'
                      for n, (p, t, u) in cams.items())
    xml = f"""<mujoco model="doseday_table">
  <include file="{ARM_XML.name}"/>
  <option timestep="0.001" integrator="implicitfast" cone="elliptic"/>
  <visual>
    <global offwidth="1920" offheight="1080" azimuth="200" elevation="-25"/>
    <quality shadowsize="4096"/>
    <headlight diffuse="0.55 0.55 0.55" ambient="0.35 0.35 0.35" specular="0.1 0.1 0.1"/>
  </visual>
  <asset>
    <texture name="sky" type="skybox" builtin="gradient" rgb1="0.92 0.93 0.95" rgb2="0.75 0.77 0.8" width="256" height="256"/>
  </asset>
  <worldbody>
    <light pos="0.2 0.1 1.2" dir="0 0 -1" directional="true" castshadow="true" diffuse="0.6 0.6 0.6"/>
    <geom name="table" type="plane" size="0.9 0.6 0.01" pos="0.25 0 {TABLE_Z / 1000}" rgba="0.95 0.95 0.94 1" {SCENERY}/>
    <geom name="paper" type="box" size="0.285 0.40 0.00015" pos="0.315 0 {(TABLE_Z + 0.15) / 1000:.5f}" rgba="0.13 0.13 0.14 1" {SCENERY}/>
    {cells}
    {pills}
    {cam_xml}
  </worldbody>
</mujoco>
"""
    SCENE_XML.write_text(xml)
    return SCENE_XML


class Twin:
    """The scene plus handles: set arm joints in degrees and the jaw in Viam's percent, read the jaw-tip point."""

    def __init__(self, b: box.Box | None = None, lids_open: float = OPEN_DEG, build: bool = True, **kw):
        self.box = b or box.demo_box()
        self.front, self.hinge_mm = kw.get("front", FRONT), kw.get("hinge", HINGE)  # for landing checks
        path = write_scene(self.box, **kw) if build else SCENE_XML
        self.model = mujoco.MjModel.from_xml_path(str(path))
        self.data = mujoco.MjData(self.model)
        # Clearance probe: the same scene with a 30 mm detection margin on the arm, never stepped.
        self.probe = mujoco.MjModel.from_xml_path(str(path))
        arm = self.model.body("base").id
        for g in range(self.probe.ngeom):
            b = self.probe.geom_bodyid[g]
            while b > 0 and b != arm:
                b = self.probe.body_parentid[b]
            if b == arm and self.probe.geom_contype[g] == 1:
                self.probe.geom_margin[g] = self.probe.geom_gap[g] = PROBE_MARGIN
        self.probe_data = mujoco.MjData(self.probe)
        self.arm_adr = [self.model.jnt_qposadr[self.model.joint(n).id] for n in ARM_JOINTS]
        self.arm_dof = [self.model.jnt_dofadr[self.model.joint(n).id] for n in ARM_JOINTS]
        self.jaw_adr = self.model.jnt_qposadr[self.model.joint("gripper").id]
        self.jaw_dof = self.model.jnt_dofadr[self.model.joint("gripper").id]
        self.hinge = {d: self.model.jnt_qposadr[self.model.joint(f"{d}_hinge").id] for d in box.ROBOT_DAYS}
        for d in box.ROBOT_DAYS:
            self.data.qpos[self.hinge[d]] = np.radians(lids_open)
        mujoco.mj_forward(self.model, self.data)

    def reset(self, lids_open: float | dict = OPEN_DEG):
        """Back to the start: pills on the far mat, Mon-Fri lids at lids_open degrees (a number, or per day)."""
        mujoco.mj_resetData(self.model, self.data)
        for d in box.ROBOT_DAYS:
            deg = lids_open.get(d, 0.0) if isinstance(lids_open, dict) else lids_open
            self.data.qpos[self.hinge[d]] = np.radians(deg)
            if deg > 0:  # the stop sits where the lid was opened to
                self.model.jnt_range[self.model.joint(f"{d}_hinge").id, 1] = np.radians(deg)
        mujoco.mj_forward(self.model, self.data)

    def set_arm(self, q_deg, jaw_pct=None):
        self.data.qpos[self.arm_adr] = np.radians(q_deg)
        if jaw_pct is not None:
            self.data.qpos[self.jaw_adr] = jaw_angle(jaw_pct)

    def finger_low(self) -> float:
        """Lowest point of either finger box, mm, base frame."""
        low = np.inf
        for name in ("finger_fixed", "finger_moving"):
            g = self.model.geom(name).id
            c, r, h = self.data.geom_xpos[g], self.data.geom_xmat[g].reshape(3, 3), self.model.geom_size[g]
            corners = np.array([[sx, sy, sz] for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)]) * h
            low = min(low, float((corners @ r.T + c)[:, 2].min()))
        return low * 1000

    def place_pill(self, xy, name="tums0"):
        """Lay a Tums flat on the paper at xy (mm)."""
        adr = self.model.jnt_qposadr[self.model.joint(f"{name}_free").id]
        dof = self.model.jnt_dofadr[self.model.joint(f"{name}_free").id]
        self.data.qpos[adr:adr + 3] = [xy[0] / 1000, xy[1] / 1000, (TABLE_Z + 0.3 + TUMS_H / 2 + 0.05) / 1000]
        self.data.qpos[adr + 3:adr + 7] = [1, 0, 0, 0]
        self.data.qvel[dof:dof + 6] = 0.0

    def tip(self) -> np.ndarray:
        """box.py's jaw tip (98 mm down the claw axis), mm, base frame."""
        g = self.model.body("gripper").id
        return (self.data.xpos[g] + self.data.xmat[g].reshape(3, 3) @ np.array([0, 0, -0.098])) * 1000
