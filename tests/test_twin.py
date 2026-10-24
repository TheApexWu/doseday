"""The twin's arm must sit where the robot reported itself (twin/validate.py). Skipped without MuJoCo or the
vendor model (twin/fetch_model.sh): the robot code doesn't depend on either."""
from pathlib import Path

import pytest

pytest.importorskip("mujoco")
VENDOR = Path(__file__).resolve().parent.parent / "twin" / "vendor" / "SO101" / "so101_new_calib_camera.xml"
pytestmark = pytest.mark.skipif(not VENDOR.exists(), reason="run twin/fetch_model.sh first")


def test_twin_arm_matches_the_robots_reported_poses():
    from twin import validate
    assert validate.main() == 0
