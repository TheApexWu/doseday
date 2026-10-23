import json

import numpy as np

import demo
import provenance
from calib import Calibration
from inventory import Inventory
from pills import REJECT, Registry
from synth import CAPSULE_C, OVAL_C, scene, single
from vision import detect

SCHED = {"Mon-AM": {"oval": 1, "capsule": 1}, "Mon-PM": {"oval": 1}, "Tue-AM": {"oval": 1, "capsule": 1}}


def registry(scale=1.0):
    """scale must match the calibration used at classify time (mm^2 per px^2), as demo.enroll does."""
    r = Registry()
    r.enroll_pill("oval", detect(single(OVAL_C, "black"))[0], scale)
    r.enroll_pill("capsule", detect(single(CAPSULE_C, "white", "capsule"))[0], scale)
    return r


def cal():
    # 0.5 mm/px, mat rotated 90 deg on the robot
    return Calibration(H=[[0.5, 0, 0], [0, 0.5, 0], [0, 0, 1]], theta_deg=90.0, t=[250.0, -100.0],
                       table_z=10.0, photo_pose={"x": 300, "y": 0, "z": 400})


def test_plan_on_scene():
    img, truth = scene()
    steps = demo.plan_picks(detect(img), registry(0.25), Inventory(SCHED), cal())
    by = {}
    for s in steps:
        by.setdefault(s["action"], []).append(s)
    assert len(by["pick"]) == 5 and len(by["skip"]) == 1 and len(by["reject"]) == 1
    assert sorted(s["slot"] for s in by["pick"] if s["type"] == "oval") == ["Mon-AM", "Mon-PM", "Tue-AM"]
    assert sorted(s["slot"] for s in by["pick"] if s["type"] == "capsule") == ["Mon-AM", "Tue-AM"]
    assert by["reject"][0]["type"] == REJECT
    assert "merged" in by["skip"][0]["why"]
    # every elongated pick carries a robot-frame yaw; robot xy follows the calibration
    for s in by["pick"]:
        assert s["axis_yaw"] is not None
        x, y = s["px"]
        assert np.allclose(s["robot_xy"], (250 - 0.5 * y, -100 + 0.5 * x), atol=0.2)


def test_plan_does_not_mutate_inventory():
    inv = Inventory(SCHED)
    demo.plan_picks(detect(scene()[0]), registry(), inv, None)
    assert inv.remaining() == {"oval": 3, "capsule": 2}


def test_dry_run_cli(tmp_path, capsys):
    import cv2
    cv2.imwrite(str(tmp_path / "scene.png"), scene()[0])
    provenance.write(tmp_path / "scene.png", provenance.SYNTHETIC)
    registry().save(tmp_path / "pills.json")
    (tmp_path / "sched.json").write_text(json.dumps({"schedule": SCHED}))
    steps = demo.main(["run", "--dry-run", "--image", str(tmp_path / "scene.png"), "--pills", str(tmp_path / "pills.json"),
                       "--schedule", str(tmp_path / "sched.json"), "--out", str(tmp_path / "plan.png")])
    out = capsys.readouterr().out
    assert (tmp_path / "plan.png").exists()
    assert sum(s["action"] == "pick" for s in steps) == 5
    assert "schedule complete" in out and "IMAGE pixels" in out


def test_t1_fails_on_blank_entry_in_any_position():
    nan = float("nan")
    assert demo.t1_verdict({3: 1.0, 4: nan}, 2.0) is False  # blank last tag: max() would say 1.0
    assert demo.t1_verdict({3: nan, 4: 1.0}, 2.0) is False
    assert demo.t1_verdict({3: 1.0, 4: 1.5}, 2.0) is True
    assert demo.t1_verdict({3: 2.5, 4: 1.0}, 2.0) is False
    assert demo.t1_verdict({}, 2.0) is False


def test_bare_webcam_and_index_zero_are_one_camera():
    from camera import camera_id
    assert camera_id("webcam") == camera_id("webcam:0") == "webcam:0"
