"""Rehearse tomorrow's moves in the twin before the robot makes them.

    python twin/rehearse.py drops     where a released Tums lands: trial_pick's release, box.py's drop poses, a sweep
    python twin/rehearse.py strokes   the Mon-Fri lid strokes: does the lid shut, are the neighbours touched
    python twin/rehearse.py grasp     how far off the tray spot a Tums can lie and still be gripped

The arm follows the planned joints exactly (it is a recording, not a controller) except in `strokes`, where the
vendor's servo model drives it at box.py's torque cap. Lids, pills and the jaw's push are physics.
The twin can't show the latch (the Thu/Fri spring-back), real bounce, or sag beyond the servo model.
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
from twin.scene import Twin, jaw_angle  # noqa: E402

KIN = box.Kinematics()
OUT = ROOT / "twin" / "out"
SEED = [0.0, 15.0, -10.0, 80.0, 3.0]
# scripts/trial_pick.py, unchanged
TRAY, GRASP_Z, HOVER_Z = [346.3, -108.1], 10.6, 50.0
DROP, PICK_LEAN, PICK_HEADING = [247.1, -67.6, 31.0], 21.7, -88.0
CARRY = [([346.3, -108.1, 60.0], 21.7), ([300.0, -85.0, 115.0], 21.7), ([250.0, -68.0, 85.0], 6.0)]
TRIAL_OPEN_PCT, STATION_OPEN_PCT = 91.0, 30.0
HELD_PCT, JAW_OPEN_S = 12.0, 0.3
PROPOSED_DROP = (18.0, 15.0)  # behind the front edge, above the lid tops: inside the swept window with margin   # 12 %: the jaw just touching a 19 mm Tums in the twin's jaw model
PILL_IN_JAW = np.array([0.0016, 0.0, -0.100])  # m, gripper frame: rim against the fixed finger (x -7.9 mm)
PROBE_EVERY = 10  # steps between clearance checks: the claw moves under 0.3 mm in 10 ms at 25 deg/s


def timed(qs, speed):
    """box.densify's path through qs, timed so the fastest joint moves at `speed` deg/s."""
    path = np.array(box.densify([[float(v) for v in q] for q in qs]), float)
    steps = np.abs(np.diff(path, axis=0)).max(axis=1) / speed
    return np.concatenate([[0.0], np.cumsum(steps)]), path


def sample(tp, path, t):
    if t >= tp[-1]:
        return path[-1]
    i = int(np.searchsorted(tp, t, side="right") - 1)
    a = (t - tp[i]) / max(tp[i + 1] - tp[i], 1e-9)
    return path[i] + a * (path[i + 1] - path[i])


class Runner:
    """Steps the twin while the arm and jaw follow a script; records clearances and, optionally, video frames."""

    def __init__(self, twin: Twin, video=None):
        self.twin, self.m, self.d = twin, twin.model, twin.data
        self.video = video  # (camera.Camera, [camera names], frames list, fps)
        self.next_frame = 0.0
        self.time = 0.0
        arm_root = self.m.body("base").id
        self.arm_bodies = {b for b in range(self.m.nbody) if self._under(b, arm_root)}
        self.fingers = {self.m.geom("finger_fixed").id, self.m.geom("finger_moving").id}
        self.clear = {}  # scenery geom name -> (min distance mm, arm geom name, time)
        self.q = None
        self.jaw = None
        self.jaw_servo = False  # True: the jaw moves under its servo (squeezes); False: placed exactly
        self.probe = True

    def _under(self, b, root):
        while b > 0:
            if b == root:
                return True
            b = self.m.body_parentid[b]
        return False

    def _record(self):
        self.k = getattr(self, "k", 0) + 1
        if not self.probe or self.k % PROBE_EVERY:
            return
        pm, pd = self.twin.probe, self.twin.probe_data
        pd.qpos[:] = self.d.qpos
        mujoco.mj_fwdPosition(pm, pd)
        for i in range(pd.ncon):
            c = pd.contact[i]
            g1, g2 = int(c.geom[0]), int(c.geom[1])
            a1, a2 = self.m.geom_bodyid[g1] in self.arm_bodies, self.m.geom_bodyid[g2] in self.arm_bodies
            if a1 == a2:
                continue
            arm_g, other = (g1, g2) if a1 else (g2, g1)
            if arm_g in self.fingers or self.m.geom(other).name.startswith("tums"):
                continue
            name = self.m.geom(other).name
            dist = float(c.dist) * 1000
            if name not in self.clear or dist < self.clear[name][0]:
                part = self.m.mesh(self.m.geom_dataid[arm_g]).name if self.m.geom_dataid[arm_g] >= 0 else "geom"
                self.clear[name] = (round(dist, 1), f"{self.m.body(self.m.geom_bodyid[arm_g]).name}:{part}",
                                    round(self.time, 2))

    def _frame(self):
        if not self.video or self.time < self.next_frame:
            return
        cam, names, frames, fps = self.video
        frames.append([cam.frame(n) for n in names])
        self.next_frame += 1.0 / fps

    def step(self, q, jaw_pct, attach=None, ctrl=False):
        dt = self.m.opt.timestep
        q = np.asarray(q, float)
        if ctrl:  # servo model: the arm is driven, not placed
            for i, n in enumerate(scene.ARM_JOINTS):
                self.d.ctrl[self.m.actuator(n).id] = np.radians(q[i])
        else:
            dq = np.zeros(5) if self.q is None else (q - self.q) / dt
            self.d.qpos[self.twin.arm_adr] = np.radians(q)
            self.d.qvel[self.twin.arm_dof] = np.radians(dq)
        jaw = jaw_angle(jaw_pct)
        if not self.jaw_servo:
            self.d.qvel[self.twin.jaw_dof] = 0.0 if self.jaw is None else (jaw - self.jaw) / dt
            self.d.qpos[self.twin.jaw_adr] = jaw
        self.d.ctrl[self.m.actuator("gripper").id] = jaw
        self.q, self.jaw = q, jaw
        if attach is not None:
            mujoco.mj_kinematics(self.m, self.d)
            g = self.m.body("gripper").id
            rot = self.d.xmat[g].reshape(3, 3)
            adr = self.m.jnt_qposadr[self.m.joint(f"{attach}_free").id]
            dof = self.m.jnt_dofadr[self.m.joint(f"{attach}_free").id]
            self.d.qpos[adr:adr + 3] = self.d.xpos[g] + rot @ PILL_IN_JAW
            quat = np.zeros(4)
            mujoco.mju_mat2Quat(quat, rot.flatten())
            self.d.qpos[adr + 3:adr + 7] = quat
            self.d.qvel[dof:dof + 6] = 0.0
        mujoco.mj_step(self.m, self.d)
        self.time += dt
        self._record()
        self._frame()

    def hold(self, q, jaw_pct, seconds, **kw):
        for _ in range(int(round(seconds / self.m.opt.timestep))):
            self.step(q, jaw_pct, **kw)

    def follow(self, tp, path, jaw_pct, **kw):
        t = 0.0
        while t <= tp[-1]:
            self.step(sample(tp, path, t), jaw_pct, **kw)
            t += self.m.opt.timestep

    def jaw_move(self, q, a, b, seconds, **kw):
        n = int(round(seconds / self.m.opt.timestep))
        for i in range(n):
            self.step(q, a + (b - a) * (i + 1) / n, **kw)


