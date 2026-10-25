"""Caretaker check and notices, with fake channels: nothing here touches the network."""
import json
import threading
import time
import urllib.error
import urllib.request

import pytest

import actions
import app
import governance
import notify
import trust


def call(url, path, body=None):
    req = urllib.request.Request(url + path, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


class Rec:
    """A notice channel that records what it was given."""
    def __init__(self, name, live=True, delay=0.0):
        self.name, self.live, self.delay, self.sent = name, live, delay, []

    def send(self, *args):
        time.sleep(self.delay)
        self.sent.append(args)


class FakeCaretaker:
    """A live-looking caretaker channel (not a DryRun) that answers with a fixed verdict."""
    name = "telegram"

    def __init__(self, verdict):
        self.verdict, self.photos = verdict, []

    def send(self, photo, caption, run_id):
        self.photos.append(photo)
        return "1"

    def wait(self, run_id, timeout_s):
        return self.verdict


@pytest.fixture(autouse=True)
def quiet_logs(tmp_path, monkeypatch):
    monkeypatch.setattr(notify, "LOG", tmp_path / "governance.jsonl")
    monkeypatch.setattr(trust, "LOG", tmp_path / "trust.jsonl")
    monkeypatch.setattr(actions, "joint_positions", lambda v: v)
    for k in ("SETTLE_POLL_S", "PRESS_HOLD_S", "CAMERA_SETTLE_S", "ARRIVE_POLL_S"):
        monkeypatch.setattr(actions, k, 0.0)


def make(tmp_path, care, fam=None, sms=None, timeout_s=0.05):
    fam, sms = fam or Rec("family-telegram"), sms or Rec("vonage-sms")
    gov = governance.Governance(caretaker=lambda: care, family=lambda: fam, sms=lambda: sms,
                                timeout_s=timeout_s, photo_dir=tmp_path)
    return gov, fam, sms


def settle(gov):
    gov.thread.join(timeout=5)
    assert not gov.thread.is_alive()


def serve(gov):
    ctl = app.Controller(app.fake_station(0.0), gov=gov)
    srv = app.make_server(ctl, 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return ctl, srv, f"http://127.0.0.1:{srv.server_address[1]}"


def test_flag_pauses_placing_but_not_close(tmp_path):
    gov, fam, _ = make(tmp_path, FakeCaretaker(trust.FLAG))
    ctl, srv, url = serve(gov)
    try:
        ctl.station.last_frame = b"jpeg"
        assert call(url, "/approval", {"days": ["mon"]})[0] == 200
        settle(gov)
        assert gov.state == governance.FLAGGED
        code, body = call(url, "/cmd", {"action": "place", "day": "mon", "pill": "tums"})
        assert code == 400 and body["say"] == governance.FLAGGED_SAY
        assert call(url, "/cmd", {"action": "close", "day": "mon"})[0] == 200
    finally:
        srv.shutdown()


def test_approve_releases_and_tells_family(tmp_path):
    gov, fam, sms = make(tmp_path, FakeCaretaker(trust.OK))
    gov.request(["Monday"], b"jpeg")
    settle(gov)
    assert gov.state == governance.RELEASED and gov.blocks({"action": "place"}) is None
    texts = [a[0] for a in fam.sent]
    assert any("Waiting for" in t for t in texts) and any("approved Monday" in t for t in texts)
    assert sms.sent == []


def test_timeout_is_not_released_and_texts_caretaker(tmp_path):
    gov, fam, sms = make(tmp_path, FakeCaretaker(trust.TIMEOUT))
    gov.request(["Tuesday"], b"jpeg")
    settle(gov)
    assert gov.state == governance.TIMED_OUT
    assert len(sms.sent) == 1 and "Tuesday" in sms.sent[0][0]


def test_dead_caretaker_channel_counts_as_no_answer(tmp_path):
    def boom(*a):
        raise RuntimeError("telegram down")
    gov, _, sms = make(tmp_path, FakeCaretaker(trust.OK))
    gov._approve = boom
    gov.request(["Monday"], b"jpeg")
    settle(gov)
    assert gov.state == governance.TIMED_OUT and sms.sent


def test_family_never_gets_a_photo(tmp_path):
    care = FakeCaretaker(trust.FLAG)
    gov, fam, _ = make(tmp_path, care)
    gov.request(["Monday"], b"jpeg")
    settle(gov)
    gov.stop_alert().join(timeout=5)
    assert care.photos  # the caretaker did get the photo
    assert fam.sent and all(len(a) == 1 and isinstance(a[0], str) for a in fam.sent)


def test_family_telegram_only_calls_send_message():
    class Http:
        headers, calls = {}, []

        def post(self, url, **kw):
            self.calls.append((url, kw))
            return type("R", (), {"json": lambda s: {"ok": True}})()
    http = Http()
    notify.FamilyTelegram("tok", "-100", http=http).send("hello")
    assert [u.rsplit("/", 1)[1] for u, _ in http.calls] == ["sendMessage"]
    assert "files" not in http.calls[0][1] and http.headers["User-Agent"]


def test_vonage_raises_on_a_failed_status():
    class Http:
        headers = {}

        def post(self, url, **kw):
            return type("R", (), {"json": lambda s: {"messages": [{"status": "4", "error-text": "Bad Credentials"}]}})()
    with pytest.raises(RuntimeError, match="Bad Credentials"):
        notify.VonageSMS("k", "s", "Doseday", "1555", http=Http()).send("x")


def test_demo_answer_refused_when_a_real_caretaker_is_connected(tmp_path):
    gov, _, _ = make(tmp_path, FakeCaretaker(trust.OK))
    ctl, srv, url = serve(gov)
    try:
        assert call(url, "/approval/demo", {"verdict": "ok"})[0] == 403
    finally:
        srv.shutdown()


def test_demo_caretaker_decides_in_dry_run(tmp_path):
    gov, _, _ = make(tmp_path, trust.DryRun(), timeout_s=5)
    ctl, srv, url = serve(gov)
    try:
        ctl.station.last_frame = b"jpeg"
        assert call(url, "/approval", {})[0] == 200
        for _ in range(100):  # the family notice lands when the photo is "sent"
            if gov.run_id:
                break
            time.sleep(0.02)
        assert call(url, "/approval/demo", {"verdict": "flag"})[0] == 200
        settle(gov)
        assert gov.state == governance.FLAGGED
        assert call(url, "/governance")[1]["dry_run"] is True
    finally:
        srv.shutdown()


def test_no_frame_no_request(tmp_path):
    gov, _, _ = make(tmp_path, FakeCaretaker(trust.OK))
    body, code = gov.request(["Monday"], None)
    assert code == 400 and gov.state == governance.IDLE


def test_stop_alert_does_not_wait_on_the_network(tmp_path):
    slow = Rec("vonage-sms", delay=1.0)
    gov, fam, _ = make(tmp_path, FakeCaretaker(trust.OK), sms=slow)
    ctl, srv, url = serve(gov)
    try:
        t0 = time.monotonic()
        assert call(url, "/stop", {})[0] == 200
        assert time.monotonic() - t0 < 0.8
        for _ in range(200):
            if slow.sent:
                break
            time.sleep(0.02)
        assert "stopped" in slow.sent[0][0] and any("stopped" in a[0] for a in fam.sent)
    finally:
        srv.shutdown()


def test_failed_notice_is_logged_not_raised(tmp_path):
    class Broken(Rec):
        def send(self, *a):
            raise RuntimeError("no network")
    gov, _, _ = make(tmp_path, FakeCaretaker(trust.OK), fam=Broken("family-telegram"))
    gov.stop_alert().join(timeout=5)
    assert "send_failed" in notify.LOG.read_text()


def test_flag_refuses_choosing_a_pill(tmp_path):
    gov, _, _ = make(tmp_path, FakeCaretaker(trust.FLAG))
    gov.request(["Monday"], b"jpeg")
    settle(gov)
    ctl, srv, url = serve(gov)
    try:
        ctl.viewer = object()  # any viewer: the refusal comes before it is used
        code, body = call(url, "/select", {"pill": "magnesium"})
        assert code == 400 and body["say"] == governance.FLAGGED_SAY
    finally:
        srv.shutdown()


class JsonHttp:
    def __init__(self, status=202, body='{"message_uuid": "u1"}'):
        self.headers, self.calls, self.status, self.body = {}, [], status, body

    def post(self, url, **kw):
        self.calls.append((url, kw))
        return type("R", (), {"status_code": self.status, "text": self.body})()


def test_whatsapp_sandbox_sends_text_only_with_key_auth():
    http = JsonHttp()
    notify.VonageWhatsApp("k", "s", "", "+15551234567", http=http).send("hello")
    url, kw = http.calls[0]
    assert url == "https://messages-sandbox.nexmo.com/v1/messages" and kw["auth"] == ("k", "s")
    assert kw["json"] == {"from": "14157386102", "to": "15551234567", "channel": "whatsapp",
                          "message_type": "text", "text": "hello"}


def test_whatsapp_raises_unless_accepted():
    with pytest.raises(RuntimeError, match="401"):
        notify.VonageWhatsApp("k", "s", "", "1555", http=JsonHttp(401, "Unauthorized")).send("x")


def test_vonage_channel_comes_from_env(monkeypatch):
    for k, v in {"VONAGE_API_KEY": "k", "VONAGE_API_SECRET": "s", "CARETAKER_PHONE": "1555"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("VONAGE_FROM", raising=False)
    monkeypatch.delenv("VONAGE_CHANNEL", raising=False)
    assert isinstance(notify.sms(), notify.DryRun)  # SMS needs a sender number
    monkeypatch.setenv("VONAGE_CHANNEL", "whatsapp")
    assert isinstance(notify.sms(), notify.VonageWhatsApp)  # the sandbox supplies its own


def test_approval_timeout_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("DOSEDAY_APPROVAL_TIMEOUT_S", "20")
    dry = lambda: notify.DryRun("x")
    gov = governance.Governance(caretaker=trust.DryRun, family=dry, sms=dry, photo_dir=tmp_path)
    assert gov.timeout_s == 20
