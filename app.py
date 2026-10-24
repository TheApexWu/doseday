"""Doseday control page: pick a day, then a pill, and watch the camera box both. Also big buttons and voice for
open / close / place, one robot action at a time.

  python app.py                  connects to pi-arm1 (keys from .env), serves http://localhost:8000
  python app.py --fake           no robot: fake arm, for the page and rehearsals
  python app.py --unverified     place pills without enrolled photos (demo only; says so in the log)
  python app.py --claude         identify each pill with Claude vision + measured features (needs ANTHROPIC_API_KEY)
  python app.py --detect viam yolo   show the Viam colour detector and YOLOv8 boxes on the page (display only)
  python app.py --no-view        no live camera view (the day and pill picker needs it)

Commands queue and run one at a time on the arm. STOP cancels the running action, stops the arm, empties the
queue and restores full servo torque.
"""
import argparse
import asyncio
import concurrent.futures
import json
import queue
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import actions
import governance
import selector
import viewer

HERE = Path(__file__).parent
PAGE = HERE / "web" / "index.html"
ACTIONS = {"open", "close", "place", "home", "opened"}


class Controller:
    """Owns the robot's event loop and runs queued commands one at a time."""

    def __init__(self, make_station, gov=None):
        self.gov = gov or governance.Governance()
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()
        self.station = asyncio.run_coroutine_threadsafe(make_station(), self.loop).result(timeout=60)
        self.q, self.current, self.future = queue.Queue(), None, None
        self.results, self.n = deque(maxlen=30), 0
        self.lock = threading.Lock()
        self.mode = None  # how pills are identified, shown on the page
        self.detectors: list[str] = []
        self.viewer = None
        threading.Thread(target=self._work, daemon=True).start()

    def submit(self, cmd: dict) -> int:
        with self.lock:
            self.n += 1
            cmd = {**cmd, "id": self.n}
        self.q.put(cmd)
        return cmd["id"]

    def _work(self):
        while True:
            cmd = self.q.get()
            self.current = cmd
            self.future = asyncio.run_coroutine_threadsafe(self.station.run(cmd), self.loop)
            try:
                result = self.future.result()
            except (concurrent.futures.CancelledError, asyncio.CancelledError):  # separate classes since 3.8
                result = {"ok": False, "say": "stopped"}
            except Exception as e:  # a hardware error must reach the page, not kill the worker
                result = {"ok": False, "say": f"arm error: {str(e)[:120]}"}
            self.results.appendleft({**cmd, **result, "t": time.strftime("%H:%M:%S")})
            self.current, self.future = None, None

    def stop(self):
        while not self.q.empty():
            self.q.get_nowait()
        if self.future:
            self.future.cancel()
        asyncio.run_coroutine_threadsafe(self.station.halt(), self.loop).result(timeout=15)

    def status(self) -> dict:
        return {"busy": self.current, "queued": self.q.qsize(), "results": list(self.results),
                "lids": self.station.lid, "days": list(actions.DAYS), "mode": self.mode,
                "detectors": self.detectors, "look": self.station.last_look,
                "view": self.viewer.state() if self.viewer else None, "governance": self.gov.snapshot()}

    def placed_days(self) -> list:
        return [d for d in actions.DAYS if any(r.get("ok") and r.get("action") == "place" and r.get("day") == d
                                               for r in self.results)]

    def frame(self):
        return (self.viewer and self.viewer.frame) or self.station.last_frame

    def start_view(self, make_viewer):
        self.viewer = asyncio.run_coroutine_threadsafe(make_viewer(), self.loop).result(timeout=60)
        self.viewer.start(self.loop)


def validate(cmd: dict) -> str | None:
    if cmd.get("action") not in ACTIONS:
        return f"action must be one of {sorted(ACTIONS)}"
    if cmd["action"] in {"open", "close", "place", "opened"}:
        try:
            actions.check_day(cmd.get("day", ""))
        except actions.Refused as r:
            return str(r)
    if cmd["action"] == "place" and not cmd.get("pill"):
        return "place needs a pill"
    return None


def select(v: viewer.Viewer, body: dict) -> tuple[dict, int]:
    """{text, today} is a typed or spoken answer; {day}, {pill} and {reset} come from the buttons."""
    if body.get("reset"):
        v.reset()
        return {"ok": True, "say": "Which day?"}, 200
    if "text" in body:
        res = v.answer(str(body["text"]), body.get("today"))
        return res, 200 if res["ok"] else 400
    if "day" in body:
        if body["day"] not in selector.DAY_COLORS:
            return {"ok": False, "say": f"day must be one of {list(selector.DAY_COLORS)}"}, 400
        v.choose(day=body["day"])
        return {"ok": True, "say": f"{selector.DAY_NAMES[body['day']]}. Which pill?"}, 200
    if "pill" in body:
        if body["pill"] not in selector.PILLS:
            return {"ok": False, "say": f"pill must be one of {list(selector.PILLS)}"}, 400
        if v.day is None:
            return {"ok": False, "say": "Pick a day first."}, 400
        v.choose(pill=body["pill"])
        return {"ok": True, "say": f"{selector.PILLS[body['pill']]['name']} for {selector.DAY_NAMES[v.day]}"}, 200
    return {"ok": False, "say": "send text, day, pill or reset"}, 400


