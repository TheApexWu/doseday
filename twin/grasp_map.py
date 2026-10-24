"""Where on the paper can the arm pick up a Tums, and how should it come at it? Geometry only.

The twin's squeeze physics isn't trusted (smooth box fingers push the pill out; real jaws have teeth), so a
pickup counts when the geometry is right, checked kinematically:
  reach:    the hover and grasp poses are inside the joint limits
  descent:  neither finger touches the pill on the way down
  opening:  the pill sits clear of the fixed finger and inside the open jaw's swing, its centre within the
            finger width, its mid-height within the fingertips
  reading:  the jaw % where the moving finger first meets the pill is >= 3 (the robot's own held check)
Each strategy (claw lean x wrist heading x aim offset x jaw opening) that passes at the spot is then tried with
the pill nudged 6 mm four ways; the score is how many nudges still pass.

    python twin/grasp_map.py        writes twin/out/grasp_map.json and grasp_map.png
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import mujoco
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import box  # noqa: E402
from twin import scene  # noqa: E402
from twin.rehearse import HOVER_DZ, JAW_HELD_MIN, KIN, OUT, SEED, pose  # noqa: E402
from twin.scene import Twin, jaw_angle  # noqa: E402

LEANS = (0.0, 10.0, 20.0, 30.0)
HEADINGS = (-90.0, -45.0, 0.0, 45.0, 90.0)
X_OFFS = (4.0, 8.0, 12.0)          # where the pill should sit: mm from the claw axis toward the moving jaw
OPENS = (42.0, 91.0)
NUDGE, STEP = 6.0, 30.0
FIXED_FACE, FINGER_HALF_W = -7.9, 6.0   # gripper frame mm, from the vendor meshes
RIM_GRIP = 2.0                          # mm each finger must reach down the pill's rim
R_PILL, H_PILL = scene.TUMS_D / 2, scene.TUMS_H


class Geometry:
    def __init__(self, twin: Twin):
        self.t, self.m, self.d = twin, twin.model, twin.data
        self.g = self.m.body("gripper").id
        self.mf = self.m.geom("finger_moving").id
        self.ff = self.m.geom("finger_fixed").id
        self.pill = self.m.geom("tums0").id
        # inner face of the moving finger (gripper frame x, tip region) as a function of the jaw angle
        self.angles = np.linspace(scene.JAW_LO, jaw_angle(100.0), 60)
        faces = []
        for a in self.angles:
            self.d.qpos[self.t.jaw_adr] = a
            mujoco.mj_kinematics(self.m, self.d)
            faces.append(self._moving_face())
        self.faces = np.array(faces)

    def _gframe(self):
        return self.d.xpos[self.g], self.d.xmat[self.g].reshape(3, 3)

    def _moving_face(self) -> float:
        p, r = self._gframe()
        c, rot, h = self.d.geom_xpos[self.mf], self.d.geom_xmat[self.mf].reshape(3, 3), self.m.geom_size[self.mf]
        corners = np.array([[sx, sy, sz] for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)]) * h
        local = ((corners @ rot.T + c) - p) @ r * 1000
        return float(local[:, 0].min())

    def _low(self, geom) -> float:
        c, rot, h = self.d.geom_xpos[geom], self.d.geom_xmat[geom].reshape(3, 3), self.m.geom_size[geom]
        corners = np.array([[sx, sy, sz] for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)]) * h
        return float((corners @ rot.T + c)[:, 2].min()) * 1000

    def finger_low(self, q, pcts) -> float:
        low = np.inf
        for pct in pcts:
            self.t.set_arm(q, pct)
            mujoco.mj_kinematics(self.m, self.d)
            low = min(low, self.t.finger_low())
        return low

    def aim(self, pill_xy, lean, heading, x_off):
        aim = np.array(pill_xy, float)
        for _ in range(2):
            q = pose([*aim, 30.0], lean, heading, SEED)
            self.t.set_arm(q)
            mujoco.mj_kinematics(self.m, self.d)
            xg = self.d.xmat[self.g].reshape(3, 3)[:2, 0]
            aim = np.asarray(pill_xy, float) - x_off * xg / np.linalg.norm(xg)
        return aim

    def check(self, pill_xy, lean, heading, x_off, open_pct, aim=None) -> dict:
        """Does a pill lying at pill_xy end up pinchable when the claw comes down at aim (default: aimed for it)?"""
        try:
            aim = self.aim(pill_xy, lean, heading, x_off) if aim is None else np.asarray(aim, float)
            q30 = pose([*aim, 30.0], lean, heading, SEED)
            low = self.finger_low(q30, np.linspace(open_pct, 0.0, 10))
            z_tip = 30.0 - (low - (scene.TABLE_Z + 0.3 + 0.8))  # lowest finger 0.8 mm over the paper, whole swing
            q_down = pose([*aim, z_tip], lean, heading, q30)
            q_up = pose([*aim, z_tip + HOVER_DZ], lean, heading, q_down)
        except ValueError:
            return {"ok": False, "why": "reach"}
        self.t.reset({})
        self.t.place_pill(pill_xy)
        ft = np.zeros(6)
        for s in np.linspace(0.0, 1.0, 12):  # descent with the jaw open: the fingers must not touch the pill
            self.t.set_arm(q_up + s * (np.asarray(q_down) - q_up), open_pct)
            mujoco.mj_kinematics(self.m, self.d)
            for f in (self.ff, self.mf):
                if mujoco.mj_geomDistance(self.m, self.d, f, self.pill, 0.01, ft) < 0.0005:
                    return {"ok": False, "why": "descent"}
        p, r = self._gframe()
        c = (self.d.xpos[self.m.body("tums0").id] - p) @ r * 1000
        a = r.T @ np.array([0.0, 0.0, 1.0])
        half_x = R_PILL * np.sqrt(max(1 - a[0] ** 2, 0)) + H_PILL / 2 * abs(a[0])
        open_face = float(np.interp(jaw_angle(open_pct), self.angles, self.faces))
        if c[0] - half_x < FIXED_FACE - 0.5:
            return {"ok": False, "why": "on the fixed finger"}
        if c[0] + half_x > open_face - 0.5:
            return {"ok": False, "why": "outside the opening"}
        if abs(c[1]) > FINGER_HALF_W - 1.0:
            return {"ok": False, "why": "off the finger width"}
        touch = float(np.interp(c[0] + half_x, self.faces, self.angles))  # jaw angle where the moving face meets it
        # A flat Tums has a vertical rim: each finger must reach at least RIM_GRIP mm down it at the moment of
        # contact. The squeeze then pushes sideways; tilt of the squeeze axis is recorded, not judged.
        pill_top = self.d.xpos[self.m.body("tums0").id][2] * 1000 + H_PILL / 2
        self.d.qpos[self.t.jaw_adr] = touch
        mujoco.mj_kinematics(self.m, self.d)
        for f in (self.ff, self.mf):
            if self._low(f) > pill_top - RIM_GRIP:
                return {"ok": False, "why": "fingers too high on the rim"}
        tilt = float(np.degrees(np.arcsin(min(abs(self.d.xmat[self.g].reshape(3, 3)[2, 0]), 1.0))))
        pct = (touch - scene.JAW_LO) / scene.JAW_SPAN * 100
        if pct < JAW_HELD_MIN:
            return {"ok": False, "why": "reads empty"}
        return {"ok": True, "reads_pct": round(pct, 1), "squeeze_tilt_deg": round(tilt, 0),
                "aim": [round(float(v), 1) for v in aim],
                "pill_in_jaw": [round(float(v), 1) for v in c]}


def spots(b: box.Box) -> list[tuple[float, float]]:
    away, along = np.asarray(b.away[:2], float), np.asarray(b.along[:2], float)
    mon = np.asarray(b.mon[:2], float)
    pan = KIN.pan_axis()[:2]
    out = []
    for x in np.arange(100.0, 401.0, STEP):
        for y in np.arange(-240.0, 241.0, STEP):
            rel = np.array([x, y]) - mon
            behind, s = rel @ away, rel @ along
            on_box = -15 < behind < 50 and -box.PITCH * 1.5 - 15 < s < box.PITCH * 5.5 + 15
            if not on_box and np.linalg.norm(np.array([x, y]) - pan) >= 110:
                out.append((float(x), float(y)))
    return out


def run():
    twin = Twin()
    geo = Geometry(twin)
    print("control at the run 06 grasp (lean 21.7, heading -88), pill aimed 8 mm into the jaw:",
          geo.check([346.3, -108.1], 21.7, -88.0, 8.0, 42.0))
    print("control, pill 25 mm off where the claw comes down:",
          geo.check([371.3, -83.1], 21.7, -88.0, 8.0, 42.0, aim=geo.aim([346.3, -108.1], 21.7, -88.0, 8.0)))
    grid = spots(twin.box)
    table = []
    for xy in grid:
        passed, why = [], {}
        for lean in LEANS:
            for h in HEADINGS:
                for xo in X_OFFS:
                    for op in OPENS:
                        r = geo.check(xy, lean, h, xo, op)
                        if r["ok"]:
                            passed.append(((lean, h, xo, op), r))
                        else:
                            why[r["why"]] = why.get(r["why"], 0) + 1
        best, best_score = None, -1
        for strat, r in passed:
            score = sum(geo.check([xy[0] + dx, xy[1] + dy], *strat, aim=r["aim"])["ok"]
                        for dx, dy in ((NUDGE, 0), (-NUDGE, 0), (0, NUDGE), (0, -NUDGE)))
            if score > best_score or (score == best_score and strat[0] < best[0][0]):
                best, best_score = (strat, r), score
        table.append({"x": xy[0], "y": xy[1], "strategies_ok": len(passed),
                      "best": None if best is None else {"lean": best[0][0], "heading": best[0][1],
                                                          "x_off": best[0][2], "open_pct": best[0][3],
                                                          "reads_pct": best[1]["reads_pct"],
                                                          "squeeze_tilt_deg": best[1]["squeeze_tilt_deg"]},
                      "nudges_ok": max(best_score, 0), "fails": why})
        print(f"   spot ({xy[0]:5.0f},{xy[1]:5.0f}): {len(passed):3d} strategies ok, best survives "
              f"{max(best_score, 0)}/4 nudges {table[-1]['best'] or ''}", flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "grasp_map.json").write_text(json.dumps(table, indent=1))
    draw(table, twin.box)
    print(f"spots with a strategy that survives all four 6 mm nudges: {sum(t['nudges_ok'] == 4 for t in table)}"
          f"/{len(table)}; with any strategy: {sum(t['strategies_ok'] > 0 for t in table)}/{len(table)}")


def draw(table, b, scale=2.0):
    """Top-down map with the arm's base at the bottom: green = the best approach still fits with the pill 6 mm off
    in any direction, through yellow (2-3 of 4) to red (dead-on only); grey = no approach fits."""
    from PIL import Image, ImageDraw
    w, h = int(520 * scale), int(470 * scale)
    img = Image.new("RGB", (w, h), (245, 245, 243))
    dr = ImageDraw.Draw(img)
    pan = KIN.pan_axis()

    def px(x, y):
        return (w / 2 - y * scale, h - 40 - x * scale)

    for r_mm in (200, 260, 320):
        cx, cy = px(pan[0], pan[1])
        dr.ellipse([cx - r_mm * scale, cy - r_mm * scale, cx + r_mm * scale, cy + r_mm * scale], outline=(200, 200, 200))
        dr.text((cx + 4, cy - r_mm * scale + 2), f"{r_mm / 10:.0f} cm", fill=(140, 140, 140))
    for d in box.DAYS:
        corners = [b.point(d, bh, 0.0)[:2] + s * np.asarray(b.along[:2]) * box.PITCH / 2
                   for bh in (scene.FRONT, scene.HINGE) for s in (-1, 1)]
        dr.polygon([px(*corners[i]) for i in (0, 1, 3, 2)], outline=(70, 70, 70))
        c = b.point(d, 12.0, 0.0)
        dr.text((px(c[0], c[1])[0] - 8, px(c[0], c[1])[1] - 5), d[:2].upper(), fill=(70, 70, 70))
    colours = {4: (60, 170, 80), 3: (150, 190, 70), 2: (215, 190, 60), 1: (220, 130, 60), 0: (200, 70, 60)}
    for t in table:
        cx, cy = px(t["x"], t["y"])
        col = (195, 195, 195) if t["best"] is None else colours[t["nudges_ok"]]
        dr.ellipse([cx - 9, cy - 9, cx + 9, cy + 9], fill=col)
    bx, by = px(pan[0], pan[1])
    dr.ellipse([bx - 18, by - 18, bx + 18, by + 18], outline=(0, 0, 0), width=4)
    dr.text((bx + 24, by - 6), "arm turntable (you sit below)", fill=(0, 0, 0))
    tx, ty = px(346.3, -108.1)
    dr.rectangle([tx - 12, ty - 12, tx + 12, ty + 12], outline=(30, 30, 200), width=3)
    dr.text((tx + 16, ty - 6), "day 1 tray", fill=(30, 30, 200))
    dr.text((10, 10), "Tums pickup map from the twin (geometry: reach, clean descent, pill inside the jaws). Not a grip test.",
            fill=(0, 0, 0))
    dr.text((10, 26), "green: best approach still fits with the pill 6 mm off any way | yellow: 2-3 of 4 | red: dead-on only | "
            "grey: no approach fits", fill=(0, 0, 0))
    img.save(OUT / "grasp_map.png")


if __name__ == "__main__":
    if sys.argv[1:] == ["draw"]:  # redraw from the saved table
        draw(json.loads((OUT / "grasp_map.json").read_text()), Twin().box)
    else:
        run()
