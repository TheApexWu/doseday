"""Pixels -> mat mm (ArUco homography) -> robot base mm (rigid touch-off).

Frames:
  image px  x right, y down.
  mat mm    origin at tag 0, +x toward tag 1, +y 90 deg counter-clockwise from +x SEEN FROM ABOVE
            (right-handed with z up, same handedness as the robot base). Lay tag 3 accordingly;
            a mirrored mat shows up as a large residual on a third touch point.
  robot mm  Viam world frame, TCP (gripper frame), not the flange.

The homography is valid only for the exact photo pose it was fitted at, so the photo pose is saved
with it and demo.py refuses to use the calibration from anywhere else.
"""
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import cv2
import numpy as np

LIMIT_MM = 3.0
DICT = cv2.aruco.DICT_4X4_50
# Default 5-tag layout for an A3-ish mat; tag 4 makes the homography residual mean something
# (4 points fit a homography exactly, so a 4-tag residual is 0 by construction).
DEFAULT_LAYOUT = {0: (0.0, 0.0), 1: (300.0, 0.0), 2: (300.0, 200.0), 3: (0.0, 200.0), 4: (150.0, 0.0)}


class CalibrationError(RuntimeError):
    pass


def detect_tags(img: np.ndarray, dictionary: int = DICT) -> dict[int, tuple[float, float]]:
    """Tag id -> centre px. Centres, not corners, so tag rotation on the mat does not matter."""
    gray = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    det = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(dictionary), cv2.aruco.DetectorParameters())
    corners, ids, _ = det.detectMarkers(gray)
    if ids is None:
        return {}
    return {int(i): tuple(c.reshape(4, 2).mean(axis=0).tolist()) for i, c in zip(ids.flatten(), corners)}


def tag_sides(img: np.ndarray, dictionary: int = DICT) -> dict[int, float]:
    """Tag id -> black-square side in px (mean edge length)."""
    gray = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    det = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(dictionary), cv2.aruco.DetectorParameters())
    corners, ids, _ = det.detectMarkers(gray)
    if ids is None:
        return {}
    out = {}
    for i, c in zip(ids.flatten(), corners):
        q = c.reshape(4, 2)
        out[int(i)] = float(np.mean(np.linalg.norm(q - np.roll(q, 1, axis=0), axis=1)))
    return out


def tag_mask(img_shape, tags: dict, radius: float = 40.0, sides: dict | None = None) -> np.ndarray:
    """Mask out tag areas so vision.detect does not read a tag as a pill.
    With sides, each circle scales to that tag: on black paper the tag's white margin is bright, and a
    fixed 40 px circle left its corners showing as pills once the tag was larger than ~55 px.
    1.2 x side covers the printed sheet's ~11 mm margin around a 45 mm tag, cut on the dashed line."""
    m = np.zeros(img_shape[:2], np.uint8)
    for i, (x, y) in tags.items():
        r = 1.2 * sides[i] if sides and i in sides else radius
        cv2.circle(m, (int(x), int(y)), int(r), 255, -1)
    return m


def outside_mat(img_shape, tags: dict, corners=(0, 1, 2, 3)) -> np.ndarray | None:
    """Mask of everything outside the quad of corner tags, so the organizer, hands or table beside
    the mat are never pick targets. None when a corner tag is not seen (no safe quad to draw)."""
    if not all(c in tags for c in corners):
        return None
    m = np.full(img_shape[:2], 255, np.uint8)
    quad = np.array([tags[c] for c in corners], np.int32)
    cv2.fillConvexPoly(m, cv2.convexHull(quad), 0)
    return m


def apply_h(H: np.ndarray, pts) -> np.ndarray:
    pts = np.asarray(pts, np.float64).reshape(-1, 1, 2)
    return cv2.perspectiveTransform(pts, H).reshape(-1, 2)


def fit_homography(tags_px: dict, layout: dict = DEFAULT_LAYOUT) -> tuple[np.ndarray, dict]:
    """px -> mat mm. Returns H and per-tag reprojection error in mm."""
    ids = sorted(set(tags_px) & set(layout))
    if len(ids) < 4:
        raise CalibrationError(f"need 4 known tags, saw {sorted(tags_px)}")
    src = np.array([tags_px[i] for i in ids], np.float64)
    dst = np.array([layout[i] for i in ids], np.float64)
    H, _ = cv2.findHomography(src, dst, 0)
    err = np.linalg.norm(apply_h(H, src) - dst, axis=1)
    return H, {i: float(e) for i, e in zip(ids, err)}


