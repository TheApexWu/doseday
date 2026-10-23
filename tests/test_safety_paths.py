"""Stop path, frame decode, pre-flight and crosshair targets: the top hardware risks, without hardware."""
import asyncio
import json
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

import arm
import demo
from camera import decode_viam
from inventory import Inventory


def _stop_arm(tmp_path, fail=()):
    """PillArm with the two hardware calls replaced; calls records what reached the hardware layer."""
    calls = []
    a = arm.PillArm(robot=None, table_z=0.0, log_path=tmp_path / "a.jsonl")

    async def hw_stop():
        calls.append("stop")
        if "stop" in fail:
            raise RuntimeError("stop failed")

    async def hw_gripper(action):
        calls.append(("gripper", arm.gripper_command(action)["percentage"]))

    a._hw_stop, a._hw_gripper = hw_stop, hw_gripper
    return a, calls


def test_stop_runs_every_step_even_when_one_fails(tmp_path):
    a, calls = _stop_arm(tmp_path, fail={"stop"})
    asyncio.run(a.stop())
    assert calls == ["stop", ("gripper", arm.GRIPPER_OPEN_PCT)]
    log = [json.loads(x) for x in a.log_path.read_text().splitlines()]
    assert any(e.get("stop") == "arm.stop" and e["ok"] is False for e in log)
    assert any(e.get("stop") == "open" and e["ok"] is True for e in log)


def test_holding_is_none_until_the_gripper_reports_grip(tmp_path):
    a, _ = _stop_arm(tmp_path)
    assert asyncio.run(a.holding()) is None


def test_decode_refuses_depth_and_garbage():
    ok, jpg = cv2.imencode(".jpg", np.full((10, 10, 3), 128, np.uint8))
    assert decode_viam([SimpleNamespace(data=jpg.tobytes(), mime_type="image/jpeg")]).shape == (10, 10, 3)
    with pytest.raises(RuntimeError, match="depth"):
        decode_viam([SimpleNamespace(data=b"\x00" * 64, mime_type="image/vnd.viam.dep")])
    with pytest.raises(RuntimeError, match="decode"):
        decode_viam([SimpleNamespace(data=b"not an image", mime_type="image/jpeg")])
    with pytest.raises(RuntimeError, match="no images"):
        decode_viam([])


def test_preflight_refuses_missing_slot_pose():
    inv = Inventory({"Mon-AM": {"oval": 1}, "Mon-PM": {"oval": 1}})
    with pytest.raises(SystemExit, match="Mon-PM"):
        demo.preflight({"photo": {}, "table_z": 0, "Mon-AM": {}}, inv)
    demo.preflight({"photo": {}, "table_z": 0, "Mon-AM": {}, "Mon-PM": {}}, inv)


def test_crosshair_targets_map_tag_centres_through_the_pick_transform():
    from calib import DEFAULT_LAYOUT, build
    from test_calib import synthetic_view
    img, _ = synthetic_view()
    touches = [(DEFAULT_LAYOUT[n], (DEFAULT_LAYOUT[n][0] + 200, DEFAULT_LAYOUT[n][1] - 50)) for n in (0, 1, 2)]
    cal = build(img, DEFAULT_LAYOUT, touches, 0.0, {"x": 0, "y": 0, "z": 0})
    got = demo.crosshair_targets(img, cal, [3, 4])
    for t in (3, 4):  # robot = mat + (200, -50) by construction
        assert abs(got[t][0] - (DEFAULT_LAYOUT[t][0] + 200)) < 1.0 and abs(got[t][1] - (DEFAULT_LAYOUT[t][1] - 50)) < 1.0
