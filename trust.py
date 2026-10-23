"""Trust loop: record the run, verify each pick, send the result to the caretaker, wait for a decision.

  python trust.py send --photo data/assist/x.png --caption "Mon-AM filled"   PILL_TRUST_MOCK=ok|flag|timeout
  python trust.py whoami                                                     Telegram: print chat ids that messaged the bot

Fail closed: only an explicit Approve from the caretaker's own Telegram account, for THIS run,
counts. Timeout and Flag both mean the organizer is not released. Approval is a logged decision,
not a physical lock. Never send photos of real medication: demo with candy/vitamins.
"""
import argparse
import json
import os
import secrets
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).parent
LOG = HERE / "logs" / "trust.jsonl"
UA = {"User-Agent": "doseday/0.1"}  # default python UAs get blocked by some edges
OK, FLAG, TIMEOUT = "ok", "flag", "timeout"


def _log(event: dict):
    LOG.parent.mkdir(exist_ok=True)
    with LOG.open("a") as f:
        f.write(json.dumps({"t": round(time.time(), 3), **event}) + "\n")


# ── patient-side cue ─────────────────────────────────────────────────────────
def announce(text: str, hold_s: float = 2.0, speak: bool = True):
    """Say what the arm is about to do, then hold still so the person can react."""
    _log({"announce": text})
    if speak and not os.environ.get("PILL_SILENT"):
        try:
            subprocess.run(["say", text], timeout=10, check=False)  # macOS; blocks until spoken
        except (FileNotFoundError, subprocess.TimeoutExpired):
            print(f"[announce] {text}")
    else:
        print(f"[announce] {text}")
    time.sleep(hold_s)


# ── video ────────────────────────────────────────────────────────────────────
class Recorder:
    """Frames -> mp4 on a background thread so the control loop never waits on the encoder."""
    def __init__(self, path, fps: float = 8.0):
        self.path, self.fps, self.w = Path(path), fps, None
        self._q: list = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._t.start()
        return self

    def add(self, frame: np.ndarray):
        with self._lock:
            self._q.append(frame.copy())

    def _run(self):
        while not self._stop.is_set() or self._q:
            with self._lock:
                batch, self._q = self._q, []
            for f in batch:
                if self.w is None:
                    h, w = f.shape[:2]
                    # mp4v opens on stock OpenCV for macOS; avc1 often does not
                    self.w = cv2.VideoWriter(str(self.path), cv2.VideoWriter_fourcc(*"mp4v"), self.fps, (w, h))
                self.w.write(f)
            time.sleep(0.02)

    def stop(self) -> Path:
        self._stop.set()
        self._t.join(timeout=10)
        if self.w is not None:
            self.w.release()
        return self.path


# ── verification ─────────────────────────────────────────────────────────────
@dataclass
class PickCheck:
    ok: bool
    roi_change: float
    count_before: int
    count_after: int
    why: str