def landing(twin: Twin, pill="tums0") -> dict:
    """Where the pill came to rest, in the frame of the compartment it is nearest to. Inside = within that
    compartment's walls as this twin built them (front wall to back wall, side walls) and below the rim."""
    p = twin.data.xpos[twin.model.body(pill).id] * 1000
    rot = twin.data.xmat[twin.model.body(pill).id].reshape(3, 3)
    b = twin.box
    away = np.asarray(b.away[:2], float)
    side = np.array([-away[1], away[0]])
    best = None
    for day in box.DAYS:
        o = b.point(day, 0.0, 0.0)
        rel = p[:2] - o[:2]
        behind, lateral = float(rel @ away), float(rel @ side)
        if best is None or abs(lateral) < abs(best["lateral"]):
            best = {"day": day, "behind": round(behind, 1), "lateral": round(lateral, 1)}
    rim_z = scene.LID_TOP - scene.LID_T
    lo, hi = twin.front + scene.CELL_FRONT + scene.WALL, twin.hinge_mm - scene.WALL
    inside = (lo < best["behind"] < hi and abs(best["lateral"]) < scene.CELL_W / 2 - scene.WALL
              and scene.TABLE_Z < p[2] < rim_z)
    tilt = float(np.degrees(np.arccos(abs(rot[2, 2]))))
    return {**best, "z": round(float(p[2]), 1), "inside": bool(inside), "tilt_deg": round(tilt, 0)}


def pose(tip, lean, heading, seed=SEED):
    return KIN.ik([float(v) for v in tip], lean, seed, heading=heading)


def drop(twin: Twin, q_start, q_release, open_pct=TRIAL_OPEN_PCT, speed=25.0, settle=1.5, video=None,
         lids_open=scene.OPEN_DEG, via=()) -> dict:
    """Carry a held Tums from q_start through `via` to q_release (one joint move per leg, as the robot makes
    them), open the jaw, go back the same way, let it settle."""
    twin.reset(lids_open)
    run = Runner(twin, video)
    legs = [q_start, *via, q_release]
    run.hold(q_start, HELD_PCT, 0.1, attach="tums0")
    for a, b_ in zip(legs, legs[1:]):
        run.follow(*timed([a, b_], speed), HELD_PCT, attach="tums0")
    run.jaw_move(q_release, HELD_PCT, open_pct, JAW_OPEN_S)
    run.hold(q_release, open_pct, max(0.6 - JAW_OPEN_S, 0.0))
    back = legs[::-1]
    for a, b_ in zip(back, back[1:]):
        run.follow(*timed([a, b_], speed), open_pct)
    run.hold(q_start, open_pct, settle)
    twin.set_arm(q_release)
    mujoco.mj_kinematics(twin.model, twin.data)
    tip = twin.tip()
    return {"release_tip": [round(float(v), 1) for v in tip], "landed": landing(twin), "closest": closest(run.clear, twin)}


def closest(clear: dict, twin=None, top=4) -> list:
    return [(k, *v) for k, v in sorted(clear.items(), key=lambda kv: kv[1][0])[:top]]


def trial_pick_path():
    """Joints the trial script would reach: grasp, the carry waypoints, the release (same IK chain and seeds)."""
    qs = [pose([*TRAY, HOVER_Z], PICK_LEAN, PICK_HEADING)]
    qs.append(pose([*TRAY, GRASP_Z], PICK_LEAN, PICK_HEADING, qs[-1]))
    for p, lean in CARRY:
        qs.append(pose(p, lean, PICK_HEADING, qs[-1]))
    qs.append(pose(DROP, 6.0, PICK_HEADING, qs[-1]))
    return qs


