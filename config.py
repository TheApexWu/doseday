"""Names and paths shared by every module. Environment overrides exist for the site, not for tests."""
import os
from pathlib import Path

ARM = os.environ.get("PILL_ARM", "arm")
GRIPPER = os.environ.get("PILL_GRIPPER", "gripper")
CAMERA = os.environ.get("PILL_CAMERA", "cam")
CAMERA_SOURCE = os.environ.get("PILL_CAMERA_SOURCE", "color")  # RealSense colour stream; "" = no filter
VISION_SERVICE = os.environ.get("PILL_VISION_SERVICE", "multi-color-detector")
POSES = Path(os.environ.get("PILL_POSES", Path(__file__).parent / "poses.json"))
