import numpy as np
import pytest

import vision
from synth import CAPSULE_C, OVAL_C, capsule, ellipse, mat, scene
from vision import axis_diff, detect

MAX_ERR = 10.0


def one(img):
    pills = detect(img)
    assert len(pills) == 1, f"expected 1 pill, got {len(pills)}"
    return pills[0]


@pytest.mark.parametrize("angle", range(0, 180, 15))
def test_ellipse_angle_light_on_black(angle):
    img = mat(kind="black", noise=3)
    ellipse(img, 320, 240, 60, 24, angle, OVAL_C)
    p = one(img)
    assert axis_diff(p.angle_deg, angle) < MAX_ERR
    assert axis_diff(p.angle_moments_deg, angle) < MAX_ERR
    assert not p.round and p.zone == "dark"


@pytest.mark.parametrize("angle", range(5, 180, 20))
def test_capsule_angle_dark_on_white(angle):
    img = mat(kind="white", noise=3)
    capsule(img, 300, 260, 56, 20, angle, CAPSULE_C)
    p = one(img)
    assert axis_diff(p.angle_deg, angle) < MAX_ERR
    assert p.zone == "light"


def test_convention_ground_truth():
    """Check the axis against pixels, not against cv2.ellipse's own angle convention:
    25 px along the reported axis must be pill, 25 px along its y-up mirror must be mat."""
    img = mat(kind="black")
    ellipse(img, 320, 240, 70, 20, 30, OVAL_C)
    p = one(img)
    a = np.radians(p.angle_deg)
    on = img[int(round(p.cy + 25 * np.sin(a))), int(round(p.cx + 25 * np.cos(a)))]
    mirrored = np.radians(180 - p.angle_deg)
    off = img[int(round(p.cy + 25 * np.sin(mirrored))), int(round(p.cx + 25 * np.cos(mirrored)))]
    assert on.mean() > 200 and off.mean() < 50


def test_wrong_convention_would_fail():
    """Negative control for the angle tests: a y-up atan2 (180 - angle) must miss the threshold,
    otherwise the angle tests above cannot tell the two conventions apart."""
    img = mat(kind="black")
    ellipse(img, 320, 240, 60, 24, 30, OVAL_C)
    p = one(img)
    assert axis_diff(p.angle_deg, 30) < MAX_ERR
    assert axis_diff(180 - p.angle_deg, 30) > MAX_ERR


def test_round_flag():
    img = mat(kind="black")
    ellipse(img, 150, 240, 30, 30, 0, OVAL_C)   # disc
    ellipse(img, 320, 240, 32, 30, 40, OVAL_C)  # aspect 1.07: still round
    ellipse(img, 500, 240, 60, 30, 40, OVAL_C)  # aspect 2
    pills = sorted(detect(img), key=lambda p: p.cx)
    assert [p.round for p in pills] == [True, True, False]
    assert pills[0].angle_deg is None and pills[2].angle_deg is not None


def test_merged_flag():
    img = mat(kind="black")
    for x in (80, 200, 320, 440):
        ellipse(img, x, 100, 60, 24, 0, OVAL_C)
    ellipse(img, 300, 300, 60, 24, 0, OVAL_C)
    ellipse(img, 300, 320, 60, 24, 0, OVAL_C)
    pills = detect(img)
    assert len(pills) == 5
    merged = [p for p in pills if p.merged]
    assert len(merged) == 1 and abs(merged[0].cy - 310) < 5


def test_split_mat_finds_both_polarities_and_no_seam():
    img, truth = scene()
    pills = detect(img)
    # 3 ovals + merged pair + 2 capsules + blue = 7 blobs; the seam at x=320 must add none
    assert len(pills) == 7
    assert all(abs(p.cx - 320) > 15 for p in pills)
    assert sum(p.zone == "dark" for p in pills) == 4
    for x, y, a in truth["capsules"] + truth["ovals"]:
        p = min(pills, key=lambda q: np.hypot(q.cx - x, q.cy - y))
        assert axis_diff(p.angle_deg, a) < MAX_ERR


def test_empty_noisy_mat_has_no_pills():
    assert detect(mat(kind="split", noise=8)) == []


def test_dark_pill_on_black_is_invisible():
    """Documents the known limit: dark capsules must go on the white half."""
    img = mat(kind="black")
    capsule(img, 320, 240, 56, 20, 30, (35, 35, 45))  # near-black capsule
    assert detect(img) == []
    img = mat(kind="white")
    capsule(img, 320, 240, 56, 20, 30, (35, 35, 45))  # same capsule on the white half
    assert len(detect(img)) == 1


def test_angle_disagree_flag_off_for_clean_pill():
    img = mat(kind="black")
    ellipse(img, 320, 240, 60, 24, 70, OVAL_C)
    assert not one(img).angle_disagree
    assert vision.axis_diff(179, 1) == 2