def drops(video=False):
    twin = Twin()
    b = twin.box
    results = {}

    print("1. scripts/trial_pick.py as written: from the last carry point down to Friday's front edge, jaw to 91 %")
    qs = trial_pick_path()
    r = drop(twin, qs[-2], qs[-1])
    results["trial_pick"] = r
    print("  ", json.dumps(r["landed"]), "| closest:", r["closest"][:3])

    print("2. the app's place(): tray hover straight to drop_<day>_hover (22 mm behind, 30 above, lean 5), jaw to 30 %")
    tray_hover = qs[0]
    results["station"] = {}
    for d in box.ROBOT_DAYS:
        _, behind, above, lean = box.DROP
        q = pose(b.point(d, behind, above), lean, box.HEADING)
        r = drop(twin, tray_hover, q, open_pct=STATION_OPEN_PCT, speed=box.MOVE_SPEED)
        results["station"][d] = r
        print(f"   {d}:", json.dumps(r["landed"]), "| closest:", r["closest"][:3])

    print("3. sweep over Friday: where along the compartment and how high to let go (lean 6), from 25 mm above")
    rows = []
    for heading in (PICK_HEADING, box.HEADING):
        for above in (3.0, 15.0, 30.0):
            line = []
            for behind in (-4.0, 0.0, 4.0, 8.0, 12.0, 16.0, 20.0, 24.0, 28.0, 32.0):
                try:
                    q_rel = pose(b.point("fri", behind, above), 6.0, heading)
                    q_top = pose(b.point("fri", behind, above + 25.0), 6.0, heading, q_rel)
                except ValueError:
                    line.append(" -- ")
                    continue
                r = drop(twin, q_top, q_rel, settle=1.0)
                ok = r["landed"]["inside"] and r["landed"]["day"] == "fri"
                near = r["closest"][0][1] if r["closest"] else None
                rows.append({"heading": heading, "above": above, "behind": behind, **r["landed"], "ok": ok,
                             "closest_mm": near})
                line.append(" in " if ok else "out ")
            print(f"   heading {heading:+5.0f} above {above:4.0f}: " + "".join(line))
    print("   (columns: behind the front edge = -4 0 4 8 12 16 20 24 28 32 mm; -- = out of reach)")
    results["sweep"] = rows

    print("4. proposed trial release: Friday's centre (18 mm behind), 15 mm above the lids, from the same carry point")
    q_new = pose(b.point("fri", PROPOSED_DROP[0], PROPOSED_DROP[1]), 6.0, PICK_HEADING, qs[-2])
    r = drop(twin, qs[-2], q_new)
    results["trial_proposed"] = r
    print("  ", json.dumps(r["landed"]), "| tip", r["release_tip"], "| closest:", r["closest"][:3])

    print("5. does it hold if the pill bounces (restitution ~0.4) or the lids open to 90 or 110 deg?")
    pill = twin.model.geom("tums0").id
    stock = (twin.model.geom_solref[pill].copy(), float(twin.model.geom_solmix[pill]))
    cases = [("bouncy pill", (0.01, 0.3), scene.OPEN_DEG), ("lids at 90", None, 90.0), ("lids at 110", None, 110.0)]
    results["sensitivity"] = {}
    for label, solref, lids in cases:
        if solref:
            twin.model.geom_solref[pill], twin.model.geom_solmix[pill] = solref, 1000.0
        line = {}
        r = drop(twin, qs[-2], q_new, lids_open=lids)
        line["trial_proposed"] = (r["landed"]["inside"] and r["landed"]["day"] == "fri", r["closest"][0][:2])
        for d in box.ROBOT_DAYS:
            _, behind, above, lean = box.DROP
            q = pose(b.point(d, behind, above), lean, box.HEADING)
            r = drop(twin, tray_hover, q, open_pct=STATION_OPEN_PCT, speed=box.MOVE_SPEED, lids_open=lids)
            line[d] = (r["landed"]["inside"] and r["landed"]["day"] == d, r["closest"][0][:2])
        twin.model.geom_solref[pill], twin.model.geom_solmix[pill] = stock
        results["sensitivity"][label] = line
        print(f"   {label:12s}", " ".join(f"{k}:{'in' if v[0] else 'OUT'}({v[1][0]} {v[1][1]}mm)" for k, v in line.items()))
    print("6. candidate drop poses for the app: every day x (stock, bouncy pill, lids 90, lids 110)")
    results["station_candidates"] = station_candidates(twin, tray_hover)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "drops.json").write_text(json.dumps(results, indent=1))
    return results


def station_candidates(twin, tray_hover, candidates=((22.0, 30.0), (18.0, 20.0), (16.0, 15.0), (18.0, 15.0), (14.0, 15.0)),
                       conditions=None, quiet=False):
    b, pill = twin.box, twin.model.geom("tums0").id
    stock = (twin.model.geom_solref[pill].copy(), float(twin.model.geom_solmix[pill]))
    conditions = conditions or [("stock", None, scene.OPEN_DEG), ("bouncy", (0.01, 0.3), scene.OPEN_DEG),
                                ("lids90", None, 90.0), ("lids110", None, 110.0)]
    table = []
    for behind, above in candidates:
        misses, worst = [], (1e9, "")
        for label, solref, lids in conditions:
            if solref:
                twin.model.geom_solref[pill], twin.model.geom_solmix[pill] = solref, 1000.0
            for d in box.ROBOT_DAYS:
                try:
                    q = pose(b.point(d, behind, above), box.DROP[3], box.HEADING)
                except ValueError:
                    misses.append(f"{d}/{label}:unreachable")
                    continue
                r = drop(twin, tray_hover, q, open_pct=STATION_OPEN_PCT, speed=box.MOVE_SPEED, lids_open=lids, settle=1.0)
                if not (r["landed"]["inside"] and r["landed"]["day"] == d):
                    misses.append(f"{d}/{label}")
                c = r["closest"][0]
                if c[1] < worst[0]:
                    worst = (c[1], f"{c[0]} on {d}/{label}")
            twin.model.geom_solref[pill], twin.model.geom_solmix[pill] = stock
        table.append({"behind": behind, "above": above, "misses": misses, "closest_mm": worst[0], "closest": worst[1]})
        n = len(conditions) * len(box.ROBOT_DAYS)
        if not quiet:
            print(f"   behind {behind:4.0f} above {above:4.0f}: {n - len(misses):2d}/{n} inside; closest {worst[0]} mm "
                  f"({worst[1]}){'; missed ' + ', '.join(misses) if misses else ''}")
    return table


