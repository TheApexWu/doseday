"""Replay a recorded pick-and-drop run from its cleaned script, checking every grab and recovering from misses.

usage: python scripts/scripted_pick.py <script.json> [--only N] [--dry-run]

Pick spots and drop days come from the script (a hand demo cleaned by its README). A grab counts as held when the
closed jaw reads at or above the pill type's floor (hand-demo values: tablets 10.5-10.9%, capsules 3.7-4.7%,
empty 1.5-1.7%). The jaw stays commanded closed through the lift, so a pill that slips out lets it close further
and the post-lift read catches it. A miss is retried lower, then shifted, then (capsules) with the claw turned
90 deg, then skipped and logged. The wrist roll is held at its current reading except for that capsule retry.
HARDWARE-ONLY unless --dry-run.
"""
import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import box
sys.path.insert(0, str(Path(__file__).resolve().parent))
from box_obstacle import check_path
from linear import calibrated, ik as ik_h, line

MIN_CLEAR_MM = 5.0

TRANSIT_Z = 120.0      # claw-tip height between spots: clears the open lids
DROP_Z = 40.0          # tip height at release: demo-04 hand releases at 36-45 (Mon, Wed, Sun, cream), lids at z 28
DROP_IN_MM = 0.0       # release x is BOX_FRONT_X itself (the measured mean)
BOX_FRONT_X = 204.0    # mean release x of the clean demo-04 drops (190-214)
ENTRY_BACK_MM = 40.0   # hand drops slid the last 15-40 mm in from the front ...
ENTRY_UP_MM = 5.0      # ... nearly level (within 4 mm), so the claw never comes down onto a lid
DROP_LEAN = 8.0        # hand drops tilted 5-13 deg away from the arm at release
DROP_OPEN_PCT = 20.0   # wide enough to release a tablet (held ~10%), narrow enough to miss the neighbouring lids
BOX_X = 205.0          # compartment centres' distance out, mean of the five camera-confirmed demo-04 drops (195-213);
                       # per-step hand releases scattered (cream at 162 landed in front of the box, 24 Oct)
DOWN_FLOOR_Z = -18.0   # never command the tip below this (hand-demo grabs reached -17)
OPEN_PCT = 30.0
HELD_MIN = {"capsule": 3.0, "tablet": 7.0}
CARRY_SPEED = 40.0
DESCEND_SPEED = 30.0   # below ~27 the straight-down move drifts (run 01)
LEANS = (0, 10, 20, 30, 40)


def solve(kin, tip, seed, wrist, leans=LEANS):
    for lean in leans:
        try:
            q = kin.ik(tip, float(lean), seed)
            return q[:4] + [wrist], lean
        except ValueError as e:
            err = e
    raise ValueError(f"no reach for tip {tip}: {err}")


def day_tip(script, step):
    fit, days = script["box_fit"], box.DAYS
    x = BOX_FRONT_X + DROP_IN_MM
    y = fit["sun_centre_y"] + fit["pitch_y"] * days.index(step["drop_day"])
    return [x, y, DROP_Z]


def attempts(step):
    """(label, tip offset dx, dy, dz, wrist turn) per try."""
    x, y, z = step["pick_tip_mm"]
    z = max(z + 2.0, DOWN_FLOOR_Z + 2.0)
    tries = [("first", 0, 0, 0, 0), ("lower", 0, 0, -2, 0), ("shift", -5, 0, -2, 0)]
    if "capsule" in step["pill"]:
        tries.append(("turned", 0, 0, -2, 90))
    return [(lab, [x + dx, y + dy, max(z + dz, DOWN_FLOOR_Z)], turn) for lab, dx, dy, dz, turn in tries]


