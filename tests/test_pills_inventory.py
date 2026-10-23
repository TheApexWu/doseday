import pytest

from inventory import Inventory, OverfillError
from pills import REJECT, PillType, Registry

OVAL = PillType("oval", (235, 128, 128), 1130, 2.5)
ORANGE = PillType("orange", (170, 160, 190), 600, 1.0)
CAPSULE = PillType("capsule", (80, 140, 150), 1030, 2.8)


def reg():
    return Registry([OVAL, ORANGE, CAPSULE])


def test_classify_known():
    r = reg()
    assert r.classify((232, 127, 129), 1100, 2.4)[0] == "oval"
    assert r.classify((168, 158, 192), 640, 1.05)[0] == "orange"


def test_unknown_colour_rejected():
    assert reg().classify((60, 170, 60), 1100, 2.4)[0] == REJECT


def test_wrong_size_rejected():
    assert reg().classify((235, 128, 128), 3000, 2.5)[0] == REJECT


def test_ambiguous_rejected():
    r = Registry([OVAL, PillType("oval2", (241, 128, 128), 1130, 2.5)])
    assert r.classify((238, 128, 128), 1130, 2.5)[0] == REJECT


def test_max_five_types():
    r = Registry([PillType(f"t{i}", (i * 40, 128, 128), 1000, 1.0) for i in range(5)])
    with pytest.raises(ValueError):
        r.enroll(PillType("t5", (250, 128, 128), 1000, 1.0))


def test_registry_round_trip(tmp_path):
    reg().save(tmp_path / "p.json")
    assert Registry.load(tmp_path / "p.json").classify((232, 127, 129), 1100, 2.4)[0] == "oval"


SCHED = {"Mon-AM": {"oval": 1, "capsule": 1}, "Mon-PM": {"oval": 1}, "Tue-AM": {"oval": 1}}


def test_fill_order_and_overfill():
    inv = Inventory(SCHED)
    assert inv.next_slot("oval") == "Mon-AM"
    inv.record("Mon-AM", "oval")
    assert inv.next_slot("oval") == "Mon-PM"
    with pytest.raises(OverfillError):
        inv.record("Mon-AM", "oval")
    assert inv.next_slot("orange") is None
    assert inv.remaining() == {"oval": 2, "capsule": 1}


def test_log_survives_restart(tmp_path):
    log = tmp_path / "inv.jsonl"
    inv = Inventory(SCHED, log_path=log)
    inv.record("Mon-AM", "oval")
    inv.record("Mon-AM", "capsule")
    again = Inventory(SCHED, log_path=log)
    assert again.next_slot("oval") == "Mon-PM" and again.next_slot("capsule") is None


def test_mismatch_and_summary():
    inv = Inventory(SCHED, stock={"oval": 2})
    assert inv.mismatch({"oval": 2, "capsule": 1}) == ["expected 3 oval, found 2"]
    for s in ("Mon-AM", "Mon-PM", "Tue-AM"):
        inv.record(s, "oval")
    inv.record("Mon-AM", "capsule")
    assert inv.done()
    text = inv.summary()
    assert "OK oval 1/1, capsule 1/1" in text and "schedule complete" in text
    assert "refill oval" in text  # stock hit 0


def test_unknown_slot_rejected():
    with pytest.raises(ValueError):
        Inventory({"Monday-AM": {"oval": 1}})


def test_retract_reopens_the_slot_and_survives_reload(tmp_path):
    from inventory import Inventory
    log = tmp_path / "inv.jsonl"
    inv = Inventory({"Mon-AM": {"oval": 1}}, log_path=log)
    inv.record("Mon-AM", "oval")
    inv.retract("Mon-AM", "oval", why="photo check")
    assert inv.next_slot("oval") == "Mon-AM"
    assert Inventory({"Mon-AM": {"oval": 1}}, log_path=log).next_slot("oval") == "Mon-AM"


def test_reload_does_not_count_a_placement_twice_against_stock(tmp_path):
    log = tmp_path / "inv.jsonl"
    sched = {"Mon-AM": {"oval": 2}}
    Inventory(sched, log_path=log, stock={"oval": 2}).record("Mon-AM", "oval")
    assert Inventory(sched, log_path=log, stock={"oval": 2}).stock["oval"] == 1


def test_retract_without_stock_leaves_stock_at_zero(tmp_path):
    inv = Inventory({"Mon-AM": {"oval": 1}}, log_path=tmp_path / "inv.jsonl", stock={"oval": 0})
    inv.record("Mon-AM", "oval")
    inv.retract("Mon-AM", "oval")
    assert inv.stock["oval"] == 0
