"""Print bounding boxes from a configured Viam vision service without moving the arm.

Usage:
  python tools/vision_probe.py

The machine connection uses VIAM_ADDRESS, VIAM_API_KEY_ID and VIAM_API_KEY.
PILL_CAMERA and PILL_VISION_SERVICE override the configured resource names.
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from arm import connect  # noqa: E402
from config import CAMERA, VISION_SERVICE  # noqa: E402


async def main() -> None:
    """HARDWARE-ONLY. Reads one camera frame through the vision service."""
    from viam.services.vision import VisionClient

    robot = await connect()
    try:
        detector = VisionClient.from_robot(robot, VISION_SERVICE)
        properties = await detector.get_properties()
        if not properties.detections_supported:
            raise SystemExit(f"{VISION_SERVICE!r} does not support detections")
        detections = await detector.get_detections_from_camera(CAMERA)
        print(json.dumps([
            {
                "label": detection.class_name,
                "confidence": round(detection.confidence, 3),
                "box": [detection.x_min, detection.y_min, detection.x_max, detection.y_max],
            }
            for detection in detections
        ], indent=2))
    finally:
        await robot.close()


if __name__ == "__main__":
    asyncio.run(main())