def verify_pick(before: np.ndarray, after: np.ndarray, pick_px, count_before: int, count_after: int,
                radius: int = 40, change_min: float = 0.15) -> PickCheck:
    """A pick happened when the spot it came from changed AND exactly one pill left the mat.
    Needs both frames from the same camera pose (fixed camera, or the arm's photo pose)."""
    x, y = int(pick_px[0]), int(pick_px[1])
    h, w = before.shape[:2]
    x0, x1, y0, y1 = max(0, x - radius), min(w, x + radius), max(0, y - radius), min(h, y + radius)
    a = cv2.cvtColor(before[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY).astype(np.int16)
    b = cv2.cvtColor(after[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY).astype(np.int16)
    change = float((np.abs(a - b) > 40).mean()) if a.size else 0.0
    removed = count_before - count_after
    if change < change_min:
        return PickCheck(False, change, count_before, count_after, "pick spot unchanged: pill still there")
    if removed == 0:
        return PickCheck(False, change, count_before, count_after, "spot changed but count did not: pill moved, not picked")
    if removed > 1:
        return PickCheck(False, change, count_before, count_after, f"{removed} pills left the mat: double pick or a hand")
    return PickCheck(True, change, count_before, count_after, "one pill removed from the pick spot")


# ── caretaker channel ────────────────────────────────────────────────────────
class DryRun:
    """No network. Decision comes from PILL_TRUST_MOCK (ok | flag | timeout); default timeout = fail closed."""
    name = "dry-run"

    def send(self, photo, caption: str, run_id: str) -> str:
        _log({"send": "dry-run", "photo": str(photo), "caption": caption, "run_id": run_id})
        print(f"[dry-run] would send {photo} with Approve/Flag for run {run_id}: {caption}")
        return "dry"

    def wait(self, run_id: str, timeout_s: float) -> str:
        d = os.environ.get("PILL_TRUST_MOCK", TIMEOUT)
        return d if d in (OK, FLAG) else TIMEOUT


class Telegram:
    """Bot API over plain HTTPS, long polling (no web server). Only the caretaker's user id can decide."""
    name = "telegram"

    def __init__(self, token: str, chat_id: str, caretaker_id: str, http=None):
        import requests
        self.base = f"https://api.telegram.org/bot{token}"
        self.chat_id, self.caretaker_id = str(chat_id), str(caretaker_id)
        self.http = http or requests.Session()
        self.http.headers.update(UA)
        self.offset = None

    def _call(self, method: str, **kw):
        r = self.http.post(f"{self.base}/{method}", timeout=40, **kw)
        body = r.json()
        if not body.get("ok"):
            raise RuntimeError(f"telegram {method}: {body.get('description', r.status_code)}")
        return body["result"]

    def send(self, photo, caption: str, run_id: str) -> str:
        self._call("deleteWebhook")  # getUpdates fails while a webhook is set
        self._drain()                # ignore button presses from earlier runs
        kb = {"inline_keyboard": [[{"text": "Approve", "callback_data": f"ok:{run_id}"},
                                   {"text": "Flag", "callback_data": f"flag:{run_id}"}]]}
        with open(photo, "rb") as f:
            msg = self._call("sendPhoto", data={"chat_id": self.chat_id, "caption": caption[:1024],
                                                "reply_markup": json.dumps(kb)}, files={"photo": f})
        _log({"send": "telegram", "run_id": run_id, "message_id": msg.get("message_id")})
        return str(msg.get("message_id"))

    def _updates(self, timeout: int):
        params = {"timeout": timeout, "allowed_updates": json.dumps(["callback_query"])}
        if self.offset is not None:
            params["offset"] = self.offset
        res = self._call("getUpdates", data=params)
        if res:
            self.offset = res[-1]["update_id"] + 1
        return res

    def _drain(self):
        self._updates(0)

    def wait(self, run_id: str, timeout_s: float) -> str:
        end = time.time() + timeout_s
        while time.time() < end:
            for u in self._updates(int(min(25, max(1, end - time.time())))):
                q = u.get("callback_query") or {}
                data, who = q.get("data", ""), str((q.get("from") or {}).get("id", ""))
                if not data:
                    continue
                verdict, _, rid = data.partition(":")
                accepted = who == self.caretaker_id and rid == run_id and verdict in (OK, FLAG)
                _log({"callback": data, "from": who, "accepted": accepted})
                self._call("answerCallbackQuery", data={"callback_query_id": q.get("id"),
                                                        "text": "Recorded" if accepted else "Not for this run"})
                if accepted:
                    return verdict
        return TIMEOUT

    def whoami(self):
        for u in self._call("getUpdates"):
            m = u.get("message") or (u.get("callback_query") or {}).get("message") or {}
            frm = u.get("message", {}).get("from") or (u.get("callback_query") or {}).get("from") or {}
            print(f"chat_id={m.get('chat', {}).get('id')} from_id={frm.get('id')} name={frm.get('first_name')}")


def channel():
    # TODO: an SMS channel (Vonage) is planned as primary. Any SMS link to a photo needs access
    # control first, because the photo shows the patient's pills.
    tok = os.environ.get("TELEGRAM_BOT_TOKEN")
    if os.environ.get("PILL_TRUST_MOCK") or not tok:
        return DryRun()
    return Telegram(tok, os.environ["TELEGRAM_CHAT_ID"], os.environ["TELEGRAM_CARETAKER_ID"])


def request_approval(photo, caption: str, timeout_s: float = 600, ch=None) -> dict:
    """Send the end-of-run photo and block for the caretaker. Returns the logged decision."""
    ch = ch or channel()
    run_id = secrets.token_hex(4)  # fresh per run: an old Approve cannot release a new run
    ch.send(photo, caption, run_id)
    verdict = ch.wait(run_id, timeout_s)
    released = verdict == OK
    decision = {"run_id": run_id, "channel": ch.name, "verdict": verdict, "released": released}
    _log({"decision": decision})
    return decision


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("send", "whoami"))
    ap.add_argument("--photo")
    ap.add_argument("--caption", default="Pill organizer filled. Approve to release.")
    ap.add_argument("--timeout", type=float, default=600)
    args = ap.parse_args(argv)
    if args.cmd == "whoami":
        return Telegram(os.environ["TELEGRAM_BOT_TOKEN"], "0", "0").whoami()
    d = request_approval(args.photo, args.caption, args.timeout)
    print(json.dumps(d))
    return d


if __name__ == "__main__":
    main()