def hover_heights(heights=(50.0, 80.0, 100.0, 120.0), candidates=((22.0, 30.0), (16.0, 15.0), (16.0, 20.0))):
    """How high tray_hover must be taught so the app's single move to each drop pose clears the open lids."""
    twin = Twin()
    conditions = [("stock", None, scene.OPEN_DEG), ("lids90", None, 90.0), ("bouncy", (0.01, 0.3), scene.OPEN_DEG)]
    out = []
    for z in heights:
        try:
            hover = pose([*TRAY, z], PICK_LEAN, PICK_HEADING)
        except ValueError as e:
            print(f"   tray_hover at {z:.0f} mm: unreachable ({e})")
            continue
        for row in station_candidates(twin, hover, candidates, conditions, quiet=True):
            out.append({"hover_z": z, **row})
            n = len(conditions) * len(box.ROBOT_DAYS)
            print(f"   tray_hover {z:5.0f} | drop behind {row['behind']:4.0f} above {row['above']:4.0f}: "
                  f"{n - len(row['misses']):2d}/{n} inside, closest {row['closest_mm']:6.1f} mm ({row['closest']})")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "hover_heights.json").write_text(json.dumps(out, indent=1))
    return out


def lid_force(twin: Twin, day: str, arm_bodies) -> float:
    """Total normal force (N) the arm puts on this day's lid right now."""
    m, d = twin.model, twin.data
    lid = m.body(f"{day}_lidbody").id
    f6, total = np.zeros(6), 0.0
    for i in range(d.ncon):
        c = d.contact[i]
        b1, b2 = m.geom_bodyid[int(c.geom[0])], m.geom_bodyid[int(c.geom[1])]
        if (b1 == lid and b2 in arm_bodies) or (b2 == lid and b1 in arm_bodies):
            if c.dist < 0:
                mujoco.mj_contactForce(m, d, i, f6)
                total += abs(f6[0])
    return total


def stroke(twin: Twin, day: str, torque=box.STROKE_TORQUE, lids_open=scene.OPEN_DEG, video=None,
           steps=None, lift=None) -> dict:
    """box.py's stroke for one day, driven through the vendor's servo model at the stroke's torque cap:
    one dense move to the press, hold, then the lift, as run_stroke does it."""
    m, d = twin.model, twin.data
    stock_lift = box.LIFT
    if lift is not None:
        box.LIFT = lift
    try:
        wps = box.plan(KIN, twin.box, day, SEED, steps=steps or box.STROKE)
    finally:
        box.LIFT = stock_lift
    names = [w["name"] for w in wps]
    press_i = names.index("press")
    twin.reset(lids_open)
    stock = m.actuator_forcerange.copy()
    for n in scene.ARM_JOINTS:
        m.actuator_forcerange[m.actuator(n).id] = stock[m.actuator(n).id] * torque / 1000.0
    run = Runner(twin, video)
    q0 = np.asarray(wps[0]["joints"], float)
    d.qpos[twin.arm_adr] = np.radians(q0)
    run.q = q0
    hinge = twin.hinge
    start = {k: float(d.qpos[a]) for k, a in hinge.items()}
    peak = {k: 0.0 for k in hinge}
    lid_min, force_max = float('inf'), 0.0
    track_err = 0.0

    def watch(target_q=None):
        nonlocal lid_min, force_max, track_err
        for k, a in hinge.items():
            peak[k] = max(peak[k], abs(float(d.qpos[a]) - start[k]))
        lid_min = min(lid_min, float(np.degrees(d.qpos[hinge[day]])))
        force_max = max(force_max, lid_force(twin, day, run.arm_bodies))
        if target_q is not None:
            track_err = max(track_err, float(np.abs(np.degrees(d.qpos[twin.arm_adr]) - target_q).max()))

    for _ in range(300):  # settle on the servos at the first waypoint
        run.step(q0, 0.0, ctrl=True)
    tp, path = timed([w["joints"] for w in wps[:press_i + 1]], box.STROKE_SPEED)
    t = 0.0
    while t <= tp[-1] + 0.5:  # run_stroke waits for arrival (up to 2 s) before the hold
        q = sample(tp, path, t)
        run.step(q, 0.0, ctrl=True)
        watch(q)
        t += m.opt.timestep
    twin_tip_press = twin.tip()
    for _ in range(int(0.3 / m.opt.timestep)):  # PRESS_HOLD_S
        run.step(path[-1], 0.0, ctrl=True)
        watch()
    at_press = float(np.degrees(d.qpos[hinge[day]]))
    tp, path = timed([w["joints"] for w in wps[press_i:]], box.STROKE_SPEED)
    t = 0.0
    while t <= tp[-1] + 0.5:
        run.step(sample(tp, path, t), 0.0, ctrl=True)
        watch()
        t += m.opt.timestep
    m.actuator_forcerange[:] = stock
    neighbours = {k: round(float(np.degrees(v)), 1) for k, v in peak.items() if k != day and v > np.radians(1)}
    return {
        "day": day, "lid_min_deg": round(lid_min, 1), "lid_at_press_deg": round(at_press, 1),
        "lid_after_lift_deg": round(float(np.degrees(d.qpos[hinge[day]])), 1),
        "press_force_N": round(force_max, 2), "neighbours_moved_deg": neighbours,
        "press_tip_planned": wps[press_i]["tip"], "press_tip_sim": [round(float(v), 1) for v in twin_tip_press],
        "track_err_deg": round(track_err, 1),
        "closest_other": [c for c in closest(run.clear, top=8) if not c[0].startswith(day + "_")][:2],
    }


