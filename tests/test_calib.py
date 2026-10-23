import cv2
import numpy as np
import pytest

from calib import (DEFAULT_LAYOUT, DICT, Calibration, CalibrationError, apply_h, build, detect_tags,
                   fit_homography, fit_rigid, residual_check)

PX_PER_MM, MARGIN_MM, TAG_MM = 2.0, 40.0, 30.0


def mat_to_canvas(pts):
    return (np.asarray(pts, float) + MARGIN_MM) * PX_PER_MM


def synthetic_view():
    """Tags drawn on a flat mat, then viewed through a known perspective warp.
    Returns the camera image and the true camera-px -> mat-mm homography."""
    w = int((300 + 2 * MARGIN_MM) * PX_PER_MM)
    h = int((200 + 2 * MARGIN_MM) * PX_PER_MM)
    canvas = np.full((h, w), 230, np.uint8)
    d = cv2.aruco.getPredefinedDictionary(DICT)
    side = int(TAG_MM * PX_PER_MM)
    for i, mm in DEFAULT_LAYOUT.items():
        cx, cy = mat_to_canvas([mm])[0]
        tag = cv2.aruco.generateImageMarker(d, i, side)
        tag = cv2.copyMakeBorder(tag, 8, 8, 8, 8, cv2.BORDER_CONSTANT, value=255)
        x0, y0 = int(cx - tag.shape[1] / 2), int(cy - tag.shape[0] / 2)
        canvas[y0:y0 + tag.shape[0], x0:x0 + tag.shape[1]] = tag
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    dst = np.float32([[90, 60], [930, 30], [980, 700], [40, 650]])  # mild keystone
    P = cv2.getPerspectiveTransform(src, dst)
    img = cv2.warpPerspective(canvas, P, (1024, 768), borderValue=230)
    S = np.array([[PX_PER_MM, 0, MARGIN_MM * PX_PER_MM], [0, PX_PER_MM, MARGIN_MM * PX_PER_MM], [0, 0, 1]])
    true_px_to_mm = np.linalg.inv(P @ S)
    return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR), true_px_to_mm


def test_tags_detected():
    img, _ = synthetic_view()
    assert set(detect_tags(img)) == set(DEFAULT_LAYOUT)


def test_homography_round_trip_under_1mm():
    img, true_H = synthetic_view()
    H, tag_err = fit_homography(detect_tags(img))
    assert max(tag_err.values()) < 1.0
    rng = np.random.default_rng(0)
    mm = rng.uniform([0, 0], [300, 200], (200, 2))
    px = apply_h(np.linalg.inv(true_H), mm)
    err = np.linalg.norm(apply_h(H, px) - mm, axis=1)
    assert err.max() < 1.0, err.max()


def test_homography_control_detects_wrong_layout():
    """Same image, tag 4 declared 20 mm off: the 5th tag must show up in the residual."""
    img, _ = synthetic_view()
    bad = {**DEFAULT_LAYOUT, 4: (170.0, 0.0)}
    _, tag_err = fit_homography(detect_tags(img), bad)
    assert max(tag_err.values()) > 3.0


def rigid(pts, deg, t):
    th = np.radians(deg)
    R = np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]])
    return np.asarray(pts, float) @ R.T + t


def test_fit_rigid_recovers_pose():
    mat = [(0, 0), (300, 0), (300, 200)]
    th, t, res = fit_rigid(mat, rigid(mat, 37.0, (250, -120)))
    assert abs(th - 37.0) < 1e-6 and np.allclose(t, (250, -120)) and res.max() < 1e-6


def test_mirrored_mat_is_caught_by_third_touch():
    mat = np.array([(0, 0), (300, 0), (300, 200)], float)
    robot = rigid(mat * [1, -1], 10, (200, 0))  # mat laid face-down / y axis flipped
    _, _, res = fit_rigid(mat, robot)
    assert res.max() > 3.0


def make_cal(img, deg=90.0, t=(250.0, -100.0)):
    touches = [(DEFAULT_LAYOUT[i], tuple(rigid([DEFAULT_LAYOUT[i]], deg, t)[0])) for i in (0, 1, 2)]
    return build(img, DEFAULT_LAYOUT, touches, table_z=12.0, photo_pose={"x": 300, "y": 0, "z": 400})


def test_build_refuses_bad_touch():
    img, _ = synthetic_view()
    good = make_cal(img)
    assert max(good.touch_res_mm) < 0.01
    # two touches 308 mm apart for tags 300 mm apart: a span error is caught
    touches = [(DEFAULT_LAYOUT[0], (250.0, -100.0)), (DEFAULT_LAYOUT[1], (558.0, -100.0))]
    with pytest.raises(CalibrationError):
        build(img, DEFAULT_LAYOUT, touches, 12.0, {})


def test_two_touches_miss_a_sideways_error():
    """Why demo.py defaults to three touches: an 8 mm sideways miss on tag 1 only rotates the
    fit, and two points cannot see it."""
    img, _ = synthetic_view()
    touches = [(DEFAULT_LAYOUT[0], (250.0, -100.0)), (DEFAULT_LAYOUT[1], (550.0, -92.0))]
    cal = build(img, DEFAULT_LAYOUT, touches, 12.0, {})
    assert max(cal.touch_res_mm) < 0.5
    three = touches + [(DEFAULT_LAYOUT[2], tuple(rigid([DEFAULT_LAYOUT[2]], 0.0, (250.0, -100.0))[0]))]
    with pytest.raises(CalibrationError):
        build(img, DEFAULT_LAYOUT, three, 12.0, {})


def test_residual_check_passes_and_refuses():
    img, true_H = synthetic_view()
    cal = make_cal(img)
    mm = np.array([(50, 50), (150, 100), (250, 150), (60, 180), (280, 20)], float)
    px = apply_h(np.linalg.inv(true_H), mm)
    robot = rigid(mm, 90.0, (250.0, -100.0))
    assert residual_check(cal, px, robot).max() < 1.0
    robot_bad = robot.copy()
    robot_bad[2] += (4.0, 0.0)
    with pytest.raises(CalibrationError):
        residual_check(cal, px, robot_bad)


def test_axis_yaw_goes_through_both_transforms():
    """A pill axis at 20 deg in the mat frame, mat rotated 90 deg on the robot, must read 110."""
    img, true_H = synthetic_view()
    cal = make_cal(img, deg=90.0)
    c = np.array([150.0, 100.0])
    u = np.array([np.cos(np.radians(20)), np.sin(np.radians(20))]) * 15
    p1, p2 = apply_h(np.linalg.inv(true_H), [c - u, c + u])
    assert abs(cal.axis_yaw_deg(p1, p2) - 110.0) < 1.0


def test_save_load(tmp_path):
    img, _ = synthetic_view()
    cal = make_cal(img)
    cal.save(tmp_path / "c.json")
    back = Calibration.load(tmp_path / "c.json")
    assert np.allclose(back.px_to_robot([(500, 400)]), cal.px_to_robot([(500, 400)]))
