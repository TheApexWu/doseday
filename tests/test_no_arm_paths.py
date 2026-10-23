"""Everything that must work before (or without) an arm: capture, camera consistency, mat-only
calibration, assist mode."""
import json

import cv2
import numpy as np
import pytest

import capture
import demo
import provenance
from calib import Calibration, apply_h
from synth import OVAL_C, frames, scene
from test_calib import synthetic_view


def _frames_dir(tmp_path, name="src", n=4, **kw):
    d = tmp_path / name
    d.mkdir()
    for i, img in enumerate(frames(OVAL_C, 60, 24, n=n, **kw)):
        cv2.imwrite(str(d / f"{i:02d}.png"), img)
    return d


def test_capture_from_folder_writes_camera_sidecars(tmp_path):
    src = _frames_dir(tmp_path)
    saved = capture.grab("oval", 3, f"dir:{src}", prompt=False, pose=None, out_root=tmp_path / "data")
    meta = json.loads(provenance.sidecar(saved[0]).read_text())
    assert len(saved) == 3 and meta["source"] == provenance.CAPTURED and meta["camera"] == f"dir:{src}"


def test_run_refuses_pills_enrolled_on_another_camera(tmp_path):
    src = _frames_dir(tmp_path, n=4)
    capture.grab("oval", 4, f"dir:{src}", prompt=False, pose=None, out_root=tmp_path / "data")
    pills = str(tmp_path / "p.json")
    demo.main(["enroll", "oval", "--dir", str(tmp_path / "data" / "oval"), "--pills", pills])
    sc = tmp_path / "scene.png"
    cv2.imwrite(str(sc), scene()[0])
    provenance.write(sc, provenance.CAPTURED, camera="webcam:1")
    with pytest.raises(SystemExit, match="enrolled on"):
        demo.main(["run", "--dry-run", "--image", str(sc), "--pills", pills])
    provenance.write(sc, provenance.CAPTURED, camera=f"dir:{src}")  # same camera: allowed
    demo.main(["run", "--dry-run", "--image", str(sc), "--pills", pills, "--out", str(tmp_path / "o.png")])


def test_mat_only_calibration_gives_mm_without_an_arm(tmp_path):
    img, true_h = synthetic_view()
    f = tmp_path / "mat.png"
    cv2.imwrite(str(f), img)
    provenance.write(f, provenance.CAPTURED, camera="webcam:0")
    cal = demo.main(["calibrate", "--mat-only", "--image", str(f), "--calib", str(tmp_path / "c.json")])
    pts = [(300, 300), (700, 500)]
    err = np.abs(cal.px_to_mat(pts) - apply_h(true_h, pts)).max()
    assert cal.mat_only and err < 1.0
    assert Calibration.load(tmp_path / "c.json").mat_only


def test_assist_runs_headless_on_saved_frames(tmp_path, capsys):
    d = tmp_path / "scenes"
    d.mkdir()
    cv2.imwrite(str(d / "a.png"), scene()[0])
    demo.main(["assist", "--source", f"dir:{d}", "--headless", "--frames", "2", "--allow-foreign",
               "--data", str(tmp_path)])
    out = capsys.readouterr().out
    assert out.count('"pill": 4') == 2          # one plan per frame, no window
    assert '"why": "merged blob' in out         # same planner the arm runs
