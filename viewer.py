"""The page's live camera view: pick a day and Viam boxes that compartment; pick a pill and YOLOv8 boxes it.

Display only. Nothing here moves the arm: the demo's arm motion runs on its own.
"""
import asyncio
import re
import time

import cv2
import numpy as np

import selector

PERIOD_S = 0.5
POINT_SETTLE_S = 2.0   # the robot applies a changed detector config a moment after the cloud accepts it
NEGATION = re.compile(r"\b(not|never|no|don'?t|do not)\b")
RESET = re.compile(r"\b(start over|reset|again|back|cancel)\b")


class Viewer:
    """grab() -> (jpeg, img); day_boxes(img) -> Viam detections; pill_boxes(img) -> pill detections, any pill;
    point(hex) aims the colour detector at one compartment."""

    def __init__(self, grab, day_boxes, pill_boxes, point, pill_source: str):
        self.grab, self.day_boxes, self.pill_boxes, self.point = grab, day_boxes, pill_boxes, point
        self.pill_source = pill_source
        self.day = self.pill = None
        self.pointing, self.error, self.note = False, None, None
        self.frame, self.size, self.t = None, None, None
        self.day_dets, self.pill_dets = [], []
        self.loop = None

    def start(self, loop):
        self.loop = loop
        asyncio.run_coroutine_threadsafe(self._run(), loop)

    async def _run(self):
        while True:
            try:
                await self.tick()
                self.error = None
            except Exception as e:  # a dropped frame must not end the view
                self.error = f"{type(e).__name__}: {str(e)[:120]}"
            await asyncio.sleep(PERIOD_S)

    async def tick(self):
        jpeg, img = await self.grab()
        day, pill, pointing = self.day, self.pill, self.pointing
        # boxes from before the detector is re-aimed belong to the previous day's colour
        day_dets = await self.day_boxes(img) if day and not pointing else []
        pill_dets = selector.matching(img, await self.pill_boxes(img), pill) if pill else []
        self.frame, self.size, self.t = jpeg, [img.shape[1], img.shape[0]], round(time.time(), 3)
        self.day_dets, self.pill_dets = day_dets, pill_dets

    async def _aim(self, day: str):
        self.pointing = True
        try:
            await self.point(selector.DAY_COLORS[day])
            await asyncio.sleep(POINT_SETTLE_S)
        except Exception as e:
            self.error = f"could not aim the detector: {type(e).__name__}: {str(e)[:120]}"
        finally:
            if self.day == day:
                self.pointing = False

    def choose(self, day: str | None = None, pill: str | None = None) -> None:
        if day is not None:
            self.day, self.pill = day, None
            if self.loop is not None:
                asyncio.run_coroutine_threadsafe(self._aim(day), self.loop)
        if pill is not None:
            self.pill = pill

    def reset(self) -> None:
        self.day = self.pill = None
        self.day_dets, self.pill_dets = [], []

    def answer(self, text: str, today: int | None = None) -> dict:
        """A typed or spoken answer. It may name the day, the pill, or both ("orange tums on monday")."""
        t = (text or "").strip()
        if RESET.search(t.lower()):
            self.reset()
            return {"ok": True, "say": "Starting over. Which day?"}
        if NEGATION.search(t.lower()):
            return {"ok": False, "say": "I heard 'not' or 'no'. Say it again without it."}
        day, day_why = selector.parse_day(t, today)
        pill, pill_why = selector.parse_pill(t)
        if day_why and "more than one" in day_why:
            return {"ok": False, "say": day_why}
        if pill_why and "more than one" in pill_why:
            return {"ok": False, "say": pill_why}
        if not day and not self.day:
            return {"ok": False, "say": day_why}
        if day:
            self.choose(day=day)
        if not pill:
            if day:
                return {"ok": True, "say": f"{selector.DAY_NAMES[day]}. Which pill?"}
            return {"ok": False, "say": pill_why}
        self.choose(pill=pill)
        return {"ok": True, "say": f"{selector.PILLS[pill]['name']} for {selector.DAY_NAMES[self.day]}"}

    def state(self) -> dict:
        return {"day": self.day, "pill": self.pill, "pointing": self.pointing, "error": self.error, "t": self.t,
                "size": self.size, "day_boxes": self.day_dets, "pill_boxes": self.pill_dets,
                "pill_source": self.pill_source, "days": selector.DAY_COLORS,
                "pills": {k: v for k, v in selector.PILLS.items()}}


