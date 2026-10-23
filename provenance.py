"""Every image the pipeline reads comes from capture.py, and enrollment and the run use the SAME camera.

Phone photos taken on the side have a different lens, height and angle, so sizes and colours
enrolled from them do not transfer. capture.py writes a sidecar with
the camera id; enroll / dry-run / calibrate refuse an image without one unless --allow-foreign,
and a run refuses pills enrolled on a different camera.
"""
import json
from pathlib import Path

ARM = "arm_camera"      # legacy name, still accepted
CAPTURED = "captured"   # capture.py, any camera (arm, fixed Viam cam, webcam)
SYNTHETIC = "synthetic"  # tests/synth.py; geometry only, never for enrollment on site


def sidecar(image) -> Path:
    return Path(str(image) + ".json")


def write(image, source: str, **meta):
    sidecar(image).write_text(json.dumps({"source": source, **meta}, indent=2))


def require(image, allow_foreign: bool = False, allowed=(ARM, CAPTURED, SYNTHETIC)) -> dict:
    p = sidecar(image)
    meta = json.loads(p.read_text()) if p.exists() else {}
    if meta.get("source") in allowed or allow_foreign:
        return meta
    raise SystemExit(
        f"REFUSED {image}: no arm-camera sidecar ({p.name}). Capture with "
        f"`python capture.py LABEL --source webcam|viam` (the camera you will run with). "
        f"--allow-foreign overrides (geometry tests only).")


def same_camera(enrolled: set, run_camera: str | None, allow_foreign: bool = False):
    """Refuse a run whose camera differs from the one the pills were enrolled on."""
    enrolled = {c for c in enrolled if c}
    if allow_foreign or not run_camera or not enrolled or enrolled == {run_camera}:
        return
    raise SystemExit(f"REFUSED: pills enrolled on {sorted(enrolled)}, this image is from {run_camera}. "
                     f"Re-enroll on the camera you are running with (sizes do not transfer).")
