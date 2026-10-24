"""Write labels.csv, motion_labeled.csv and frames_index.csv for every recorded run (23 Oct).

  python scripts/label_runs.py            all runs
  python scripts/label_runs.py 04 06      only runs whose folder contains these strings

Two kinds of label, kept apart in the `evidence` column:
- curated: events read from the run's README, its analysis, or the frames (who checked what is in `evidence`)
- auto: a rule on the motion signals, filling the time between curated events (`auto: ...`)
Every motion row gets the label of the curated segment covering it, else its auto label.
"""
import csv
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import box  # noqa: E402

KIN = box.Kinematics()
BOX = box.demo_box()  # fitted from run 04; valid only after the box was moved and taped (~18:00, 23 Oct)
CAMERA_LAG_S = 1.5    # frames show the arm 1-2 s late (measured 23 Oct); t_motion_est = t_frame - offset - lag

SEG_FIELDS = ["t_start", "t_end", "phase", "target", "outcome", "evidence", "notes"]


def seg(t0, t1, phase, target="", outcome="", evidence="", notes=""):
    return dict(t_start=round(t0, 1), t_end=round(t1, 1), phase=phase, target=target, outcome=outcome,
                evidence=evidence, notes=notes)


# ---- curated events per run (times on the motion CSV clock) -------------------------------------------------

def run01():
    # attempts.py: 17 grasp attempts, hit/miss read by hand from the 1 Hz frames (ANALYSIS.md)
    attempts = [(27.3, 1, "blue"), (35.6, 0, "dark"), (38.8, 1, "dark"), (46.3, 0, "red"), (50.7, 0, "red"),
                (54.0, 0, "yellow"), (56.7, 0, "yellow"), (58.9, 1, "yellow"), (66.1, 1, "red"), (72.2, 1, "dark"),
                (76.8, 0, "blue"), (81.2, 1, "dark"), (86.5, 0, "yellow"), (95.0, 0, "blue"), (98.5, 0, "yellow"),
                (100.0, 0, "yellow"), (101.7, 0, "yellow")]
    return [seg(t - 0.5, t + 1.0, "grasp_close", f"pill:{c} M&M", "success" if h else "fail",
                "curated: attempts.py onset + hit/miss read from frames (ANALYSIS.md)")
            for t, h, c in attempts]


def run02():
    out = [seg(21.1, 21.9, "lid_press", "", "unknown", "curated: README (shallow touch)")]
    # README: 14 dips; 12 bottom out at z 96-112 (wrist frame); lids Sun..Sat shut afterwards (frames 24/28, 43/47, 63/67 s)
    for t0, t1 in [(22.1, 27.6), (30.7, 34.9), (36.1, 39.0), (41.4, 59.9), (61.0, 65.8), (68.2, 74.4), (76.1, 82.3),
                   (84.9, 92.8), (101.7, 107.4), (110.2, 110.8)]:
        out.append(seg(t0, t1, "lid_press", "", "success",
                       "curated: z dips (strokes.py) + README: all lids shut after the presses, frames 24/28 43/47 63/67",
                       "teleop; day not identified per press (box skewed 20 deg)"))
    out.append(seg(98.0, 100.0, "lid_press", "", "unknown", "curated: README (shallow touch on a raised lid edge)"))
    return out


def run_buttons():
    table = [(1, 144, 108), (2, 135, 84), (3, 137, 56), (4, 138, 23), (5, 137, 11), (6, 135, -23), (7, 127, -47)]
    return [("press_table", table)]  # times are found from the motion below (no times in the README)


def run03():
    return [seg(84.0, 88.0, "tab_press", "tue", "success",
                "curated: README + frames (shut at 84 s, compartment showing at 88 s, lid back by 91 s)",
                "fingertip press with the closed jaw on the latch tab's black dot")]


def run04():
    days = [("mon", 87.0, 91.9, "frames 116-117 flat"), ("tue", 92.6, 95.9, "frame 95 flat"),
            ("wed", 96.8, 101.8, "frames 99-101 flat"), ("thu", 102.7, 106.4, "frames 104-105 flat"),
            ("fri", 107.0, 110.8, "frames 108-111 flat"), ("sat", 110.8, 113.4, "frames 110-113 flat")]
    out = [seg(a, b, "lid_press", d, "success", f"curated: frames (lid raised before, {ev} after)",
               "hand-guided rake: start ~60 mm beyond the front edge, pull toward the arm while descending")
           for d, a, b, ev in days]
    out += [seg(113.4, 117.4, "sweep", "sat..sun", "success", "curated: frames 113-117 (claw dragged along the front edges)"),
            seg(50.0, 75.0, "survey_view", "far pills", "", "curated: frames 50-75 (loose pills beyond the box)"),
            seg(119.0, 156.0, "idle", "", "", "curated: parked at view_box_high")]
    return out