# --- rehearsal: a drawn organizer and three pills, so the flow runs with no robot ---

def scene() -> np.ndarray:
    img = np.full((480, 640, 3), 24, np.uint8)
    for i, hex_color in enumerate(selector.DAY_COLORS.values()):
        rgb = [int(hex_color[j:j + 2], 16) for j in (1, 3, 5)]
        x = 22 + i * 86
        cv2.rectangle(img, (x, 40), (x + 76, 150), rgb[::-1], -1)
    cv2.circle(img, (170, 340), 34, (20, 120, 255), -1)       # orange Tums
    cv2.circle(img, (320, 340), 34, (40, 30, 215), -1)        # red Tums
    cv2.rectangle(img, (446, 322), (514, 358), (238, 238, 234), -1)  # white magnesium capsule
    for x in (446, 514):
        cv2.circle(img, (x, 340), 18, (238, 238, 234), -1)
    return img


async def blobs(img, y0: int = 0) -> list[dict]:
    """Pill boxes from the repo's own blob finder (vision.detect), below row y0: the stand-in when YOLOv8 is off."""
    import vision
    out = []
    for p in vision.detect(img[y0:]):
        x, y, w, h = cv2.boundingRect(np.array(p.box_px, np.float32))
        out.append({"source": "blobs", "label": "pill", "confidence": 1.0, "box": [x, y + y0, x + w, y + h + y0]})
    return out


def fake() -> Viewer:
    img = scene()
    jpeg = cv2.imencode(".jpg", img)[1].tobytes()
    aimed = {}
    mat_y0 = 200  # pills lie below the organizer; the blob finder looks only there

    async def grab():
        return jpeg, img

    async def day_boxes(frame):
        return selector.color_boxes(frame, aimed["hex"]) if "hex" in aimed else []

    async def pill_boxes(frame):
        return await blobs(frame, mat_y0)

    async def point(hex_color):
        aimed["hex"] = hex_color

    return Viewer(grab, day_boxes, pill_boxes, point, pill_source="blobs")


# --- the robot ---

def real(robot, camera: str, service: str, yolo) -> Viewer:
    """HARDWARE-ONLY. Frames and boxes from the robot's camera and colour detector; yolo runs on this laptop."""
    from viam.components.camera import Camera
    from viam.services.vision import VisionClient
    from viam.errors import ResourceNotFoundError
    cam = Camera.from_robot(robot, camera)
    try:
        vc = VisionClient.from_robot(robot, service)
    except ResourceNotFoundError:  # another kit (pi-arm3) has no colour detector: show the camera, no boxes
        vc = None

    async def grab():
        imgs, _ = await cam.get_images()
        data = imgs[0].data
        img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise RuntimeError("the camera frame did not decode")
        return data, img

    async def day_boxes(_img):
        if vc is None:
            return []
        return [{"source": "viam", "label": d.class_name, "confidence": round(d.confidence, 3),
                 "box": [d.x_min, d.y_min, d.x_max, d.y_max]} for d in await vc.get_detections_from_camera(camera)]

    async def point(hex_color):
        if vc is None:  # never rewrite the cloud config of a machine without our detector
            return
        await aim_detector(robot, service, hex_color)

    return Viewer(grab, day_boxes, yolo, point, pill_source="yolov8")


async def aim_detector(robot, service: str, hex_color: str) -> None:
    """HARDWARE-ONLY. Set the colour detector's detect_color in the machine's cloud config (sammy's main.py).
    The rest of the config is written back unchanged."""
    import copy
    import os

    from viam.app.viam_client import ViamClient
    from viam.rpc.dial import DialOptions
    meta = await robot.get_cloud_metadata()
    opts = DialOptions.with_api_key(api_key=os.environ["VIAM_API_KEY"], api_key_id=os.environ["VIAM_API_KEY_ID"])
    async with await ViamClient.create_from_dial_options(opts) as client:
        part = await client.app_client.get_robot_part(meta.machine_part_id)
        config = copy.deepcopy(dict(part.robot_config or {}))
        svc = next((s for s in config.get("services", []) if s.get("name") == service), None)
        if svc is None:
            raise RuntimeError(f"{service!r} is not in the machine's services")
        if svc.setdefault("attributes", {}).get("detect_color") == hex_color:
            return
        svc["attributes"]["detect_color"] = hex_color
        await client.app_client.update_robot_part(robot_part_id=meta.machine_part_id, name=part.name,
                                                  robot_config=config, last_known_update=part.last_updated)
