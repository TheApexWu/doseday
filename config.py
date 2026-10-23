"""Names and paths shared by every module. Environment overrides exist for the site, not for tests."""
import os
import sys
from pathlib import Path


def load_dotenv(path: Path = Path(__file__).parent / ".env") -> None:
    """Read NAME=value lines from .env into the environment without overriding anything already set.
    Tolerates spaces and quotes around values, which a shell `source` does not."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip("'\""))


# tests must see the code defaults, not one laptop's site settings
if "pytest" not in sys.modules:
    load_dotenv()


ARM = os.environ.get("PILL_ARM", "arm")
GRIPPER = os.environ.get("PILL_GRIPPER", "gripper")
CAMERA = os.environ.get("PILL_CAMERA", "cam")
CAMERA_SOURCE = os.environ.get("PILL_CAMERA_SOURCE", "color")  # RealSense colour stream; "" = no filter
POSES = Path(os.environ.get("PILL_POSES", Path(__file__).parent / "poses.json"))
