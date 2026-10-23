"""app.py end to end on the fake arm: the page, queued commands, refusals, and STOP mid-action."""
import json
import threading
import time
import urllib.request

import pytest

import actions
import app


@pytest.fixture
def server(monkeypatch):
    monkeypatch.setattr(actions, "joint_positions", lambda v: v)
    monkeypatch.setattr(actions, "SETTLE_POLL_S", 0.0)
    monkeypatch.setattr(actions, "PRESS_HOLD_S", 0.0)
    monkeypatch.setattr(actions, "CAMERA_SETTLE_S", 0.0)

    def start(move_s=0.0):
        ctl = app.Controller(app.fake_station(move_s))
        srv = app.make_server(ctl, 0)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        started.append(srv)
        return ctl, f"http://127.0.0.1:{srv.server_address[1]}"

    started = []
    yield start
    for s in started:
        s.shutdown()


def call(url, path, body=None):
    req = urllib.request.Request(url + path, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def wait_result(url, n, timeout=10.0):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        res = call(url, "/status")[1]["results"]
        if len(res) >= n:
            return res
        time.sleep(0.05)
    raise AssertionError("no result")


def test_page_is_served(server):
    _, url = server()
    with urllib.request.urlopen(url + "/", timeout=10) as r:
        assert b"Doseday" in r.read()


def test_place_then_close_run_in_order_and_report(server):
    ctl, url = server()
    assert call(url, "/cmd", {"action": "place", "day": "wed", "pill": "tums"})[0] == 200
    assert call(url, "/cmd", {"action": "close", "day": "wed"})[0] == 200
    res = wait_result(url, 2)
    assert [r["say"] for r in reversed(res)] == ["tums placed in Wednesday", "Wednesday is closed"]
    assert call(url, "/status")[1]["lids"]["wed"] == "closed"


def test_wrong_pill_is_refused_out_loud(server):
    _, url = server()
    call(url, "/cmd", {"action": "place", "day": "mon", "pill": "magnesium"})
    r = wait_result(url, 1)[0]
    assert r["ok"] is False and "tums, not magnesium" in r["say"]


@pytest.mark.parametrize("body", [{"action": "dance"}, {"action": "open", "day": "funday"},
                                  {"action": "place", "day": "mon"}])
def test_bad_commands_are_rejected_before_the_queue(server, body):
    ctl, url = server()
    code, j = call(url, "/cmd", body)
    assert code == 400 and j["ok"] is False and ctl.q.qsize() == 0


def test_stop_cancels_the_running_action_and_empties_the_queue(server):
    ctl, url = server(move_s=0.3)
    call(url, "/cmd", {"action": "place", "day": "fri", "pill": "tums"})
    call(url, "/cmd", {"action": "close", "day": "sat"})
    time.sleep(0.5)
    assert call(url, "/stop", {})[1]["say"] == "stopped"
    res = wait_result(url, 1)
    assert res[0]["say"] == "stopped" and ctl.q.qsize() == 0
    assert ctl.station.arm.stopped
    torque = [c["value"] for c in ctl.station.arm.commands if c.get("command") == "set_torque_limit"]
    assert torque[-1] == actions.FULL_TORQUE
    time.sleep(0.5)
    assert len(call(url, "/status")[1]["results"]) == 1  # the queued close never ran


def test_status_lists_the_newest_ten_events(server):
    ctl, url = server()
    for i in range(12):
        ctl.station.say(f"line {i}")
    events = call(url, "/status")[1]["events"]
    assert [e["text"] for e in events] == [f"line {i}" for i in range(2, 12)]
    assert set(events[0]) == {"id", "t", "text"}


def test_status_shows_the_grip_progress_of_a_real_action(server):
    _, url = server()
    call(url, "/cmd", {"action": "place", "day": "wed", "pill": "tums"})
    wait_result(url, 1)
    assert [e["text"] for e in call(url, "/status")[1]["events"]] == ["Got it."]
