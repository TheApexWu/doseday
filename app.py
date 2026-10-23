"""Doseday control page: big buttons and voice for open / close / place, one robot action at a time.

  python app.py                  connects to pi-arm1 (keys from .env), serves http://localhost:8000
  python app.py --fake           no robot: fake arm, for the page and rehearsals
  python app.py --unverified     place pills without enrolled photos (demo only; says so in the log)
  python app.py --claude         identify each pill with Claude vision + measured features (needs ANTHROPIC_API_KEY)

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

import actions

HERE = Path(__file__).parent
PAGE = HERE / "web" / "index.html"
ACTIONS = {"open", "close", "place", "home", "opened"}


class Controller:
    """Owns the robot's event loop and runs queued commands one at a time."""

    def __init__(self, make_station):
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()
        self.station = asyncio.run_coroutine_threadsafe(make_station(), self.loop).result(timeout=60)
        self.q, self.current, self.future = queue.Queue(), None, None
        self.results, self.n = deque(maxlen=30), 0
        self.lock = threading.Lock()
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
                "lids": self.station.lid, "days": list(actions.DAYS)}


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


def make_server(ctl: Controller, port: int, host: str = "127.0.0.1") -> ThreadingHTTPServer:
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path in ("/", "/index.html"):
                return self._send(PAGE.read_bytes(), "text/html; charset=utf-8")
            if self.path == "/status":
                return self._json(ctl.status())
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
                return self._json({"ok": True, "say": "stopped"})
            if self.path == "/cmd":
                err = validate(body)
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


def fake_station(move_s: float = 0.4):
    import fakes

    async def make():
        return actions.Station(fakes.FakeArm(move_s), fakes.FakeGripper(), fakes.FakeCamera(), fakes.poses(),
                               fakes.LIMITS, HERE / "logs" / f"station-fake-{time.strftime('%H%M%S')}.jsonl",
                               identify=lambda img: [{"label": "tums"}])
    return make


def real_station(unverified: bool, use_claude: bool = False):
    """HARDWARE-ONLY. One connection for the whole session; poses from taught_joints.json."""
    async def make():
        from viam.components.arm import Arm
        from viam.components.camera import Camera  # noqa: F401  clients exist only for types imported before connect
        from viam.components.gripper import Gripper

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
        return actions.Station(arm, Gripper.from_robot(robot, "follower-gripper"),
                               Camera.from_robot(robot, "follower-cam"), actions.load_poses(),
                               await joint_limits(arm), HERE / "logs" / f"station-{time.strftime('%H%M%S')}.jsonl",
                               identify=ident, unverified=unverified, poses_path=actions.POSES,
                               read_limits=lambda: joint_limits(arm))
    return make


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--fake", action="store_true")
    ap.add_argument("--unverified", action="store_true")
    ap.add_argument("--claude", action="store_true")
    a = ap.parse_args()
    ctl = Controller(fake_station() if a.fake else real_station(a.unverified, a.claude))
    print(f"Doseday on http://localhost:{a.port}  ({'fake arm' if a.fake else 'pi-arm1'}; "
          f"{len(ctl.station.poses)} taught poses)", flush=True)
    make_server(ctl, a.port).serve_forever()