def fit_rigid(mat_pts, robot_pts) -> tuple[float, np.ndarray, np.ndarray]:
    """Mat mm -> robot XY as rotation + translation (no scale, no mirror).
    2D Kabsch; returns (theta_deg, t, per-point residual mm). With 2 points the residual is
    half the span mismatch, which still catches a bad touch."""
    A, B = np.asarray(mat_pts, float), np.asarray(robot_pts, float)
    if len(A) < 2:
        raise CalibrationError("touch-off needs at least 2 points")
    ca, cb = A.mean(0), B.mean(0)
    Hm = (A - ca).T @ (B - cb)
    th = np.arctan2(Hm[0, 1] - Hm[1, 0], Hm[0, 0] + Hm[1, 1])
    R = np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]])
    t = cb - R @ ca
    res = np.linalg.norm((A @ R.T + t) - B, axis=1)
    return float(np.degrees(th)), t, res


@dataclass
class Calibration:
    H: list                      # 3x3 px -> mat mm
    theta_deg: float             # mat -> robot rotation about z
    t: list                      # mat -> robot translation, mm
    table_z: float               # TCP z touching the mat surface
    photo_pose: dict             # the pose H is valid at
    tag_err_mm: dict = field(default_factory=dict)
    touch_res_mm: list = field(default_factory=list)
    mat_only: bool = False       # tags only: real mm on the mat, no robot frame (no arm needed)

    def _R(self):
        th = np.radians(self.theta_deg)
        return np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]])

    def px_to_mat(self, pts) -> np.ndarray:
        return apply_h(np.array(self.H), pts)

    def mat_to_robot(self, pts) -> np.ndarray:
        return np.asarray(pts, float).reshape(-1, 2) @ self._R().T + np.array(self.t)

    def px_to_robot(self, pts) -> np.ndarray:
        return self.mat_to_robot(self.px_to_mat(pts))

    def axis_yaw_deg(self, p1_px, p2_px) -> float:
        """Long axis in the robot frame, degrees CCW from robot +x seen from above, in [0, 180).
        Maps both endpoints instead of adding angles, so the image's y-down flip and any
        perspective skew are handled by the same transform as the position."""
        a, b = self.px_to_robot([p1_px, p2_px])
        return float(np.degrees(np.arctan2(b[1] - a[1], b[0] - a[0]))) % 180.0

    def save(self, path):
        Path(path).write_text(json.dumps(asdict(self), indent=2))

    @classmethod
    def load(cls, path) -> "Calibration":
        d = json.loads(Path(path).read_text())
        d["tag_err_mm"] = {int(k): v for k, v in d.get("tag_err_mm", {}).items()}
        return cls(**d)


def build(img, layout, touches: list[tuple[tuple, tuple]], table_z: float, photo_pose: dict,
          limit_mm: float = LIMIT_MM) -> Calibration:
    """touches: [(mat_xy, robot_xy), ...] from jogging the TCP onto tag centres. Refuses over limit."""
    tags = detect_tags(img)
    H, tag_err = fit_homography(tags, layout)
    if max(tag_err.values()) > limit_mm:
        raise CalibrationError(f"homography residual {tag_err} mm exceeds {limit_mm}")
    th, t, res = fit_rigid([m for m, _ in touches], [r for _, r in touches])
    if res.max() > limit_mm:
        raise CalibrationError(f"touch-off residual {res.round(2).tolist()} mm exceeds {limit_mm}; re-touch")
    return Calibration(H=H.tolist(), theta_deg=th, t=t.tolist(), table_z=table_z, photo_pose=photo_pose,
                       tag_err_mm=tag_err, touch_res_mm=res.tolist())


def residual_check(cal: Calibration, px_pts, robot_measured, limit_mm: float = LIMIT_MM) -> np.ndarray:
    """T1: predicted robot XY for crosshairs seen in the image vs where the TCP actually touched them.
    Raises when any miss exceeds limit_mm; returns the misses otherwise."""
    err = np.linalg.norm(cal.px_to_robot(px_pts) - np.asarray(robot_measured, float).reshape(-1, 2), axis=1)
    if err.max() > limit_mm:
        raise CalibrationError(f"calibration miss {err.round(2).tolist()} mm, limit {limit_mm}")
    return err


def build_mat_only(img, layout, limit_mm: float = LIMIT_MM) -> Calibration:
    """Pixels -> mat mm from the tags alone. Enough for sizing, ID and assist mode; the robot
    frame is identity, so live picking refuses it."""
    tags = detect_tags(img)
    H, tag_err = fit_homography(tags, layout)
    if max(tag_err.values()) > limit_mm:
        raise CalibrationError(f"homography residual {tag_err} mm exceeds {limit_mm}")
    return Calibration(H=H.tolist(), theta_deg=0.0, t=[0.0, 0.0], table_z=0.0, photo_pose={},
                       tag_err_mm=tag_err, mat_only=True)