TRIES05 = {  # file -> (days in order, outcome per day, try label); README table
    "teleop-184017.csv": (["wed"], ["fail"], "try 1: waypoint by waypoint, torque 350: stopped at arc1, lid untouched"),
    "teleop-184415.csv": (["wed"], ["fail"], "try 2: continuous sparse path cut corners, never pressed"),
    "teleop-184503.csv": (["wed"], ["fail"], "try 3: dense path, press -2.4 mm: closed but did not latch"),
    "teleop-184539.csv": (["wed"], ["success"], "try 4: jaws turned 90 deg, press -9 mm: latched (Alex)"),
    "teleop-184613.csv": (["thu", "tue"], ["fail", "success"], "4b: Thu sprang back, Tue latched"),
    "teleop-184649.csv": (["mon", "fri"], ["unknown", "fail"], "4c: Mon not checked, Fri sprang back"),
    "teleop-184757.csv": ([], [], "aborted before motion (code error)"),
    "teleop-184813.csv": (["thu", "fri"], ["fail", "fail"], "5: box refit 6.2 deg: both swung shut, sprang back"),
    "teleop-184919.csv": (["thu", "fri"], ["fail", "fail"], "6: press -13 mm (stalled -11.3/-11.6): sprang back"),
    "teleop-185021.csv": (["thu", "fri"], ["fail", "fail"], "7: press mid-lid: sprang back"),
}


def run06():
    return [
        seg(0.0, 84.0, "idle", "", "", "curated: CSV still at jaw tip (262,-64,73), jaw 42%"),
        seg(84.0, 99.0, "manual_adjust", "tray", "", "curated: frames 88-94 show Alex's hand moving the claw out"),
        seg(99.0, 171.0, "hover", "pill:tums", "", "curated: claw held around a Tums at jaw tip (346,-108,11), frames 100-140",
            "Alex holding the open claw still at the grasp pose (lean ~22 deg, heading -88)"),
        seg(171.0, 180.0, "grasp_close", "pill:tums", "success", "curated: jaw 42% -> ~8% (held; empty close reads <1%)"),
        seg(180.0, 197.0, "hold_transport", "pill:tums", "", "curated: jaw ~8% while moving over the box (239,-43,36)"),
        seg(197.0, 209.0, "hold_transport", "pill:tums", "",
            "curated: frame 200 shows a second TUMS just ahead of the closed jaws",
            "down at (335,-23,9) still holding the first pill; read as pointing out the next pill (inferred)"),
        seg(209.0, 226.0, "hold_transport", "fri", "", "curated: CSV path to Friday's front edge (248,-68,30)"),
        seg(226.0, 228.5, "release_open", "fri", "unknown",
            "curated: jaw 9% -> 91% at Friday's front edge; frames 223-233",
            "a pill is visible in Friday afterwards; frames cannot separate in-the-compartment from on-the-lid"),
        seg(228.5, 236.0, "lift", "", "", "curated: CSV rises to (269,-33,78)"),
        seg(236.0, 240.0, "descend", "", "", "curated: CSV down to (372,8,6), jaws open; frame 239 shows a red M&M and a mint pill"),
    ]


RUNS = {
    "2026-10-23-teleop-sort-01": dict(csv=["motion.csv"], frames=[("frames", 0.0)], box=False, curated=run01),
    "2026-10-23-lid-buttons-manual": dict(csv=["motion.csv"], frames=[], box=False, curated=run_buttons),
    "2026-10-23-lid-close-02": dict(csv=["motion.csv"], frames=[("frames", 0.0), ("frames_fast", -27.0)], box=False,
                                     curated=run02),
    "2026-10-23-lid-open-teleop-03": dict(csv=["motion.csv"], frames=[("frames", 1.0)], box=False, curated=run03),
    "2026-10-23-arm-exploration/a-175149": dict(csv=["motion.csv"], frames=[("frames", 0.0)], box=False, curated=None),
    "2026-10-23-arm-exploration/b-180722": dict(csv=["motion.csv"], frames=[("frames", 1.0)], box=True, curated=None),
    "2026-10-23-arm-exploration/c-181020": dict(csv=["motion.csv"], frames=[("frames", 0.0)], box=True, curated=None),
    "2026-10-23-manual-survey-04": dict(csv=["motion.csv"], frames=[("frames", 0.0)], box=True, curated=run04),
    "2026-10-23-lid-flip-close-05": dict(csv=sorted(TRIES05), frames=[], box=True, curated="tries05"),
    "2026-10-23-pick-place-demo-06": dict(csv=["motion.csv"], frames=[("frames", 0.0)], box=True, curated=run06),
}


