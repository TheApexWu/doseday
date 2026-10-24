"""The day-then-pill picker: parsing answers, matching a detection to the chosen pill, and the /select endpoint."""
import asyncio
import json
import threading
import time
import urllib.request

import cv2
import pytest

import actions
import app
import selector
import viewer

SATURDAY = 6


def frame():
    """The rehearsal scene after a JPEG round trip, as the page and the detectors see it."""
    return cv2.imdecode(cv2.imencode(".jpg", viewer.scene())[1], cv2.IMREAD_COLOR)


@pytest.mark.parametrize("text,day", [("Monday", "mon"), ("fill wednesday please", "wed"), ("sat", "sat"),
                                      ("today", "sat"), ("tomorrow", "sun")])
def test_a_day_is_read_from_plain_english(text, day):
    assert selector.parse_day(text, SATURDAY) == (day, None)


def test_two_days_are_refused_never_guessed():
    day, why = selector.parse_day("tuesday, no, friday", SATURDAY)
    assert day is None and "more than one day" in why


@pytest.mark.parametrize("text,pill", [("orange tums", "tums-orange"), ("the red round one", "tums-red"),
                                       ("white capsule", "magnesium"), ("magnesium", "magnesium"),
                                       ("orange", "tums-orange")])
def test_a_pill_is_read_from_its_name_or_its_colour_and_shape(text, pill):
    assert selector.parse_pill(text) == (pill, None)


def test_tums_without_a_colour_asks_which_colour():
    pill, why = selector.parse_pill("tums")
    assert pill is None and "Orange or red" in why


def test_a_colour_and_shape_that_match_no_pill_are_refused():
    assert selector.parse_pill("white round")[0] is None and selector.parse_pill("red capsule")[0] is None


def test_each_day_colour_boxes_only_its_own_compartment():
    img = frame()
    boxes = {d: selector.color_boxes(img, h) for d, h in selector.DAY_COLORS.items()}
    assert all(len(b) == 1 for b in boxes.values())
    lefts = [boxes[d][0]["box"][0] for d in selector.DAY_COLORS]
    assert lefts == sorted(lefts)  # Sunday to Saturday, left to right, as drawn


@pytest.mark.parametrize("pill,center_x", [("tums-orange", 170), ("tums-red", 320), ("magnesium", 480)])
def test_only_the_chosen_pill_survives_the_colour_and_shape_check(pill, center_x):
    img = frame()
    found = asyncio.run(viewer.blobs(img, 200))
    assert len(found) == 3  # positive control: the finder sees all three pills
    kept = selector.matching(img, found, pill)
    assert len(kept) == 1 and abs((kept[0]["box"][0] + kept[0]["box"][2]) / 2 - center_x) < 12


def test_a_box_on_mondays_yellow_is_not_an_orange_tums():
    img = frame()
    monday = selector.color_boxes(img, selector.DAY_COLORS["mon"])
    assert selector.matching(img, monday, "tums-orange") == []


def test_one_answer_can_name_the_day_and_the_pill():
    v = viewer.fake()
    res = v.answer("orange tums on monday", SATURDAY)
    assert res["ok"] and (v.day, v.pill) == ("mon", "tums-orange")


def test_answers_fill_the_two_questions_in_order():
    v = viewer.fake()
    assert not v.answer("orange tums", SATURDAY)["ok"] and v.pill is None  # a pill before a day is not taken
    assert v.answer("friday", SATURDAY)["ok"] and v.day == "fri"
    assert v.answer("white capsule", SATURDAY)["ok"] and v.pill == "magnesium"


def test_a_negated_answer_is_refused():
    v = viewer.fake()
    assert not v.answer("not monday", SATURDAY)["ok"] and v.day is None


def test_a_new_day_clears_the_pill():
    v = viewer.fake()
    v.answer("red tums monday", SATURDAY)
    v.answer("tuesday", SATURDAY)
    assert (v.day, v.pill) == ("tue", None)


def test_start_over_clears_both():
    v = viewer.fake()
    v.answer("red tums monday", SATURDAY)
    assert v.answer("start over")["ok"] and (v.day, v.pill) == (None, None)


@pytest.fixture
def view_server(monkeypatch):
    monkeypatch.setattr(actions, "joint_positions", lambda v: v)
    monkeypatch.setattr(viewer, "PERIOD_S", 0.01)
    monkeypatch.setattr(viewer, "POINT_SETTLE_S", 0.0)
    ctl = app.Controller(app.fake_station(0.0))

    async def make():
        return viewer.fake()
    ctl.start_view(make)
    srv = app.make_server(ctl, 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def call(url, path, body=None):
    req = urllib.request.Request(url + path, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def view_when(url, ok, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        v = json.loads(call(url, "/status")[1])["view"]
        if ok(v):
            return v
        time.sleep(0.02)
    raise AssertionError(f"view never matched: {v}")


def test_picking_a_day_then_a_pill_boxes_both_on_the_live_frame(view_server):
    url = view_server
    assert call(url, "/select", {"day": "wed"})[0] == 200
    v = view_when(url, lambda v: v["day_boxes"])
    assert v["day"] == "wed" and len(v["day_boxes"]) == 1 and v["pill_boxes"] == []
    assert call(url, "/select", {"pill": "magnesium"})[0] == 200
    v = view_when(url, lambda v: v["pill_boxes"])
    assert [b["label"] for b in v["pill_boxes"]] == ["Magnesium"] and len(v["day_boxes"]) == 1
    status, jpeg = call(url, "/frame.jpg")
    assert status == 200 and jpeg[:2] == b"\xff\xd8"


def test_a_pill_before_a_day_and_unknown_names_are_refused(view_server):
    url = view_server
    assert call(url, "/select", {"pill": "magnesium"})[0] == 400
    assert call(url, "/select", {"day": "funday"})[0] == 400
    call(url, "/select", {"day": "mon"})
    assert call(url, "/select", {"pill": "aspirin"})[0] == 400


def test_a_typed_answer_reaches_the_viewer(view_server):
    url = view_server
    status, body = call(url, "/select", {"text": "red tums for thursday", "today": SATURDAY})
    assert status == 200 and json.loads(body)["ok"]
    v = view_when(url, lambda v: v["pill_boxes"])
    assert (v["day"], v["pill"]) == ("thu", "tums-red")
