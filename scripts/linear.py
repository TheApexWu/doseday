"""Straight-line claw-tip moves with the claw locked at a fixed angle to the base (heading = wrist roll - pan).

Joint-space moves between two poses curve and twist the claw as the base turns; demo-04's hand kept the claw at
heading -110 (+-5) for every drop and press, so moves near the box are planned as straight lines at that heading.
"""
import numpy as np

# calibrated servo ranges (follower get_calibration, 24 Oct), deg = (raw - 2047) * 360 / 4095. The module clamps
# targets to these, not to the kinematics file's limits: elbow 819..2445 = -108..35 matches its clamp warnings.
CAL_RAW = [(747, 3308), (855, 3220), (912, 3106), (814, 3071), (155, 3970)]  # new white arm swapped in 24 Oct ~17:10 (old: (811,3340),(1319,3230),(819,2445),(997,3211),(0,4095))
CAL_LIMITS = [((lo - 2047) * 360 / 4095, (hi - 2047) * 360 / 4095) for lo, hi in CAL_RAW]


def calibrated(kin):
    """Tighten the planner's limits to the servos' calibrated ranges."""
    kin.limits = [(max(a, c), min(b, d)) for (a, b), (c, d) in zip(kin.limits, CAL_LIMITS)]
    return kin


BOX_HEADING = -110.0   # demo-04 drops and lid presses, all within +-5
STEP_MM = 5.0


def ik(kin, tip, seed, heading, leans=(0, 5, 10, 15, 20, 30, 40), flip=False):
    """Jaws are symmetric, so a heading and the same heading +-180 grip identically; the closest to the seed's
    wrist that stays inside the limits wins."""
    err = None
    flips = sorted((heading, heading + 180.0, heading - 180.0), key=lambda h: abs((seed[0] + h) - seed[4])) if flip else [heading]
    for lean in leans:
        for h in flips:
            try:
                return kin.ik(tip, float(lean), seed, heading=h)
            except ValueError as e:
                err = e
    raise ValueError(f"no reach at {np.round(tip, 1).tolist()}: {err}")


def line(kin, a, b, seed, heading, leans=(0, 5, 10, 15, 20, 30, 40), flip=False):
    """Joint waypoints moving the tip from a to b in a straight line, one every STEP_MM."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    n = max(1, int(np.ceil(np.linalg.norm(b - a) / STEP_MM)))
    out, q = [], seed
    for s in np.linspace(0.0, 1.0, n + 1):
        q = ik(kin, list(a + (b - a) * s), q, heading, leans, flip)
        out.append(q)
    return out