# ---- signals and auto labels --------------------------------------------------------------------------------

def load(path):
    rows = [r for r in csv.DictReader(path.open()) if r.get("x") not in (None, "")]
    t = np.array([float(r["t"]) for r in rows])
    q = np.array([[float(r[f"F{i}"]) for i in range(5)] for r in rows])
    jaw = np.array([float(r["jaw_pct"]) if r.get("jaw_pct") not in (None, "") else np.nan for r in rows])
    tip = np.array([KIN.tip(x)[0] for x in q])
    return rows, t, tip, jaw


def smooth_rate(t, v, win=0.5):
    out = np.zeros(len(t))
    for i in range(len(t)):
        j0, j1 = np.searchsorted(t, t[i] - win / 2), np.searchsorted(t, t[i] + win / 2) - 1
        j1 = max(j1, j0 + 1) if j0 + 1 < len(t) else j0
        dt = t[j1] - t[j0]
        out[i] = 0.0 if dt <= 0 else (v[j1] - v[j0]) / dt
    return out


def auto_labels(t, tip, jaw):
    speed = np.linalg.norm(np.vstack([smooth_rate(t, tip[:, k]) for k in range(3)]).T, axis=1)
    vz = smooth_rate(t, tip[:, 2])
    vj = smooth_rate(t, np.nan_to_num(jaw), win=0.8)
    lab = []
    for i in range(len(t)):
        if vj[i] < -6:
            lab.append("grasp_close")
        elif vj[i] > 6:
            lab.append("release_open")
        elif speed[i] < 4:
            lab.append("idle")
        elif vz[i] < -10:
            lab.append("descend")
        elif vz[i] > 10:
            lab.append("lift")
        else:
            lab.append("transit")
    return lab


def debounce(labels, t, min_s=0.6):
    """Fold auto segments shorter than min_s into the one before: teleop jitter otherwise flickers the label."""
    out = list(labels)
    for a, b, p in runs_of(out, t):
        if b - a < min_s:
            i0, i1 = int(np.searchsorted(t, a)), int(np.searchsorted(t, b, side="right"))
            prev = out[i0 - 1] if i0 > 0 else (out[i1] if i1 < len(out) else p)
            for i in range(i0, i1):
                out[i] = prev
    return out


def runs_of(labels, t):
    out, i = [], 0
    while i < len(labels):
        j = i
        while j + 1 < len(labels) and labels[j + 1] == labels[i]:
            j += 1
        out.append((t[i], t[j], labels[i]))
        i = j + 1
    return out


def box_cols(p):
    rel = p - BOX.point("mon", 0, 0)
    behind, along, above = rel @ BOX.away, rel @ np.asarray(BOX.along), rel[2]
    k = int(np.clip(np.round(along / box.PITCH), -1, 5))  # 0 = Monday; -1 Sunday .. 5 Saturday
    day = box.DAYS[k + 1]
    return round(float(behind), 1), round(float(along - k * box.PITCH), 1), round(float(above), 1), day


# ---- curated helpers for runs without times in the README ---------------------------------------------------

def buttons_from_motion(t, wrist, table):
    """Each README press matched to the lowest point near its x,y. The README table is in the CSV's own x,y,z,
    which is the wrist-roll joint, not the jaw tips."""
    out = []
    for k, x, y in table:
        d = np.hypot(wrist[:, 0] - x, wrist[:, 1] - y)
        near = d < 8
        if not near.any():
            continue
        i = np.where(near)[0][np.argmin(wrist[near, 2])]
        j0, j1 = i, i
        while j0 > 0 and t[i] - t[j0] < 3 and d[j0 - 1] < 20:
            j0 -= 1
        while j1 + 1 < len(t) and t[j1] - t[i] < 3 and d[j1 + 1] < 20:
            j1 += 1
        out.append(seg(t[j0], t[j1], "tab_press", f"button {k} of 7", "unknown",
                       f"curated: README press table (button {k} at x {x}, y {y}) matched to the z minimum",
                       "order Sun..Sat along the box is inferred from y; whether each lid opened is not recorded"))
    return out