def make_server(ctl: Controller, port: int, host: str = "127.0.0.1") -> ThreadingHTTPServer:
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path in ("/", "/index.html"):
                return self._send(PAGE.read_bytes(), "text/html; charset=utf-8")
            if self.path == "/status":
                return self._json(ctl.status())
            if self.path == "/governance":
                return self._json(ctl.gov.snapshot())
            if self.path.split("?")[0] == "/frame.jpg":
                frame = (ctl.viewer and ctl.viewer.frame) or ctl.station.last_frame
                if frame is None:
                    return self._json({"error": "no frame yet"}, 404)
                return self._send(frame, "image/jpeg")
            self._json({"error": "not found"}, 404)

        def do_POST(self):
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            except json.JSONDecodeError:
                return self._json({"error": "body is not JSON"}, 400)
            if self.path == "/stop":
                try:
                    ctl.stop()
                except Exception as e:  # a dropped connection reads as "no reply", so answer with the failure
                    return self._json({"ok": False, "say": "STOP failed. The arm may still be moving.",
                                       "error": f"{type(e).__name__}: {str(e)[:160]}"}, 500)
                ctl.gov.stop_alert()
                return self._json({"ok": True, "say": "stopped"})
            if self.path == "/approval":
                asked = [d for d in body.get("days") or [] if d in actions.DAYS] or ctl.placed_days()
                res, code = ctl.gov.request([selector.DAY_NAMES[d] for d in asked], ctl.frame())
                return self._json(res, code)
            if self.path == "/approval/demo":
                res, code = ctl.gov.demo_decide(body.get("verdict"))
                return self._json(res, code)
            if self.path == "/select":
                if ctl.viewer is None:
                    return self._json({"ok": False, "say": "the camera view is off"}, 400)
                res, code = select(ctl.viewer, body)
                return self._json(res, code)
            if self.path == "/cmd":
                err = validate(body) or ctl.gov.blocks(body)
                if err:
                    return self._json({"ok": False, "say": err}, 400)
                return self._json({"id": ctl.submit(body)})
            self._json({"error": "not found"}, 404)

        def _json(self, obj, code=200):
            self._send(json.dumps(obj).encode(), "application/json", code)

        def _send(self, data: bytes, ctype: str, code=200):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *_):
            pass

    # loopback: the page is served from this laptop, and nothing on the network may send arm commands
    return ThreadingHTTPServer((host, port), H)


def fake_station(move_s: float = 0.4, staged: bool = False):
    """staged: the tray always holds the pill that was asked for (a scripted rehearsal); otherwise it holds Tums."""
    import fakes

    class TrayCamera(fakes.FakeCamera):
        """Draws the pill the last placement asked for, so rehearsals show a plausible tray."""
        pill = "tums"

        async def get_images(self):
            import cv2
            import numpy as np
            img = np.full((480, 640, 3), 18, np.uint8)
            if self.pill == "magnesium":  # white capsule
                cv2.rectangle(img, (282, 222), (358, 258), (236, 236, 232), -1)
                for x in (282, 358):
                    cv2.circle(img, (x, 240), 18, (236, 236, 232), -1)
            else:  # orange tablet
                cv2.circle(img, (320, 240), 40, (20, 120, 255), -1)
            return [SimpleNamespace(data=cv2.imencode(".jpg", img)[1].tobytes())], None

    cam = TrayCamera()
    box = {"tums": [280, 200, 360, 280], "magnesium": [262, 220, 378, 260]}

    async def viam(_img):  # the colour detector only boxes orange
        return [{"source": "viam", "label": "orange-object", "confidence": 0.91, "box": box["tums"]}] \
            if cam.pill == "tums" else []

    async def yolo(_img):
        return [{"source": "yolov8", "label": "pill", "confidence": 0.96, "box": box.get(cam.pill, box["tums"])}]

    async def make():
        actions.joint_positions = list  # the fake arm takes plain lists, as in the tests; no Viam SDK needed
        st = actions.Station(fakes.FakeArm(move_s), fakes.FakeGripper(), cam, fakes.poses(),
                             fakes.LIMITS, HERE / "logs" / f"station-fake-{time.strftime('%H%M%S')}.jsonl",
                             identify=lambda img: [{"label": cam.pill}], detectors=[viam, yolo])
        if not staged:
            return st
        place = st.place

        async def stage(pill, day):
            cam.pill = (pill or "").strip().lower()
            return await place(pill, day)
        st.place = stage
        return st
    return make