def strokes():
    twin = Twin()
    rows = []
    for torque in (box.STROKE_TORQUE, 1000):
        for d in box.ROBOT_DAYS:
            r = stroke(twin, d, torque)
            rows.append({"torque": torque, **r})
            print(f"   torque {torque:4d} {d}: lid min {r['lid_min_deg']:5.1f} deg, at press {r['lid_at_press_deg']:5.1f}, "
                  f"after lift {r['lid_after_lift_deg']:5.1f}; peak force {r['press_force_N']:5.2f} N; "
                  f"neighbours moved {r['neighbours_moved_deg'] or 'none'}; tracking {r['track_err_deg']} deg; "
                  f"press tip sim {r['press_tip_sim']} vs plan {r['press_tip_planned']}; closest other {r['closest_other'][:1]}")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "strokes.json").write_text(json.dumps(rows, indent=1))
    return rows


LIFT_VARIANTS = {
    "today": (None, None),
    "slide back, then lift": ([*box.STROKE, ("slide", 26.0, 0.0, 0.0)], None),
    "press further back": ([*box.STROKE[:-1], ("press", 20.0, -11.0, -5.0)], None),
    "lift back diagonally": (None, ("lift", 32.0, 50.0, 12.0)),
}


RECOMMENDED_DROP = (6.0, 22.0, 6.0, PICK_HEADING)  # behind, above, lean, heading: drop_design's pick


def final(days=box.ROBOT_DAYS):
    """The recommended release, along the real paths: trial_pick's carry into Friday and the app's tray->day move
    via a high crossing. Both lid sizes, stock and bouncy pill."""
    behind, above, lean, heading = RECOMMENDED_DROP
    rows = []
    for front in (0.0, -10.0):
        twin = Twin(front=front)
        b, pill = twin.box, twin.model.geom("tums0").id
        stock = (twin.model.geom_solref[pill].copy(), float(twin.model.geom_solmix[pill]))
        qs = trial_pick_path()
        for bounce in (False, True):
            if bounce:
                twin.model.geom_solref[pill], twin.model.geom_solmix[pill] = (0.01, 0.3), 1000.0
            q_rel = pose(b.point("fri", behind, above), lean, heading, qs[-2])
            r_ = drop(twin, qs[-2], q_rel)
            line = [f"trial:{'in' if r_['landed']['inside'] and r_['landed']['day'] == 'fri' else 'OUT'}"
                    f"({r_['closest'][0][1] if r_['closest'] else 99})"]
            rows.append({"front": front, "bounce": bounce, "path": "trial_pick", "day": "fri", **r_})
            for d in days:
                q_drop = pose(b.point(d, behind, above), lean, heading)
                q_above = pose(b.point(d, behind, above + 30.0), lean, heading, q_drop)
                r_ = drop(twin, qs[0], q_drop, open_pct=STATION_OPEN_PCT, speed=box.MOVE_SPEED, via=(qs[3], q_above))
                ok = r_["landed"]["inside"] and r_["landed"]["day"] == d
                rows.append({"front": front, "bounce": bounce, "path": "app_high", "day": d, **r_})
                line.append(f"{d}:{'in' if ok else 'OUT'}({r_['closest'][0][1] if r_['closest'] else 99})")
            twin.model.geom_solref[pill], twin.model.geom_solmix[pill] = stock
            print(f"   lid edge {front:+.0f} {'bouncy' if bounce else 'stock '}: " + " ".join(line)
                  + "   (closest mm to anything)", flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "final.json").write_text(json.dumps(rows, indent=1))
    return rows


