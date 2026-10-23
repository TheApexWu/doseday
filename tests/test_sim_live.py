"""The real live loop (demo.live) against sim.SimArm: rehearses Friday's failure modes today."""
import json

import demo

SCHED = str(demo.HERE / "schedule.json")


def run(*extra):
    return demo.main(["run", "--sim", "--max", "30", "--schedule", SCHED, *extra])


def placed(inv):
    return sum(inv.placed.values())


def test_clean_run_fills_the_week():
    inv = run()
    assert placed(inv) == 9 and "nothing, schedule complete" in inv.summary()


def test_wrong_wrist_sign_stops_early_instead_of_burning_the_run(capsys):
    inv = run("--sim-theta-sign", "-1")
    out = capsys.readouterr().out
    assert "STOPPED: 3 misses in a row" in out and placed(inv) < 9
    assert out.count("missed") <= 6  # stops early; before the fix it spent all 30 tries


def test_yaw_off_places_fewer_than_yaw_on():
    """T6 rehearsal: elongated pills need the wrist turned; without it the run stalls."""
    assert placed(run("--no-yaw")) < placed(run())


def test_random_slips_give_up_per_pill_but_keep_going(capsys):
    inv = run("--sim-slip", "0.3", "--sim-seed", "4")
    out = capsys.readouterr().out
    misses = [ln.split(" at ")[1].split(" (")[0] for ln in out.splitlines() if "missed" in ln]
    assert max(misses.count(m) for m in set(misses)) <= demo.MISSES_PER_PILL
    assert "STOPPED" not in out and placed(inv) >= 5


def test_every_placement_is_grip_verified_in_the_log():
    run()
    lines = [json.loads(x) for x in (demo.HERE / "logs" / "sim-inventory.jsonl").read_text().splitlines()]
    assert lines and all(e.get("grip_verified") is True for e in lines if e.get("event") == "placed")


def test_lite_gripper_confirms_by_photo_and_fills_the_week():
    assert placed(run("--sim-lite")) == 9


def test_lite_wrong_sign_stops_on_unconfirmed_picks(capsys):
    inv = run("--sim-lite", "--sim-theta-sign", "-1")
    assert "STOPPED: 3 unconfirmed picks in a row" in capsys.readouterr().out and placed(inv) < 9


def test_lite_slips_are_retracted_not_counted(capsys):
    """A pick the photo cannot confirm must not stay in the inventory sent to the caretaker."""
    inv = run("--sim-lite", "--sim-slip", "0.3", "--sim-seed", "4")
    out = capsys.readouterr().out
    lines = [json.loads(x) for x in (demo.HERE / "logs" / "sim-inventory.jsonl").read_text().splitlines()]
    retracted = sum(e["event"] == "retracted" for e in lines)
    assert retracted == out.count("NOT confirmed") > 0
    assert placed(inv) == sum(e["event"] == "placed" for e in lines) - retracted
