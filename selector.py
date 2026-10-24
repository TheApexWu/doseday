"""Pick a day, then a pill: what the page's two questions mean, and how a detection is matched to the answer.

Each day's compartment in the organizer has its own colour. Choosing a day points Viam's colour detector at that
colour, so it boxes the compartment. Choosing a pill keeps only the pill detections whose colour and shape match it.
Pure logic: no Viam imports, so it runs offline.
"""
import re

import cv2
import numpy as np

# The organizer's compartment colours, as the Viam colour detector takes them (sammy's main.py)
DAY_COLORS = {"sun": "#F47F8B", "mon": "#F5C94E", "tue": "#F4DF35", "wed": "#A5E637",
              "thu": "#7CBCE9", "fri": "#35C9CE", "sat": "#C58BE8"}
DAY_NAMES = {"sun": "Sunday", "mon": "Monday", "tue": "Tuesday", "wed": "Wednesday", "thu": "Thursday",
             "fri": "Friday", "sat": "Saturday"}
PILLS = {
    "tums-orange": {"name": "Orange Tums", "color": "orange", "shape": "round"},
    "tums-red": {"name": "Red Tums", "color": "red", "shape": "round"},
    "magnesium": {"name": "Magnesium", "color": "white", "shape": "capsule"},
}
CAPSULE_ASPECT = 1.5   # long side over short side: a round tablet's box is near 1, a capsule's near 2.5
WHITE_MAX_SAT, WHITE_MIN_VAL = 60, 150


def parse_day(text: str, today: int | None = None) -> tuple[str | None, str | None]:
    """(day, None) or (None, why). today is 0 = Sunday, as in JavaScript."""
    t = text.lower()
    found = {d for d, n in DAY_NAMES.items() if re.search(rf"\b({n.lower()}|{d})\b", t)}
    if today is not None and re.search(r"\btoday\b", t):
        found.add(list(DAY_NAMES)[today])
    if today is not None and re.search(r"\btomorrow\b", t):
        found.add(list(DAY_NAMES)[(today + 1) % 7])
    if len(found) > 1:
        return None, "I heard more than one day. Say one day."
    if not found:
        return None, "Which day? Say a day of the week."
    return found.pop(), None


def parse_pill(text: str) -> tuple[str | None, str | None]:
    """(pill key, None) or (None, why). Accepts a name, or a colour and a shape."""
    t = text.lower()
    colors = {c for c in ("orange", "red", "white") if re.search(rf"\b{c}\b", t)}
    shapes = set()
    if re.search(r"\b(round|circle|circular|tablet|disc)\b", t):
        shapes.add("round")
    if re.search(r"\b(capsule|oval|oblong|long)\b", t):
        shapes.add("capsule")
    if re.search(r"\btums?\b", t):
        shapes.add("round")
    if re.search(r"\bmag(nesium)?\b", t):
        colors.add("white"), shapes.add("capsule")
    if len(colors) > 1 or len(shapes) > 1:
        return None, "I heard more than one pill. Say one."
    keys = [k for k, p in PILLS.items() if (not colors or p["color"] in colors) and (not shapes or p["shape"] in shapes)]
    if not (colors or shapes) or not keys:
        return None, "Which pill? Orange Tums, red Tums, or white magnesium."
    if len(keys) > 1:
        return None, "Which colour of Tums? Orange or red."
    return keys[0], None


def classify(img: np.ndarray, box) -> tuple[str, str]:
    """(colour, shape) of the pill inside box (x0, y0, x1, y1)."""
    x0, y0, x1, y1 = (int(round(v)) for v in box)
    w, h = max(x1 - x0, 1), max(y1 - y0, 1)
    shape = "capsule" if max(w, h) / min(w, h) >= CAPSULE_ASPECT else "round"
    # the middle half of the box: the corners are background for both shapes
    crop = img[y0 + h // 4:y1 - h // 4, x0 + w // 4:x1 - w // 4]
    if crop.size == 0:
        return "other", shape
    hue, sat, val = (float(np.median(c)) for c in cv2.split(cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)))
    if sat < WHITE_MAX_SAT:
        return ("white" if val >= WHITE_MIN_VAL else "other"), shape
    if hue < 7 or hue > 170:
        return "red", shape
    if hue < 19:  # Monday's compartment yellow is hue 22: a box on it must not pass as an orange Tums
        return "orange", shape
    return "other", shape


def matching(img: np.ndarray, detections: list[dict], pill: str) -> list[dict]:
    """Detections of the chosen pill, each with the colour and shape it was judged to have."""
    want = PILLS[pill]
    out = []
    for d in detections:
        color, shape = classify(img, d["box"])
        if color == want["color"] and shape == want["shape"]:
            out.append({**d, "label": want["name"], "color": color, "shape": shape})
    return out


def color_boxes(img: np.ndarray, hex_color: str, tol: float = 10.0, min_area: float = 400.0) -> list[dict]:
    """Boxes around regions of one colour: what Viam's colour detector returns, for rehearsals without the robot.
    Lab distance, not hue: Monday's and Tuesday's yellows are only 4 hue steps apart."""
    rgb = [int(hex_color[i:i + 2], 16) for i in (1, 3, 5)]
    target = cv2.cvtColor(np.uint8([[rgb[::-1]]]), cv2.COLOR_BGR2LAB)[0, 0].astype(float)
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB).astype(float)
    mask = (np.linalg.norm(lab - target, axis=2) <= tol).astype(np.uint8) * 255
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out = []
    for c in contours:
        if cv2.contourArea(c) < min_area:
            continue
        x, y, w, h = cv2.boundingRect(c)
        out.append({"source": "viam", "label": hex_color, "confidence": 1.0, "box": [x, y, x + w, y + h]})
    return out