def pick_video(out_mp4, cameras="box", fps=30, day="fri"):
    """A rendered rehearsal of trial_pick with the recommended release: hover, descend, grip, carry high, release
    into the day, retreat. The grip is placed, not squeezed (the twin's squeeze isn't trusted): it is a picture of
    the motion, not evidence that the grip holds."""
    import imageio.v2 as imageio
    from twin.render import Camera
    twin = Twin()
    m, d = twin.model, twin.data
    names = cameras.split(",")
    frames = []
    run = Runner(twin, (Camera(twin), names, frames, fps))
    run.probe = False
    behind, above, lean, heading = RECOMMENDED_DROP
    qs = trial_pick_path()
    q_hover, q_grasp = qs[0], qs[1]
    twin.reset(scene.OPEN_DEG)
    twin.set_arm(q_grasp, 42.0)
    mujoco.mj_kinematics(m, d)
    g = m.body("gripper").id
    rot, p = d.xmat[g].reshape(3, 3), d.xpos[g]
    spot = p + rot @ np.array([0.006, 0.0, -0.1])
    twin.place_pill([spot[0] * 1000, spot[1] * 1000])
    mujoco.mj_forward(m, d)
    run.hold(q_hover, 42.0, 0.6)
    run.follow(*timed([q_hover, q_grasp], GRASP_SPEED), 42.0)
    run.jaw_move(q_grasp, 42.0, HELD_PCT, 0.5)
    pid = m.body("tums0").id
    rel_p = rot.T @ (d.xpos[pid] - d.xpos[g])
    rel_r = rot.T @ d.xmat[pid].reshape(3, 3)

    def carry(q, jaw):  # the pill rides where it was gripped
        run.step(q, jaw)
        mujoco.mj_kinematics(m, d)
        rg = d.xmat[g].reshape(3, 3)
        adr = m.jnt_qposadr[m.joint("tums0_free").id]
        dof = m.jnt_dofadr[m.joint("tums0_free").id]
        d.qpos[adr:adr + 3] = d.xpos[g] + rg @ rel_p
        quat = np.zeros(4)
        mujoco.mju_mat2Quat(quat, (rg @ rel_r).flatten())
        d.qpos[adr + 3:adr + 7] = quat
        d.qvel[dof:dof + 6] = 0.0

    q_rel = pose(twin.box.point(day, behind, above), lean, heading, qs[-2])
    legs = [q_grasp, *qs[2:-1], q_rel]
    for a, b_ in zip(legs, legs[1:]):
        tp, path = timed([a, b_], 25.0)
        tt = 0.0
        while tt <= tp[-1]:
            carry(sample(tp, path, tt), HELD_PCT)
            tt += m.opt.timestep
    run.jaw_move(q_rel, HELD_PCT, TRIAL_OPEN_PCT, JAW_OPEN_S)
    run.hold(q_rel, TRIAL_OPEN_PCT, 0.6)
    run.follow(*timed([q_rel, qs[-2]], 25.0), TRIAL_OPEN_PCT)
    run.hold(qs[-2], TRIAL_OPEN_PCT, 1.0)
    with imageio.get_writer(out_mp4, fps=fps, codec="libx264", quality=8, macro_block_size=8) as w:
        for views in frames:
            w.append_data(np.concatenate(views, axis=1))
    print(f"{out_mp4}: {len(frames)} frames; pill ended {landing(twin)}")


def lifts(days=("tue", "wed", "thu", "fri")):
    """Does the lid stay shut after the lift? The twin has no latch, so 'shut' here means nothing pulled it open."""
    rows = []
    for front in (0.0, -10.0):
        twin = Twin(front=front)
        for label, (steps, lift) in LIFT_VARIANTS.items():
            out = []
            for d in days:
                try:
                    r_ = stroke(twin, d, steps=steps, lift=lift)
                except ValueError as e:
                    out.append(f"{d}:unreachable")
                    continue
                rows.append({"front": front, "variant": label, **r_})
                out.append(f"{d}:{'shut' if r_['lid_after_lift_deg'] < 5 else 'OPEN'}({r_['lid_after_lift_deg']:.0f}, press {r_['lid_at_press_deg']:.0f})")
            print(f"   lid edge {front:+.0f} | {label:22s} " + " ".join(out), flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "lifts.json").write_text(json.dumps(rows, indent=1))
    return rows


def drop_design(days=("fri", "mon", "wed")):
    """With the lids standing up as fitted, which release keeps the claw off every lid and lands the pill inside?
    Two lid sizes, both consistent with run 05: 25 mm from the registered edge, or 35 mm with the edge 10 mm
    behind the physical front (what the photos suggest). Straight down from 25 mm above the release."""
    leans, headings = (-20.0, -10.0, 0.0, 6.0), (PICK_HEADING, box.HEADING)
    behinds, aboves = (2.0, 6.0, 10.0, 14.0), (10.0, 22.0, 35.0)
    tally = {}
    for front in (0.0, -10.0):
        twin = Twin(front=front)
        for day in days:
            for lean in leans:
                for heading in headings:
                    for behind in behinds:
                        for above in aboves:
                            k = (lean, heading, behind, above)
                            try:
                                q_rel = pose(twin.box.point(day, behind, above), lean, heading)
                                q_top = pose(twin.box.point(day, behind, above + 25.0), lean, heading, q_rel)
                            except ValueError:
                                tally.setdefault(k, []).append(("reach", None))
                                continue
                            r_ = drop(twin, q_top, q_rel, settle=1.0)
                            ok = r_["landed"]["inside"] and r_["landed"]["day"] == day
                            near = min((c[1] for c in r_["closest"]), default=99.0)
                            tally.setdefault(k, []).append(("in" if ok else "out", near))
        print(f"   lid model front {front:+.0f}: done", flush=True)
    rows = []
    for k, res in tally.items():
        good = sum(1 for s, near in res if s == "in" and near is not None and near >= 2.0)
        worst = min((near for _, near in res if near is not None), default=None)
        rows.append({"lean": k[0], "heading": k[1], "behind": k[2], "above": k[3], "good": good, "of": len(res),
                     "closest_mm": worst})
    rows.sort(key=lambda r: (-r["good"], -(r["closest_mm"] or -99)))
    for r_ in rows[:12]:
        print(f"   lean {r_['lean']:+4.0f} heading {r_['heading']:+4.0f} behind {r_['behind']:4.0f} above {r_['above']:4.0f}:"
              f" {r_['good']}/{r_['of']} inside with >= 2 mm to every lid; closest {r_['closest_mm']} mm")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "drop_design.json").write_text(json.dumps(rows, indent=1))
    return rows


