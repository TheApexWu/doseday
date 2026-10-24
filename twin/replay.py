"""Replay day 1's recordings in the twin: the arm follows the recorded follower joints and jaw, lids and pills move
by physics.

    python twin/replay.py lids          run 05: does the twin's lid shut where the real one did (12 strokes),
                                        and stay put where the real claw missed it (tries 1-2)?
    python twin/replay.py video RUN_CSV T0 T1 OUT.mp4 [CAMERAS]   a clip, e.g. for the demo video
"""
from __future__ import annotations

import csv
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("MUJOCO_GL", "cgl")
import mujoco  # noqa: E402
import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import box  # noqa: E402
from twin import scene  # noqa: E402
from twin.rehearse import OUT, Runner  # noqa: E402
from twin.scene import Twin  # noqa: E402

RUN05 = ROOT / "runs" / "2026-10-23-lid-flip-close-05"
# README try table: tries 1 and 2 never met the lid; from try 3 on every stroke swung it shut (latched or not).
MISSED = {"teleop-184017.csv", "teleop-184415.csv"}
SWUNG_DEG, UNTOUCHED_DEG = 10.0, 5.0


def load(path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rows = list(csv.DictReader(Path(path).open()))
    t = np.array([float(r["t"]) for r in rows])
    q = np.array([[float(r[f"F{i}"]) for i in range(5)] for r in rows])
    jaw = np.array([float(r["jaw_pct"]) if r.get("jaw_pct") not in (None, "") else 0.0 for r in rows])
    return t, q, jaw


def replay(twin: Twin, path, t0=None, t1=None, lids_open=scene.OPEN_DEG, video=None, watch=()) -> dict:
    """Play a recording from t0 to t1. Returns each watched lid's angle trace (deg) at 50 Hz."""
    t, q, jaw = load(path)
    t0 = t[0] if t0 is None else t0
    t1 = t[-1] if t1 is None else t1
    twin.reset(lids_open)
    run = Runner(twin, video)
    dt = twin.model.opt.timestep
    trace = {d: [] for d in watch}
    k, now = 0, t0
    while now <= t1:
        qi = np.array([np.interp(now, t, q[:, j]) for j in range(5)])
        run.step(qi, float(np.interp(now, t, jaw)))
        if k % 20 == 0:
            for d in watch:
                trace[d].append(float(np.degrees(twin.data.qpos[twin.hinge[d]])))
        k += 1
        now += dt
    return {"trace": trace, "closest": run.clear}


def strokes05() -> list[dict]:
    out = []
    for r in csv.DictReader((RUN05 / "labels.csv").open()):
        if r["phase"] == "lid_swing":
            out.append({"file": r["file"], "day": r["target"], "t0": float(r["t_start"])})
        elif r["phase"] == "lid_press" and out and out[-1]["file"] == r["file"] and out[-1]["day"] == r["target"]:
            out[-1]["t1"] = float(r["t_end"])
    return out


def classify(tr: np.ndarray, deg: float) -> str:
    if tr.min() <= SWUNG_DEG:
        return "swung"
    return "untouched" if np.abs(tr - deg).max() < UNTOUCHED_DEG else "moved"


def calibrate(hinges=(26.0, 28.0, 30.0, 32.0, 34.0, 36.0), open_deg=(90.0, 100.0), margin=0.0, timestep=0.002,
              front=0.0):
    """Fit the lid's hinge line to run 05: 12 strokes swung the real lid shut, 2 never met it. `front` moves the
    lid's free edge (and the front wall) relative to the registered edge, making the lid hinge - front long."""
    table = []
    for h in hinges:
        twin = Twin(hinge=h, front=front, margin=margin)
        twin.model.opt.timestep = timestep
        for deg in open_deg:
            agree, detail = 0, []
            for s in strokes05():
                rep = replay(twin, RUN05 / s["file"], max(s["t0"] - 2.0, 0.0), s.get("t1", s["t0"] + 3.0) + 0.5,
                             lids_open=deg, watch=[s["day"]])
                got = classify(np.array(rep["trace"][s["day"]]), deg)
                expect = "untouched" if s["file"] in MISSED else "swung"
                agree += got == expect
                detail.append(got[0])
            table.append({"hinge": h, "front": front, "open_deg": deg, "agree": agree, "pattern": "".join(detail)})
            print(f"   front {front:+4.0f} hinge {h:4.0f} mm, lids at {deg:3.0f} deg: {agree}/14 agree  [{''.join(detail)}]",
                  flush=True)
    print("   (pattern: one letter per stroke in labels.csv order; s = swung, u = untouched, m = moved; truth uussssssssssss)")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "lid_calibration.json").write_text(json.dumps(table, indent=1))
    return table


