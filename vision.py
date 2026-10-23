"""Find pills on a two-zone mat (black half for light pills, white half for dark ones).

Angle convention, used everywhere in this file: image pixels, x right, y DOWN, degrees in [0, 180).
So +30 deg points right-and-down on screen. Never compare these numbers to robot yaw directly:
calib.Calibration.axis_yaw_deg maps the axis endpoints through the homography instead.
"""
from dataclasses import dataclass, field

import cv2
import numpy as np

ROUND_ASPECT = 1.15   # below this a pill has no long axis worth rotating for
MERGED_RATIO = 1.6    # blob area over a single pill's area that means "touching pills"
ANGLE_DISAGREE_DEG = 15.0


@dataclass
class Pill:
    id: int
    cx: float
    cy: float
    area_px: float
    aspect: float
    angle_deg: float | None          # long axis, image convention; None when round
    angle_moments_deg: float | None  # second-moment axis, the cross-check
    round: bool
    merged: bool
    zone: str                        # "dark" bg (light pill) or "light" bg (dark pill)
    lab: tuple                       # mean colour, OpenCV 8-bit Lab
    axis_px: tuple                   # ((x1, y1), (x2, y2)) long-axis endpoints
    box_px: list = field(default_factory=list)

    @property
    def angle_disagree(self) -> bool:
        if self.round or self.angle_deg is None or self.angle_moments_deg is None:
            return False
        return axis_diff(self.angle_deg, self.angle_moments_deg) > ANGLE_DISAGREE_DEG


def axis_diff(a: float, b: float) -> float:
    """Difference between two undirected axes: 179 and 1 are 2 apart."""
    d = abs(a - b) % 180.0
    return min(d, 180.0 - d)