def transit(drop_at=(16.0, 15.0), above_at=(16.0, 50.0, 12.0)):
    """The app's place() with a high crossing: tray_hover -> the trial's carry point -> above the day -> down."""
    twin = Twin()
    b, pill = twin.box, twin.model.geom("tums0").id
    stock = (twin.model.geom_solref[pill].copy(), float(twin.model.geom_solmix[pill]))
    qs = trial_pick_path()
    tray_hover, high = qs[0], qs[3]  # the carry's (300, -85, 115) point
    conditions = [("stock", None, scene.OPEN_DEG), ("bouncy", (0.01, 0.3), scene.OPEN_DEG),
                  ("lids90", None, 90.0), ("lids110", None, 110.0)]
    rows = []
    for label, solref, lids in conditions:
        if solref:
            twin.model.geom_solref[pill], twin.model.geom_solmix[pill] = solref, 1000.0
        for d in box.ROBOT_DAYS:
            q_drop = pose(b.point(d, *drop_at), box.DROP[3], box.HEADING)
            q_above = pose(b.point(d, above_at[0], above_at[1]), above_at[2], box.HEADING, q_drop)
            for name, via in (("direct", ()), ("high", (high, q_above))):
                r = drop(twin, tray_hover, q_drop, open_pct=STATION_OPEN_PCT, speed=box.MOVE_SPEED,
                         lids_open=lids, settle=1.0, via=via)
                ok = r["landed"]["inside"] and r["landed"]["day"] == d
                rows.append({"route": name, "day": d, "condition": label, "inside": ok, "closest": r["closest"][:2]})
        twin.model.geom_solref[pill], twin.model.geom_solmix[pill] = stock
    for name in ("direct", "high"):
        sel = [r for r in rows if r["route"] == name]
        worst = min(sel, key=lambda r: r["closest"][0][1])
        print(f"   {name:6s}: {sum(r['inside'] for r in sel)}/{len(sel)} inside; closest {worst['closest'][0][1]} mm "
              f"({worst['closest'][0][0]} by {worst['closest'][0][2]}, {worst['day']}/{worst['condition']})")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "transit.json").write_text(json.dumps(rows, indent=1))
    return rows


GRIP_NM = 0.5        # jaw servo's squeeze cap, N m: below ~0.3 the vendor's servo model can't close the jaw at all
JAW_HELD_MIN = 3.0   # actions.py: the robot calls a pill held when the closing jaw stops at or above this
HOVER_DZ, GRASP_SPEED = 40.0, 15.0


def fingers_on_pill(twin: Twin, pill="tums0", min_n=0.1) -> bool:
    """Truth the robot doesn't have: both fingers press on the pill right now."""
    m, d = twin.model, twin.data
    g_pill = m.geom(pill).id
    pressing = set()
    f6 = np.zeros(6)
    for i in range(d.ncon):
        c = d.contact[i]
        a, b = int(c.geom[0]), int(c.geom[1])
        if g_pill in (a, b):
            other = m.geom(b if a == g_pill else a).name
            if other.startswith("finger_"):
                mujoco.mj_contactForce(m, d, i, f6)
                if f6[0] > min_n:
                    pressing.add(other)
    return len(pressing) == 2


def aim_for(twin: Twin, pill_xy, lean, heading, x_off, z=30.0, seed=SEED):
    """Claw-axis point that puts the pill x_off mm into the jaw opening (gripper +x, from the claw axis toward the
    moving jaw; the fixed finger's face is at -7.9). Two passes: the gripper's x axis depends on the pose."""
    aim = np.array(pill_xy, float)
    for _ in range(2):
        q = pose([*aim, z], lean, heading, seed)
        twin.set_arm(q)
        mujoco.mj_kinematics(twin.model, twin.data)
        xg = twin.data.xmat[twin.model.body("gripper").id].reshape(3, 3)[:2, 0]
        aim = np.asarray(pill_xy, float) - x_off * xg / np.linalg.norm(xg)
    return aim


