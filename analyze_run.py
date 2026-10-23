"""Score a recorded teleop run: per-second jaw, camera hold score and tip pose, plus transports to the drop area.

usage: python analyze_run.py <run_dir>     (run_dir holds motion.csv and frames/)
writes <run_dir>/per_second.csv and prints transports.

Hold score = share of strongly coloured or dark pixels in the gap between the jaw tips on the wrist camera.
Measured 23 Oct: empty jaws 0.00, held M&M 0.28-0.35. Above HOLD counts as candy between the jaws.
"""
import csv
import sys
from pathlib import Path

import cv2
import numpy as np

HOLD = 0.15
GAP = (slice(280, 400), slice(290, 390))  # rows, cols of the jaw-tip gap in a 640x480 wrist frame
PICK_MAX_X, DROP_MIN_X = 200, 250


def hold_score(img) -> float:
    hsv = cv2.cvtColor(img[GAP], cv2.COLOR_BGR2HSV)
    return float(((hsv[..., 1] > 90) | (hsv[..., 2] < 70)).mean())


def per_second(run: Path) -> list[dict]:
    rows = list(csv.DictReader(open(run / "motion.csv")))
    t = np.array([float(r["t"]) for r in rows])
    out = []
    for f in sorted((run / "frames").glob("*.jpg")):
        ts = float(f.stem.rstrip("s"))
        r = rows[int(np.argmin(abs(t - ts)))]
        out.append({"t": round(ts, 1), "jaw_pct": float(r["jaw_pct"]), "hold_score": round(hold_score(cv2.imread(str(f))), 2),
                    "x": float(r["x"]), "y": float(r["y"]), "z": float(r["z"]), "frame": f.name})
    return out


def transports(sec: list[dict]) -> list[dict]:
    """A transport starts at the last second in the pick area and ends at the first second in the drop area."""
    found, start = [], None
    for i, s in enumerate(sec):
        if s["x"] <= PICK_MAX_X:
            start = i
        elif s["x"] >= DROP_MIN_X and start is not None:
            carried = max(x["hold_score"] for x in sec[start:i]) if i > start else sec[start]["hold_score"]
            found.append({"from_t": sec[start]["t"], "to_t": s["t"], "carried": carried > HOLD, "max_hold": round(carried, 2)})
            start = None
    return found


if __name__ == "__main__":
    run = Path(sys.argv[1])
    sec = per_second(run)
    with open(run / "per_second.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(sec[0]))
        w.writeheader()
        w.writerows(sec)
    tr = transports(sec)
    for x in tr:
        print(f"{x['from_t']:6.1f}s -> {x['to_t']:6.1f}s  {'CARRIED' if x['carried'] else 'EMPTY  '}  max hold {x['max_hold']}")
    print(f"transports {len(tr)}, carried {sum(x['carried'] for x in tr)}")