async def run(script, only, dry):
    kin = calibrated(box.Kinematics())
    seed = json.loads((Path(__file__).resolve().parent.parent / "taught_joints.json").read_text())["home"]
    log_path = Path("logs") / f"scripted-pick-{time.strftime('%H%M%S')}.jsonl"
    steps = [s for i, s in enumerate(script["steps"]) if only is None or i == only]

    if dry:
        wrist = -108.0
        for s in steps:
            for lab, tip, turn in attempts(s):
                q, lean = solve(kin, tip, seed, wrist + turn)
                print(f"{s['pill']:17s} {lab:6s} tip {[round(v) for v in tip]} lean {lean:2d} -> {q}")
            dx, dy, dz = day_tip(script, s)
            for lab, tip, leans in (("entry", [dx - ENTRY_BACK_MM, dy, dz + ENTRY_UP_MM], (DROP_LEAN, 0, 10, 14, 20)),
                                    ("drop", [dx, dy, dz], (DROP_LEAN, 0, 10, 14))):
                q, lean = solve(kin, tip, seed, wrist, leans)
                print(f"{s['pill']:17s} {lab:6s} {s['drop_day']} tip {[round(v) for v in tip]} lean {lean:2.0f} -> {q}")
        return

    from viam.components.arm import Arm
    from viam.components.gripper import Gripper
    from viam.proto.component.arm import JointPositions, MoveOptions
    from armctl import connect, joint_limits, wait_arrival

    robot = await connect()
    arm, jaw = Arm.from_robot(robot, "follower-arm"), Gripper.from_robot(robot, "follower-gripper")
    log_path.parent.mkdir(exist_ok=True)

    def log(entry):
        with log_path.open("a") as f:
            f.write(json.dumps({"t": round(time.time(), 3), **entry}) + "\n")

    async def go(q, speed, label):
        await arm.do_command({"set_speed": speed})
        await arm.move_to_joint_positions(JointPositions(values=q))
        if not await wait_arrival(arm, q, speed):
            now = (await arm.get_joint_positions()).values
            if await arm.is_moving() or max(abs(a - b) for a, b in zip(now, q)) > 2.0:
                raise RuntimeError(f"{label}: did not arrive")

    async def carry(path, speed):
        """One continuous move through densified waypoints: no stop between lift, carry and drop hover."""
        dense = box.densify(path)
        await arm.move_through_joint_positions([JointPositions(values=q) for q in dense],
                                               options=MoveOptions(max_vel_degs_per_sec=speed))
        await wait_arrival(arm, dense[-1], speed)

    async def jaw_set(pct):
        await jaw.do_command({"command": "set_position", "percentage": pct})
        await asyncio.sleep(0.8)
        return float((await jaw.do_command({"command": "get_position"}))["position_percentage"])

    try:
        wrist = (await arm.get_joint_positions()).values[4]
        lims = await joint_limits(arm)
        if not lims[4][0] + 5 <= wrist <= lims[4][1] - 5:
            sys.exit(f"wrist reads {wrist:.1f}, outside {lims[4]}: re-zero it first")
        results = []
        await go(seed, CARRY_SPEED, "home")  # default position: the taught home, inside every calibrated limit
        for s in steps:
            kind = "capsule" if "capsule" in s["pill"] else "tablet"
            x, y, _ = s["pick_tip_mm"]
            held_try = None
            for lab, tip, turn in attempts(s):
                h = s.get("grasp_heading", -110.0) + turn
                try:
                    above_w = ik_h(kin, [tip[0], tip[1], TRANSIT_Z], seed, h, flip=True)
                    h = above_w[4] - above_w[0]  # the grip heading actually chosen (possibly flipped 180)
                    descent = line(kin, [tip[0], tip[1], TRANSIT_Z], tip, above_w, h, leans=(0, 5, 10, 15, 20, 30, 40))
                except ValueError as e:
                    print(f"{s['pill']:17s} {lab:6s} unreachable inside the calibrated limits: skipped", flush=True)
                    log({"pill": s["pill"], "try": lab, "unreachable": str(e)[:160]})
                    break
                for name, path in (("to pick", box.densify([(await arm.get_joint_positions()).values, above_w])), ("descent", descent)):
                    g, part, i = check_path(kin, path, lids_open=True)
                    if g < MIN_CLEAR_MM:
                        sys.exit(f"{s['pill']} {lab} {name}: claw would come within {g:.0f} mm of the {part}; nothing moved")
                down, lean = descent[-1], 0
                await jaw_set(OPEN_PCT)
                await go(above_w, CARRY_SPEED, "above pick")
                await carry(descent, DESCEND_SPEED)
                closed = await jaw_set(0.0)
                await carry(descent[::-1], DESCEND_SPEED)
                after = float((await jaw.do_command({"command": "get_position"}))["position_percentage"])
                ok = closed >= HELD_MIN[kind] and after >= HELD_MIN[kind]
                log({"pill": s["pill"], "try": lab, "tip": tip, "lean": lean, "jaw_closed": closed, "jaw_after_lift": after, "held": ok})
                print(f"{s['pill']:17s} {lab:6s} jaw {closed:4.1f}% -> {after:4.1f}% after lift: {'HELD' if ok else 'miss'}", flush=True)
                if ok:
                    held_try = lab
                    break
            if held_try is None:
                await jaw_set(OPEN_PCT)
                results.append((s["pill"], "skipped"))
                continue
            dx, dy, dz = day_tip(script, s)
            hd = script.get("drop_heading", -110.0)
            entry_high = ik_h(kin, [dx - ENTRY_BACK_MM, dy, TRANSIT_Z], above_w, hd)
            lower = line(kin, [dx - ENTRY_BACK_MM, dy, TRANSIT_Z], [dx - ENTRY_BACK_MM, dy, dz + ENTRY_UP_MM], entry_high, hd)
            slide = line(kin, [dx - ENTRY_BACK_MM, dy, dz + ENTRY_UP_MM], [dx, dy, dz], lower[-1], hd, leans=(DROP_LEAN, 5, 10, 0, 14))
            approach = box.densify([above_w, entry_high]) + lower + slide
            g, part, i = check_path(kin, approach[:-len(slide) // 3], lids_open=True)  # the slide's last third is the release, meant to be near the lid tops
            if g < MIN_CLEAR_MM:
                sys.exit(f"{s['pill']} drop: claw would come within {g:.0f} mm of the {part} (waypoint {i}); nothing moved")
            await carry(approach, CARRY_SPEED)
            await jaw_set(DROP_OPEN_PCT)
            await carry((lower + slide)[::-1], CARRY_SPEED)
            log({"pill": s["pill"], "dropped": s["drop_day"], "try": held_try})
            results.append((s["pill"], f"{s['drop_day']} ({held_try})"))
        await go(seed, CARRY_SPEED, "home")
        print("results:", results, "| log", log_path)
    except BaseException:
        await arm.stop()
        raise
    finally:
        await arm.do_command({"set_speed": 50})
        await robot.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("script", type=Path)
    ap.add_argument("--only", type=int, help="run one step (0-based) of the script")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    asyncio.run(run(json.loads(a.script.read_text()), a.only, a.dry_run))