def grasp(twin: Twin, pill_xy, lean, heading, aim_xy=None, x_off=6.0, open_pct=42.0, clear_mm=1.5, video=None) -> dict:
    """Top-down pick of a Tums lying at pill_xy: hover, descend so the lowest finger clears the paper by clear_mm,
    close the jaw under its servo, lift. Held = the pill rose with the claw. The claw aims so the pill sits x_off mm
    into the jaw opening, or at aim_xy if given (to test a pill that isn't where the claw expects)."""
    m, d = twin.model, twin.data
    twin.reset({})
    aim = list(aim_xy) if aim_xy is not None else list(aim_for(twin, pill_xy, lean, heading, x_off))
    q_probe = pose([*aim, 30.0], lean, heading)
    low = np.inf
    for pct in np.linspace(open_pct, 0.0, 12):  # the moving finger dips lower as it swings shut
        twin.set_arm(q_probe, pct)
        mujoco.mj_kinematics(m, d)
        low = min(low, twin.finger_low())
    z_tip = 30.0 - (low - (scene.TABLE_Z + clear_mm))
    q_down = pose([*aim, z_tip], lean, heading, q_probe)
    q_up = pose([*aim, z_tip + HOVER_DZ], lean, heading, q_down)
    twin.reset({})
    twin.place_pill(pill_xy)
    grip = m.actuator("gripper").id
    stock = m.actuator_forcerange[grip].copy()
    m.actuator_forcerange[grip] = [-GRIP_NM, GRIP_NM]
    run = Runner(twin, video)
    run.probe = False
    run.hold(q_up, open_pct, 0.2)
    run.follow(*timed([q_up, q_down], GRASP_SPEED), open_pct)
    moved = float(np.linalg.norm(d.xpos[m.body("tums0").id][:2] * 1000 - np.asarray(pill_xy)))
    run.jaw_servo = True
    # Close to 0 % and wait until the reading stops changing, as trial_pick's settle() does: three readings
    # 0.15 s apart within 0.3 % of each other, or 4 s.
    last, still, waited = None, 0, 0.0
    while still < 3 and waited < 4.0:
        run.hold(q_down, 0.0, 0.15)
        waited += 0.15
        now = (float(d.qpos[twin.jaw_adr]) - scene.JAW_LO) / scene.JAW_SPAN * 100
        still = still + 1 if last is not None and abs(now - last) < 0.3 else 0
        last = now
    closed_pct = last
    pinched = fingers_on_pill(twin)
    run.follow(*timed([q_down, q_up], GRASP_SPEED), 0.0)
    run.hold(q_up, 0.0, 0.3)
    m.actuator_forcerange[grip] = stock
    p = d.xpos[m.body("tums0").id] * 1000
    jaw_pct = (float(d.qpos[twin.jaw_adr]) - scene.JAW_LO) / scene.JAW_SPAN * 100
    says_held = closed_pct >= JAW_HELD_MIN
    return {"caught": pinched, "robot_says_held": says_held, "false_alarm": says_held and not pinched,
            "held": bool(p[2] > scene.TABLE_Z + 20.0),
            "jaw_pct": round(jaw_pct, 1), "closed_pct": round(closed_pct, 1),
            "pushed_on_descent_mm": round(moved, 1), "z_tip": round(z_tip, 1), "aim": [round(float(v), 1) for v in aim]}


def grasp_checks():
    """Success = the closing jaw stops on the pill (>= 3 %), the robot's own held check; the twin reproduces the
    real stall (8.6 % vs 8 %). Whether the pill then survives the lift is reported separately: the twin's smooth
    fingers have no teeth, so it is the weaker number."""
    twin = Twin()
    print("controls at the tray spot, run 06's claw angle (lean 21.7, heading -88):")
    on = grasp(twin, TRAY, PICK_LEAN, PICK_HEADING)
    off = grasp(twin, [TRAY[0] + 25.0, TRAY[1] + 25.0], PICK_LEAN, PICK_HEADING, aim_xy=on["aim"])
    print(f"   pill in the jaws: pinched={on['caught']} (jaw stopped at {on['closed_pct']}%, real ~8%), lifted={on['held']}")
    print(f"   pill 35 mm away:  pinched={off['caught']} (jaw stopped at {off['closed_pct']}%, real empty 0.4-0.7%)")
    ok = on["caught"] and not off["caught"] and on["robot_says_held"] and not off["robot_says_held"]
    print("   controls", "PASS" if ok else "FAIL: the twin can't tell a hit from a miss")
    results = {"controls": {"on": on, "off": off, "pass": ok}}
    for label, open_pct, clear in (("normal grip (jaw 42%)", 42.0, 1.5), ("sweep grip (jaw 91%, fingers low)", 91.0, 1.0)):
        grid = []
        print(f"{label}: pill offset from where the claw expects it, mm (rows dy +12..-12, columns dx -12..+12;"
              " L = pinched and lifted, c = pinched only, ! = robot would think held but isn't, . = missed)")
        for dy in (12, 9, 6, 3, 0, -3, -6, -9, -12):
            line = ""
            for dx in (-12, -9, -6, -3, 0, 3, 6, 9, 12):
                r = grasp(twin, [TRAY[0] + dx, TRAY[1] + dy], PICK_LEAN, PICK_HEADING, aim_xy=on["aim"],
                          open_pct=open_pct, clear_mm=clear)
                grid.append({"dx": dx, "dy": dy, **r})
                line += (" L " if r["held"] else " c " if r["caught"] else " ! " if r["false_alarm"] else " . ")
            print(f"   dy {dy:+3d} " + line, flush=True)
        print(f"   pinched {sum(g['caught'] for g in grid)}/81, lifted {sum(g['held'] for g in grid)}/81, "
              f"false alarms {sum(g['false_alarm'] for g in grid)}/81")
        results[label] = grid
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "grasp_checks.json").write_text(json.dumps(results, indent=1))
    return results


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "drops"
    if mode == "pick-video":
        pick_video(*sys.argv[2:])
        sys.exit(0)
    if mode == "stroke-video":  # OUT.mp4 CAMERA DAY: box.py's stroke through the servo model, as the robot runs it
        import imageio.v2 as imageio
        from twin.render import Camera
        out_mp4, cam, day = sys.argv[2:5]
        twin, frames = Twin(), []
        res = stroke(twin, day, video=(Camera(twin), [cam], frames, 30))
        with imageio.get_writer(out_mp4, fps=30, codec="libx264", quality=8, macro_block_size=8) as w:
            for views in frames:
                w.append_data(np.concatenate(views, axis=1))
        print(out_mp4, len(frames), "frames;", {k: res[k] for k in ("lid_at_press_deg", "lid_after_lift_deg")})
        sys.exit(0)
    {"drops": drops, "hover": hover_heights, "transit": transit, "strokes": strokes,
     "grasp": grasp_checks, "drop-design": drop_design, "lifts": lifts, "final": final}[mode]()