def tries05_segments(name, t, tip):
    """Per day: the bottom of the stroke near that lid is the press; the press ends once the claw has risen 15 mm;
    the swing starts where the claw was last behind the lid (>= 45 mm beyond the front edge); the approach is the
    6 s before the swing."""
    days, outcomes, note = TRIES05[name]
    out = []
    for d, oc in zip(days, outcomes):
        rel = tip - BOX.point(d, 0, 0)
        along, behind = rel @ np.asarray(BOX.along), rel @ BOX.away
        near = (np.abs(along) < 12) & (np.abs(behind) < 80)
        if not near.any():
            continue
        i = np.where(near)[0][np.argmin(tip[near, 2])]
        j1 = i
        while j1 + 1 < len(t) and tip[j1 + 1, 2] < tip[i, 2] + 15:
            j1 += 1
        k = i
        while k > 0 and behind[k] < 45 and t[i] - t[k] < 8:
            k -= 1
        a0 = int(np.searchsorted(t, t[k] - 6.0))
        out.append(seg(t[a0], t[k], "lid_approach", d, "", "curated: box frame (transit, hover, down behind the upright lid)"))
        out.append(seg(t[k], t[i], "lid_swing", d, "", "curated: box frame (arc about the hinge)"))
        out.append(seg(t[i], t[j1], "lid_press", d, oc, f"curated: run 05 README ({note})"))
    return out


# ---- writer -------------------------------------------------------------------------------------------------

def label_run(name, cfg):
    folder = ROOT / "runs" / name
    all_segs = []
    for csv_name in cfg["csv"]:
        path = folder / csv_name
        if not path.exists():  # e.g. run 05's aborted try was never copied in
            continue
        rows, t, tip, jaw = load(path)
        curated = []
        if callable(cfg["curated"]):
            got = cfg["curated"]()
            if got and isinstance(got[0], tuple) and got[0][0] == "press_table":
                wrist = np.array([[float(r["x"]), float(r["y"]), float(r["z"])] for r in rows])
                curated = buttons_from_motion(t, wrist, got[0][1])
            else:
                curated = got
        elif cfg["curated"] == "tries05":
            curated = tries05_segments(csv_name, t, tip)
        curated = sorted(curated, key=lambda s: s["t_start"])
        for prev, cur in zip(curated, curated[1:]):  # a later event starts where the earlier one ended
            if cur["t_start"] < prev["t_end"] and cur["t_end"] > prev["t_end"]:
                cur["t_start"] = prev["t_end"]
        auto = debounce(auto_labels(t, tip, jaw), t)
        phase = list(auto)
        for s in curated:
            for i in np.where((t >= s["t_start"]) & (t <= s["t_end"]))[0]:
                phase[i] = s["phase"]
        covered = np.zeros(len(t), bool)
        for s in curated:
            covered |= (t >= s["t_start"]) & (t <= s["t_end"])
        auto_segs = [seg(a, b, p, evidence="auto: jaw rate / tip speed rule") for a, b, p in
                     runs_of([p if not c else None for p, c in zip(auto, covered)], t) if p is not None and b - a >= 0.3]
        segs = sorted(curated + auto_segs, key=lambda s: s["t_start"])
        for s in segs:
            s["file"] = csv_name
        all_segs += segs

        stem = "motion" if csv_name == "motion.csv" else csv_name[:-4]
        out = folder / f"{stem}_labeled.csv"
        with out.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(list(rows[0].keys()) + ["tip_x", "tip_y", "tip_z", "box_behind", "box_along_off", "box_above",
                                               "nearest_day", "phase"])
            for r, p, ph in zip(rows, tip, phase):
                bc = box_cols(p) if cfg["box"] else ("", "", "", "")
                w.writerow(list(r.values()) + [round(float(v), 1) for v in p] + list(bc) + [ph])

        for sub, offset in cfg["frames"]:
            fdir = folder / sub
            if not fdir.exists():
                continue
            with (folder / f"frames_index_{sub}.csv" if len(cfg["frames"]) > 1 else folder / "frames_index.csv").open("w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["file", "t_frame", "t_motion_est", "phase"])
                for img in sorted(fdir.glob("*.jpg")):
                    tf = float(img.name[:-5])
                    tm = tf - offset - CAMERA_LAG_S
                    i = int(np.argmin(np.abs(t - tm))) if len(t) else 0
                    w.writerow([f"{sub}/{img.name}", tf, round(tm, 1), phase[i] if abs(t[i] - tm) < 1.5 else ""])

    with (folder / "labels.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["file"] + SEG_FIELDS)
        w.writeheader()
        for s in all_segs:
            w.writerow(s)
    cur = [s for s in all_segs if s["evidence"].startswith("curated")]
    print(f"{name}: {len(all_segs)} segments ({len(cur)} curated)")


if __name__ == "__main__":
    want = sys.argv[1:]
    for name, cfg in RUNS.items():
        if (ROOT / "runs" / name).exists() and (not want or any(w in name for w in want)):
            label_run(name, cfg)
