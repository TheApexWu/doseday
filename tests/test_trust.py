"""Trust loop with no network: pick verification, video, and the approval rules."""
import cv2
import numpy as np

import trust
from synth import OVAL_C, ellipse, mat


def _scene(pills):
    img = mat(kind="black", noise=2, seed=3)
    for x, y in pills:
        ellipse(img, x, y, 60, 24, 30, OVAL_C)
    return img


def test_verify_pick_positive_and_negative_controls():
    before = _scene([(200, 200), (400, 300)])
    after = _scene([(400, 300)])
    assert trust.verify_pick(before, after, (200, 200), 2, 1).ok                      # removed
    assert not trust.verify_pick(before, before, (200, 200), 2, 2).ok                 # nothing happened
    moved = _scene([(260, 200), (400, 300)])
    assert "moved" in trust.verify_pick(before, moved, (200, 200), 2, 2).why          # nudged, not picked
    assert "2 pills" in trust.verify_pick(before, _scene([]), (200, 200), 2, 0).why   # double pick / a hand


def test_recorder_writes_a_playable_video(tmp_path):
    r = trust.Recorder(tmp_path / "run.mp4", fps=5).start()
    for i in range(20):
        r.add(_scene([(100 + i * 10, 200)]))
    path = r.stop()
    cap = cv2.VideoCapture(str(path))
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    assert path.stat().st_size > 1000 and n >= 15


def test_dry_run_fails_closed(monkeypatch, tmp_path):
    monkeypatch.setattr(trust, "LOG", tmp_path / "t.jsonl")
    photo = tmp_path / "p.png"
    cv2.imwrite(str(photo), _scene([]))
    monkeypatch.delenv("PILL_TRUST_MOCK", raising=False)
    assert trust.request_approval(photo, "x", ch=trust.DryRun())["released"] is False
    monkeypatch.setenv("PILL_TRUST_MOCK", "ok")
    assert trust.request_approval(photo, "x", ch=trust.DryRun())["released"] is True
    monkeypatch.setenv("PILL_TRUST_MOCK", "flag")
    assert trust.request_approval(photo, "x", ch=trust.DryRun())["verdict"] == "flag"


class FakeHTTP:
    """Scripted Telegram: getUpdates returns queued callbacks once, then nothing."""
    def __init__(self, callbacks):
        self.headers, self.cb, self.sent = {}, list(callbacks), []

    def post(self, url, timeout=None, data=None, files=None):
        method = url.rsplit("/", 1)[-1]
        self.sent.append((method, data))
        result = True
        if method == "sendPhoto":
            result = {"message_id": 7}
        elif method == "getUpdates":
            result = [] if (data or {}).get("timeout") == 0 else self.cb
            if result:
                self.cb = []
        return type("R", (), {"json": lambda s: {"ok": True, "result": result}, "status_code": 200})()


def _cb(i, verdict, run_id, who):
    return {"update_id": i, "callback_query": {"id": f"q{i}", "data": f"{verdict}:{run_id}", "from": {"id": who}}}


def test_only_the_caretaker_approving_this_run_counts(monkeypatch, tmp_path):
    monkeypatch.setattr(trust, "LOG", tmp_path / "t.jsonl")
    monkeypatch.setattr(trust.secrets, "token_hex", lambda n: "run1")
    photo = tmp_path / "p.png"
    cv2.imwrite(str(photo), _scene([]))
    http = FakeHTTP([_cb(1, "ok", "run1", 999),      # stranger: ignored
                     _cb(2, "ok", "old0", 42),       # caretaker, stale run: ignored
                     _cb(3, "flag", "run1", 42)])    # caretaker, this run: decides
    tg = trust.Telegram("T", "100", "42", http=http)
    d = trust.request_approval(photo, "Mon-AM", timeout_s=3, ch=tg)
    assert d["verdict"] == "flag" and d["released"] is False
    assert [m for m, _ in http.sent].count("answerCallbackQuery") == 3


def test_no_answer_times_out_locked(monkeypatch, tmp_path):
    monkeypatch.setattr(trust, "LOG", tmp_path / "t.jsonl")
    photo = tmp_path / "p.png"
    cv2.imwrite(str(photo), _scene([]))
    d = trust.request_approval(photo, "x", timeout_s=1, ch=trust.Telegram("T", "1", "42", http=FakeHTTP([])))
    assert d == {**d, "verdict": "timeout", "released": False}