def lids(open_deg=(90.0, 95.0, 100.0)):
    twin = Twin()
    results = {}
    for deg in open_deg:
        rows, agree = [], 0
        for s in strokes05():
            rep = replay(twin, RUN05 / s["file"], max(s["t0"] - 4.0, 0.0), s.get("t1", s["t0"] + 3.0) + 1.0,
                         lids_open=deg, watch=[s["day"]])
            tr = np.array(rep["trace"][s["day"]])
            expect = "untouched" if s["file"] in MISSED else "swung"
            got = classify(tr, deg)
            agree += got == expect
            rows.append({**s, "expect": expect, "twin": got, "min_deg": round(float(tr.min()), 1)})
        results[deg] = rows
        print(f"lids open at {deg:.0f} deg: twin agrees on {agree}/{len(rows)} strokes")
        for r in rows:
            flag = "" if r["twin"] == r["expect"] else "   <-- disagrees"
            print(f"   {r['file']} {r['day']}: real {r['expect']:9s} twin {r['twin']:9s} (lid min {r['min_deg']:5.1f}){flag}")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "replay_lids.json").write_text(json.dumps({str(k): v for k, v in results.items()}, indent=1))
    return results


def video(run_csv, t0, t1, out_mp4, cameras="box,wrist", lids_open=scene.OPEN_DEG, fps=30):
    import imageio.v2 as imageio
    from twin.render import Camera
    twin = Twin()
    names = cameras.split(",")
    frames = []
    replay(twin, run_csv, float(t0), float(t1), lids_open=lids_open, video=(Camera(twin), names, frames, fps))
    with imageio.get_writer(out_mp4, fps=fps, codec="libx264", quality=8, macro_block_size=8) as w:
        for views in frames:
            h = max(v.shape[0] for v in views)
            row = [np.pad(v, ((0, h - v.shape[0]), (0, 0), (0, 0))) for v in views]
            w.append_data(np.concatenate(row, axis=1))
    print(f"{out_mp4}: {len(frames)} frames")


if __name__ == "__main__":
    if sys.argv[1] == "lids":
        lids()
    elif sys.argv[1] == "calibrate":
        calibrate()
    elif sys.argv[1] == "calibrate-front":  # is the registered edge the lid's real front edge?
        for f in (0.0, -4.0, -8.0, -12.0):
            calibrate(hinges=(22.0, 25.0, 28.0, 31.0), open_deg=(85.0, 90.0), front=f)
    elif sys.argv[1] == "calibrate-fine":
        calibrate(hinges=(24.0, 25.0, 26.0, 27.0, 28.0, 29.0, 30.0), open_deg=(85.0, 88.0, 90.0, 92.0, 95.0))
    elif sys.argv[1] == "physics-check":  # does the clearance margin or the step size change the outcome?
        for m_, ts in ((0.03, 0.002), (0.0, 0.001), (0.03, 0.001)):
            print(f"margin {m_}, timestep {ts}:")
            calibrate(hinges=(28.0,), open_deg=(90.0,), margin=m_, timestep=ts)
    elif sys.argv[1] == "video":
        video(*sys.argv[2:])
