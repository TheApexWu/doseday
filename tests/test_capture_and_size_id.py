"""Arm-camera-only inputs, and telling apart pills that differ only slightly in size."""
import cv2
import pytest

import demo
import provenance
from pills import Registry, features, from_samples
from synth import OVAL_C, frames, scene
from vision import detect


def _write(dir_, imgs, source):
    dir_.mkdir(parents=True, exist_ok=True)
    for i, img in enumerate(imgs):
        p = dir_ / f"{i:02d}.png"
        cv2.imwrite(str(p), img)
        if source:
            provenance.write(p, source)


def test_phone_photo_is_refused(tmp_path):
    p = tmp_path / "IMG_0412.jpg"
    cv2.imwrite(str(p), scene()[0])
    with pytest.raises(SystemExit, match="REFUSED"):
        demo.main(["run", "--dry-run", "--image", str(p)])


def test_enrollment_refuses_synthetic_without_override(tmp_path):
    _write(tmp_path / "oval", frames(OVAL_C, 60, 24, n=3), provenance.SYNTHETIC)
    with pytest.raises(SystemExit, match="REFUSED"):
        demo.main(["enroll", "oval", "--dir", str(tmp_path / "oval"), "--pills", str(tmp_path / "p.json")])


def test_arm_frames_enroll_with_spread(tmp_path):
    _write(tmp_path / "oval", frames(OVAL_C, 60, 24, n=10), provenance.ARM)
    demo.main(["enroll", "oval", "--dir", str(tmp_path / "oval"), "--pills", str(tmp_path / "p.json")])
    t = Registry.load(tmp_path / "p.json").types[0]
    assert t.n == 10 and len(t.size_std) == 2 and abs(t.size[0] - 60) < 3


def _feats(length, width, seed):
    return [features(detect(img)[0]) for img in frames(OVAL_C, length, width, n=10, seed=seed)]


def test_same_colour_pills_7pct_apart_are_separated(tmp_path):
    """60x24 vs 64x25.5 px: ~1.4 mm apart at 0.35 mm/px, identical colour."""
    _write(tmp_path / "data" / "small", frames(OVAL_C, 60, 24, seed=1), provenance.ARM)
    _write(tmp_path / "data" / "big", frames(OVAL_C, 64, 25.5, seed=2), provenance.ARM)
    tally = demo.main(["loo", "--data", str(tmp_path / "data")])
    assert tally["wrong"] == 0
    assert tally["correct"] >= 19


def test_one_sample_enrollment_cannot_separate_them():
    """Negative control: the fixed-scale fallback (n=1) is too coarse for a 7% size gap."""
    small, big = _feats(60, 24, 1), _feats(64, 25.5, 2)
    reg = Registry([from_samples("small", small[:1], "px"), from_samples("big", big[:1], "px")])
    got = [reg.classify(*f)[0] for f in small[1:] + big[1:]]
    correct = sum(g == "small" for g in got[:9]) + sum(g == "big" for g in got[9:])
    assert correct / len(got) < 0.95  # fails the T-ID bar that 10-frame enrollment passes
