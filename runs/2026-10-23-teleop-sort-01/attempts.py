"""Per-attempt features for run 01, hits against misses.

usage: python attempts.py      (from this folder)
Hit/miss labels were read by hand from the 1 Hz wrist frames: a hit is candy seen between the lifted jaws or
arriving at the drop area. Features come from motion.csv at the close onset; the candy blob is from the last
frame at or before onset. With 6 hits and 11 misses, a permutation p under ~0.05 is the least worth reading.
"""
import csv
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).parent
# close onset s, close end s, 1 = hit, candy colour
ATTEMPTS = [(27.3, 30.9, 1, "blue"), (35.6, 37.4, 0, "dark"), (38.8, 42.0, 1, "dark"), (46.3, 49.0, 0, "red"),
            (50.7, 52.7, 0, "red"), (54.0, 55.1, 0, "yellow"), (56.7, 57.9, 0, "yellow"), (58.9, 61.4, 1, "yellow"),
            (66.1, 69.0, 1, "red"), (72.2, 75.0, 1, "dark"), (76.8, 77.5, 0, "blue"), (81.2, 81.5, 1, "dark"),
            (86.5, 87.7, 0, "yellow"), (95.0, 97.3, 0, "blue"), (98.5, 99.0, 0, "yellow"), (100.0, 100.7, 0, "yellow"),
            (101.7, 104.2, 0, "yellow")]


def blob_x(img):
    """Column of the coloured or dark blob nearest the jaw gap, in a 640-wide frame (fixed jaw edge ~295)."""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    m = np.zeros(hsv.shape[:2], np.uint8)
    m[180:430, 270:520] = ((hsv[180:430, 270:520, 1] > 90) | (hsv[180:430, 270:520, 2] < 70))
    n, _, st, cen = cv2.connectedComponentsWithStats(m)
    near = [k for k in range(1, n) if st[k, 4] >= 400]
    return min((cen[k] for k in near), key=lambda c: np.hypot(c[0] - 340, c[1] - 340))[0] if near else np.nan


def main():
    rows = list(csv.DictReader(open(HERE / "motion.csv")))
    a = {k: np.array([float(r[k]) for r in rows]) for k in rows[0]}
    t, p = a["t"], np.c_[a["x"], a["y"], a["z"]]
    frames = sorted((HERE / "frames").glob("*.jpg"))
    ft = np.array([float(f.stem.rstrip("s")) for f in frames])
    out = []
    for ts, te, hit, colour in ATTEMPTS:
        s, e = (int(np.argmin(abs(t - x))) for x in (ts, te))
        m = s + int(np.argmin(a["jaw_pct"][s:e + 1]))
        b = int(np.argmin(abs(t - (t[s] - 0.5))))
        img = cv2.imread(str(frames[np.where(ft <= ts + 0.15)[0][-1]]))
        out.append({"t": ts, "hit": hit, "colour": colour, "jaw_open": a["jaw_pct"][s], "jaw_min": a["jaw_pct"][m],
                    "z_onset": p[s, 2], "z_min": p[s:m + 1, 2].min(), "v_xy": np.linalg.norm(p[s, :2] - p[b, :2]) / (t[s] - t[b]),
                    "v_z": (p[s, 2] - p[b, 2]) / (t[s] - t[b]), "pitch": a["F3"][s], "roll": a["F4"][s],
                    "x": p[s, 0], "y": p[s, 1], "blob_col": blob_x(img)})
    for o in out:
        print("  ".join(f"{k} {v:.1f}" if isinstance(v, float) else f"{k} {v}" for k, v in o.items()))
    rng = np.random.default_rng(1)
    for k in [k for k in out[0] if k not in ("t", "hit", "colour")]:
        h = np.array([o[k] for o in out if o["hit"]])
        mi = np.array([o[k] for o in out if not o["hit"]])
        d, both = h.mean() - mi.mean(), np.r_[h, mi]
        perm = [abs((q := rng.permutation(both))[:len(h)].mean() - q[len(h):].mean()) >= abs(d) for _ in range(5000)]
        print(f"{k:9s} hit {h.mean():6.1f} [{h.min():6.1f},{h.max():6.1f}]  miss {mi.mean():6.1f} "
              f"[{mi.min():6.1f},{mi.max():6.1f}]  p={np.mean(perm):.2f}")


if __name__ == "__main__":
    main()
