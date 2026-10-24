"""The pill box as an obstacle for planned claw paths (arm frame, mm).

Geometry: closed lid tops z 28 and pitch 32.7 (HARDWARE-SETUP.md); open lids stand near-upright on a hinge ~40 mm
behind the front edge and are ~42 mm long (box.py). Placement today is inferred from demo-04: hand drops released at
x 190-214 and lid presses landed at x 205-227, so the front edge is taken at x 200; Sunday's centre y 80.8 and the
32.6 mm pitch come from the drop fit in script.json.
"""
import numpy as np

FRONT_X = 200.0
DEPTH = 40.0           # front edge to hinge
LID_TOP_Z = 28.0
OPEN_LID_TOP_Z = 72.0  # hinge height + ~42 mm upright lid
LID_THICK = 12.0       # slab the standing lids sweep through, behind the hinge line
SUN_Y, PITCH_Y = 80.8, -32.6
END_Y = (SUN_Y - PITCH_Y / 2, SUN_Y + 6 * PITCH_Y + PITCH_Y / 2)  # Sunday's outer edge, Saturday's outer edge
CLAW_R = 10.0          # jaw half-width
JAW_LEN = 98.0


def volumes(lids_open=True):
    y_hi, y_lo = max(END_Y), min(END_Y)
    vols = {"box body": ((FRONT_X, y_lo, -20.0), (FRONT_X + DEPTH, y_hi, LID_TOP_Z))}
    if lids_open:
        vols["open lids"] = ((FRONT_X + DEPTH - 2, y_lo, LID_TOP_Z), (FRONT_X + DEPTH + LID_THICK, y_hi, OPEN_LID_TOP_Z))
    return vols


def _dist(p, lo, hi):
    """Distance from point p to an axis-aligned box (0 inside)."""
    d = np.maximum(np.maximum(np.asarray(lo) - p, 0.0), p - np.asarray(hi))
    return float(np.linalg.norm(d))


def clearance(kin, q, lids_open=True):
    """Smallest gap (mm) between the claw (wrist joint to jaw tip, CLAW_R thick) and the box, and which part."""
    m = kin.wrist(q)
    o, axis = m[:3, 3], m[:3, 2]
    best = (1e9, "")
    for s in np.linspace(0.0, JAW_LEN, 15):
        p = o + s * axis
        for name, (lo, hi) in volumes(lids_open).items():
            g = _dist(p, lo, hi) - CLAW_R
            if g < best[0]:
                best = (g, name)
    return best


def check_path(kin, path, lids_open=True, allow_from=None):
    """Worst clearance along a joint path; points from index allow_from on may touch (an intended contact)."""
    worst = (1e9, "", -1)
    for i, q in enumerate(path):
        if allow_from is not None and i >= allow_from:
            break
        g, name = clearance(kin, q, lids_open)
        if g < worst[0]:
            worst = (g, name, i)
    return worst