def find_split(gray: np.ndarray, min_contrast: float = 60.0):
    """Column where the mat switches black/white, or None for a single-colour mat.
    Column medians ignore the pills because pills cover a small fraction of each column."""
    col = np.median(gray, axis=0).astype(float)
    w = col.size
    left, right = np.median(col[: w // 2]), np.median(col[w // 2:])
    if abs(left - right) < min_contrast:
        return None, float(np.median(gray)), float(np.median(gray))
    mid = (left + right) / 2
    above = col > mid
    flips = np.flatnonzero(above[1:] != above[:-1])
    split = int(flips[np.argmin(np.abs(flips - w // 2))]) + 1 if flips.size else w // 2
    return split, float(left), float(right)


def segment(gray: np.ndarray, delta: float = 50.0, band: int = 8, ignore=None,
            bright: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Binary pill mask plus a per-pixel zone map (True = dark background).
    Polarity is per zone: on black only brighter pixels count, on white only darker ones,
    so a shadow on the black half or a glare spot on the white half is not a pill.
    bright = per-pixel max(B, G, R): on black, a saturated blue or red pill is dark in grey
    (pure blue ~29) but bright in its own channel, so the dark zone tests that instead."""
    split, left, right = find_split(gray)
    h, w = gray.shape
    bg = np.empty((h, w), np.float32)
    if split is None:
        bg[:] = left
    else:
        bg[:, :split], bg[:, split:] = left, right
    dark_bg = bg < 128
    g = gray.astype(np.float32)
    if bright is None:
        on_dark = g > bg + delta
    else:
        # Local background, not one median: a lamp makes black paper brighter on one side, and a
        # global threshold then reads the bright patch as pills. Opening with a kernel wider than
        # any pill erases the pills and keeps the paper's own brightness at each spot.
        v = bright.astype(np.uint8)
        k = max(31, (min(h, w) // 8) | 1)
        v_bg = cv2.morphologyEx(v, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
        v_bg = cv2.blur(v_bg, (k, k)).astype(np.float32)
        on_dark = v.astype(np.float32) > v_bg + delta
    mask = np.where(dark_bg, on_dark, g < bg - delta).astype(np.uint8) * 255
    if split is not None:
        mask[:, max(0, split - band): split + band] = 0  # the paper seam is not a pill
    if ignore is not None:
        mask[ignore > 0] = 0
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
    # close fills specular highlights inside glossy pills
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
    return mask, dark_bg


def long_axis(contour) -> tuple[float, float, float, tuple, np.ndarray]:
    """(angle_deg, long_len, short_len, center, box) from cv2.boxPoints.
    The minAreaRect angle field changed convention across OpenCV versions; the longest box
    edge measured with our own atan2 does not."""
    rect = cv2.minAreaRect(contour)
    box = cv2.boxPoints(rect)
    edges = [box[(i + 1) % 4] - box[i] for i in range(4)]
    lens = [float(np.hypot(*e)) for e in edges]
    i = int(np.argmax(lens))
    dx, dy = edges[i]
    angle = float(np.degrees(np.arctan2(dy, dx))) % 180.0
    return angle, max(lens), min(lens), rect[0], box


def moments_axis(m: dict) -> float | None:
    if m["m00"] == 0:
        return None
    return float(np.degrees(0.5 * np.arctan2(2 * m["mu11"], m["mu20"] - m["mu02"]))) % 180.0


def detect(img: np.ndarray, min_area: float = 80.0, delta: float = 50.0, single_area: float | None = None,
           ignore=None) -> list[Pill]:
    """All pill blobs in a BGR image. single_area (px) is the enrolled one-pill area; without it the
    median blob stands in, which fails if most blobs are clusters."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    mask, dark_bg = segment(gray, delta=delta, ignore=ignore, bright=img.max(axis=2))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    contours = [c for c in contours if cv2.contourArea(c) >= min_area]
    if not contours:
        return []
    areas = [cv2.contourArea(c) for c in contours]
    ref = single_area or float(np.median(areas))
    pills = []
    for i, (c, area) in enumerate(zip(contours, areas)):
        m = cv2.moments(c)
        cx, cy = m["m10"] / m["m00"], m["m01"] / m["m00"]
        angle, L, S, center, box = long_axis(c)
        aspect = L / max(S, 1e-6)
        is_round = aspect < ROUND_ASPECT
        u = np.array([np.cos(np.radians(angle)), np.sin(np.radians(angle))]) * L / 2
        axis = (tuple(np.array(center) - u), tuple(np.array(center) + u))
        # erode so the background's colour at the rim does not pull the mean
        pm = np.zeros(gray.shape, np.uint8)
        cv2.drawContours(pm, [c], -1, 255, -1)
        inner = cv2.erode(pm, np.ones((5, 5), np.uint8))
        bgr = cv2.mean(img, mask=inner if inner.any() else pm)[:3]
        lab = cv2.cvtColor(np.uint8([[bgr]]), cv2.COLOR_BGR2LAB)[0, 0]
        pills.append(Pill(
            id=i, cx=cx, cy=cy, area_px=float(area), aspect=float(aspect),
            angle_deg=None if is_round else angle,
            angle_moments_deg=None if is_round else moments_axis(m),
            round=is_round, merged=area > MERGED_RATIO * ref,
            zone="dark" if dark_bg[int(cy), int(cx)] else "light",
            lab=tuple(float(v) for v in lab), axis_px=axis, box_px=box.tolist()))
    return pills


def annotate(img: np.ndarray, pills: list[Pill], labels: dict | None = None) -> np.ndarray:
    out = img.copy()
    for p in pills:
        colour = (0, 0, 255) if p.merged else (0, 200, 255) if p.round else (0, 255, 0)
        cv2.drawContours(out, [np.int32(p.box_px)], -1, colour, 2)
        if not p.round:
            a, b = p.axis_px
            cv2.line(out, tuple(map(int, a)), tuple(map(int, b)), (255, 0, 255), 2)
        text = f"{p.id}:{(labels or {}).get(p.id, '')}"
        cv2.putText(out, text, (int(p.cx) + 8, int(p.cy) - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
    return out
