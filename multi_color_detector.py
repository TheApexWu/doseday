"""Connected-component color detection for the Viam multi-color vision service."""
from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class ColorBox:
    label: str
    x_min: int
    y_min: int
    x_max: int
    y_max: int
    confidence: float = 1.0


HUE_RANGES = {
    "orange": ((8, 24),),
    "green": ((35, 85),),
    "cyan": ((86, 100),),
    "blue": ((101, 130),),
    "purple": ((131, 172),),
    "red": ((0, 7), (173, 179)),
}


def _components(mask: np.ndarray, label: str, min_area_px: int,
                max_area_px: float) -> list[ColorBox]:
    clean = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    clean = cv2.morphologyEx(clean, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    count, _, stats, _ = cv2.connectedComponentsWithStats(clean, connectivity=8)
    boxes = []
    for i in range(1, count):
        x, y, width, height, area = (int(v) for v in stats[i])
        if area < min_area_px or area > max_area_px:
            continue
        boxes.append(ColorBox(label, x, y, x + width, y + height))
    return boxes


def detect_colors(image_bgr: np.ndarray, *, min_area_px: int = 200,
                  saturation_min: int = 80, value_min: int = 50,
                  black_value_max: int = 45,
                  max_area_fraction: float = 0.25) -> list[ColorBox]:
    """Return non-overlapping HSV color regions, including black on a light background."""
    if image_bgr.ndim != 3 or image_bgr.shape[2] != 3:
        raise ValueError("expected a BGR image with three channels")
    if min_area_px < 1:
        raise ValueError("min_area_px must be positive")
    if not 0 < max_area_fraction <= 1:
        raise ValueError("max_area_fraction must be in (0, 1]")

    hsv = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2HSV)
    hue, saturation, value = cv2.split(hsv)
    chromatic = (saturation >= saturation_min) & (value >= value_min)
    max_area_px = image_bgr.shape[0] * image_bgr.shape[1] * max_area_fraction
    boxes = []

    for label, ranges in HUE_RANGES.items():
        selected = np.zeros(hue.shape, dtype=bool)
        for low, high in ranges:
            selected |= (hue >= low) & (hue <= high)
        mask = np.where(selected & chromatic, 255, 0).astype(np.uint8)
        boxes.extend(_components(mask, label, min_area_px, max_area_px))

    black = np.where(value <= black_value_max, 255, 0).astype(np.uint8)
    boxes.extend(_components(black, "black", min_area_px, max_area_px))
    return boxes
