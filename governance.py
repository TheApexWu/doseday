"""Caretaker check after a fill, family notices, and the one rule that pauses the arm.

States: idle -> waiting -> released | flagged | timed_out. Only an Approve from the caretaker's own account, for
this run, releases a fill (trust.py). Flagged pauses placing until a later check is approved; timed out is not
released and texts the caretaker. STOP always wins and tells the family and the caretaker.
In dry-run (no Telegram env) the caretaker is played from the page: /approval/demo, and the page says so.
"""
import threading
import time
from collections import deque
from pathlib import Path

import notify
import trust

HERE = Path(__file__).parent
IDLE, WAITING, RELEASED, FLAGGED, TIMED_OUT = "idle", "waiting", "released", "flagged", "timed_out"
FLAGGED_SAY = "Caretaker flagged the last fill. Waiting for their review."
POLICY = [
    "A caretaker checks every fill. Only their own Approve, for this fill, releases it.",
    "No answer means not released. After the wait, the caretaker gets a text.",
    "If the caretaker flags a fill, the arm stops placing pills until a later fill is approved.",
    "The family group is told what happened. Photos of pills go only to the caretaker.",
    "STOP always works, and the family and caretaker are told the arm was stopped.",
    "Every action, message and decision is logged.",
    "Doseday never chooses a dose or gives medical advice. Pill detectors are display only.",
    "Demos use candy and vitamins, never real medication.",
]


class DemoCaretaker(trust.DryRun):
    """Dry-run caretaker played from the page; no network, and the page labels it a demo."""
    name = "demo"

    def __init__(self):
        self.verdict, self.event = None, threading.Event()

    def decide(self, verdict: str):
        self.verdict = verdict
        self.event.set()

    def wait(self, run_id: str, timeout_s: float) -> str:
        self.event.wait(timeout_s)
        return self.verdict if self.verdict in (trust.OK, trust.FLAG) else trust.TIMEOUT


class _Announcing:
    """Wraps the caretaker channel so the run id is known, and the family told, the moment the photo goes out."""
    def __init__(self, ch, on_send):
        self.ch, self.on_send, self.name = ch, on_send, ch.name

    def send(self, photo, caption, run_id):
        out = self.ch.send(photo, caption, run_id)
        self.on_send(run_id)
        return out

    def wait(self, run_id, timeout_s):
        return self.ch.wait(run_id, timeout_s)


class Governance:
    def __init__(self, caretaker=trust.channel, family=notify.family, sms=notify.sms, approve=trust.request_approval,
                 caretaker_name: str = "the caretaker", timeout_s: float = 600, photo_dir: Path = HERE / "logs"):
        # built once: env does not change while the server runs, and the page polls twice a second
        self.care, self.fam, self.txt, self._approve = caretaker(), family(), sms(), approve
        self.who, self.timeout_s, self.photo_dir = caretaker_name, timeout_s, Path(photo_dir)
        self.state, self.run_id, self.days, self.demo = IDLE, None, [], None
        self.events = deque(maxlen=10)
        self.lock = threading.Lock()
        self.thread = None

    def dry_run(self) -> bool:
        return isinstance(self.care, trust.DryRun)

    def _event(self, event: str, **kw):
        row = notify.log(event, **kw)
        self.events.appendleft(row)

    def _tell_family(self, text: str):
        notify.safe_send(self.fam, text)
        self._event("family", text=text)

    def _text_caretaker(self, text: str):
        notify.safe_send(self.txt, text)
        self._event("sms", text=text)

    def blocks(self, cmd: dict):
        """The refusal for a command, or None. Only placing is paused; STOP, close and home always run."""
        if cmd.get("action") == "place" and self.state == FLAGGED:
            return FLAGGED_SAY
        return None

    def request(self, days, frame: bytes | None) -> tuple[dict, int]:
        with self.lock:
            if self.state == WAITING:
                return {"ok": False, "say": f"Already waiting for {self.who}."}, 409
            if not frame:
                return {"ok": False, "say": f"No camera picture yet. {self.who.capitalize()} needs one to check."}, 400
            self.photo_dir.mkdir(parents=True, exist_ok=True)
            photo = self.photo_dir / f"approval-{time.strftime('%Y%m%d-%H%M%S')}.jpg"
            photo.write_bytes(frame)
            self.state, self.run_id, self.days = WAITING, None, list(days)
            ch = self.care
            if isinstance(ch, trust.DryRun):
                ch = self.demo = DemoCaretaker()
            else:
                self.demo = None
        label = ", ".join(days) if days else "the organizer"
        self._event("request", days=self.days, photo=photo.name, channel=ch.name)

        def sent(run_id):
            self.run_id = run_id
            self._tell_family(f"Doseday filled {label}. Waiting for {self.who} to check.")

        def work():
            try:
                d = self._approve(photo, f"Doseday filled {label}. Approve if it looks right, Flag if not.",
                                  self.timeout_s, _Announcing(ch, sent))
                verdict = d["verdict"]
            except Exception as e:  # a dead channel is no answer: not released
                self._event("approval_error", error=f"{type(e).__name__}: {str(e)[:160]}")
                verdict = trust.TIMEOUT
            self.decided(verdict, label)
        self.thread = threading.Thread(target=work, daemon=True)
        self.thread.start()
        return {"ok": True, "say": f"Sent to {self.who}. Waiting for their check."}, 200

    def decided(self, verdict: str, label: str):
        with self.lock:
            self.state = {trust.OK: RELEASED, trust.FLAG: FLAGGED}.get(verdict, TIMED_OUT)
        self._event("decision", verdict=verdict, state=self.state, run_id=self.run_id)
        if self.state == RELEASED:
            self._tell_family(f"{self.who.capitalize()} approved {label}.")
        elif self.state == FLAGGED:
            self._tell_family(f"{self.who.capitalize()} flagged {label}. The arm is paused until they review it.")
        else:
            self._text_caretaker(f"Doseday: {label} is waiting for your check. Open Telegram to approve or flag it.")
            self._tell_family(f"No answer from {self.who} yet. We texted them. The fill is not released.")

    def demo_decide(self, verdict: str) -> tuple[dict, int]:
        if not self.dry_run():
            return {"ok": False, "say": "Demo answers are off: a real caretaker is connected."}, 403
        if verdict not in (trust.OK, trust.FLAG):
            return {"ok": False, "say": "verdict must be ok or flag"}, 400
        if self.state != WAITING or self.demo is None:
            return {"ok": False, "say": "Nothing is waiting for a check."}, 409
        self.demo.decide(verdict)
        return {"ok": True, "say": "Demo caretaker answered."}, 200

    def stop_alert(self):
        """Runs in the background so STOP never waits on the network."""
        text = f"Doseday was stopped at {time.strftime('%H:%M')}."

        def work():
            self._tell_family(text)
            self._text_caretaker(text)
        t = threading.Thread(target=work, daemon=True)
        t.start()
        return t

    def snapshot(self) -> dict:
        dry = self.dry_run()
        return {"state": self.state, "run_id": self.run_id, "days": self.days, "dry_run": dry,
                "channels": [{"role": "Caretaker", "via": "Telegram", "live": not dry},
                             {"role": "Family group", "via": "Telegram", "live": self.fam.live},
                             {"role": "Caretaker SMS", "via": "Vonage", "live": self.txt.live}],
                "policy": POLICY, "events": list(self.events)}