def viam_detector(robot, service: str, camera: str = "follower-cam"):
    """HARDWARE-ONLY. The robot's own vision service; its boxes are in that camera's pixels."""
    from viam.services.vision import VisionClient
    vc = VisionClient.from_robot(robot, service)

    async def run(_img):
        return [{"source": "viam", "label": d.class_name, "confidence": round(d.confidence, 3),
                 "box": [d.x_min, d.y_min, d.x_max, d.y_max]} for d in await vc.get_detections_from_camera(camera)]
    return run


def yolo_detector(weights: Path):
    """YOLOv8 on this laptop over the station's frame: the Pi cannot run it (models/README.md)."""
    if not weights.exists():
        raise SystemExit(f"{weights} is missing: run ./models/fetch_pill_model.sh")
    from ultralytics import YOLO  # not a project dependency; pip install ultralytics
    model = YOLO(str(weights))

    async def run(img):
        r = (await asyncio.to_thread(model.predict, img, verbose=False))[0]
        return [{"source": "yolov8", "label": r.names[int(c)], "confidence": round(float(p), 3),
                 "box": [round(float(v)) for v in xyxy]}
                for xyxy, c, p in zip(r.boxes.xyxy.tolist(), r.boxes.cls.tolist(), r.boxes.conf.tolist())]
    return run


def real_viewer(weights: Path):
    """HARDWARE-ONLY. Its own robot connection, so the view keeps running whatever the arm is doing."""
    async def make():
        from viam.components.camera import Camera  # noqa: F401  clients exist only for types imported before connect
        from viam.services.vision import VisionClient  # noqa: F401

        from armctl import connect
        from config import VISION_SERVICE
        robot = await connect()
        try:
            yolo = yolo_detector(weights)
        except (SystemExit, ImportError) as e:  # the page says which finder drew the pill boxes
            print(f"YOLOv8 off ({e}); pill boxes come from the blob finder")
            v = viewer.real(robot, "follower-cam", VISION_SERVICE, viewer.blobs)
            v.pill_source = "blobs"
            return v
        return viewer.real(robot, "follower-cam", VISION_SERVICE, yolo)
    return make


def real_station(unverified: bool, use_claude: bool = False, detect=()):
    """HARDWARE-ONLY. One connection for the whole session; poses from taught_joints.json."""
    async def make():
        from viam.components.arm import Arm
        from viam.components.camera import Camera  # noqa: F401  clients exist only for types imported before connect
        from viam.components.gripper import Gripper
        from viam.services.vision import VisionClient  # noqa: F401  before connect, for --detect viam

        from armctl import connect, joint_limits
        robot = await connect()
        arm = Arm.from_robot(robot, "follower-arm")
        await arm.do_command({"command": "exit_manual_mode"})
        ident = None
        try:
            if use_claude:
                import identify_claude
                ident = identify_claude.ClaudeIdentifier().identify
                print("identify: Claude vision + measured features, must agree")
            else:
                import identify
                ident = identify.Gallery(identify.Features()).identify
        except SystemExit as e:  # no enrolled photos yet
            print(f"identify off: {e}")
        from config import VISION_SERVICE
        dets = [viam_detector(robot, VISION_SERVICE) if d == "viam" else yolo_detector(HERE / "models" / "pill-yolov8s.pt")
                for d in detect]
        return actions.Station(arm, Gripper.from_robot(robot, "follower-gripper"),
                               Camera.from_robot(robot, "follower-cam"), actions.load_poses(),
                               await joint_limits(arm), HERE / "logs" / f"station-{time.strftime('%H%M%S')}.jsonl",
                               identify=ident, unverified=unverified, poses_path=actions.POSES, detectors=dets,
                               read_limits=lambda: joint_limits(arm), box_path=HERE / "box.json")
    return make


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--fake", action="store_true")
    ap.add_argument("--unverified", action="store_true")
    ap.add_argument("--claude", action="store_true")
    ap.add_argument("--detect", nargs="+", choices=("viam", "yolo"), default=[])
    ap.add_argument("--no-view", action="store_true")
    a = ap.parse_args()
    ctl = Controller(fake_station(staged=True) if a.fake else real_station(a.unverified, a.claude, a.detect))
    ctl.detectors = ["viam", "yolo"] if a.fake else a.detect
    ctl.mode = ("fake" if a.fake else "claude" if a.claude and ctl.station.identify else
                "features" if ctl.station.identify else "unverified" if a.unverified else "off")
    if not a.no_view:
        async def fake_viewer():
            return viewer.fake()
        ctl.start_view(fake_viewer if a.fake else real_viewer(HERE / "models" / "pill-yolov8s.pt"))
    print(f"Doseday on http://localhost:{a.port}  ({'fake arm' if a.fake else 'pi-arm1'}; "
          f"{len(ctl.station.poses)} taught poses)", flush=True)
    make_server(ctl, a.port).serve_forever()
