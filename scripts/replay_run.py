"""Replay a hand-demonstrated run joint for joint: the hand's own approach, grab, carry, release and lid sweep.

usage: python scripts/replay_run.py <run_dir> [--picks 3,4,5,6] [--speed 30] [--dry-run]
The jaw closes at each labelled grasp time and opens at each release time (labels.json). Wrist values recorded
before the 24 Oct power-cycle read one turn low and are corrected. A pick whose recorded path leaves the servos'
calibrated limits is refused before anything moves. HARDWARE-ONLY unless --dry-run.
"""
import argparse
import asyncio
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import box
from linear import calibrated

NO_LIDS = False
OFFSETS = Path(__file__).resolve().parent.parent / "runs" / "grip_offsets.json"  # learned per-pill grab offsets (mm)
SEARCH_MM = 4.0
DESCEND_MM = 40.0
MAX_CLAMP_DEG = 12.0  # a bigger clamp would bend the path too far from the hand's
LEAD_S = 4.0      # replay this much of the hand's approach before each grab
OPEN_PCT = 30.0
CHUNK = 60        # waypoints per move_through call
SAFE_Z = 130.0    # claw-tip height for every empty or between-segment move: clears the standing lids (top ~72)
HELD_MIN = 7.0    # tablets read 10.5-10.9% held in the demo and 8.7-9.1% in today's robot grabs; empty < 2
DROP_OPEN_PCT = 20.0


def load(run: Path):
    rows = list(csv.DictReader((run / "samples.csv").open()))
    t0 = float(rows[0]["unix_time"])
    pts = [(float(r["unix_time"]) - t0, [float(r[f"F{k}"]) for k in range(4)] +
            [float(r["F4"]) + (360.0 if float(r["F4"]) < -200 else 0.0)]) for r in rows]
    return pts, json.loads((run / "labels.json").read_text())


def window(pts, a, b):
    return [q for t, q in pts if a <= t <= b]


def plan(run: Path, picks):
    kin = calibrated(box.Kinematics())
    pts, labels = load(run)
    segs = [s for s in labels["segments"] if s["label"] == "pick"]
    out = []
    for i in picks:
        s = segs[i]
        approach = window(pts, s["grasp_t"] - LEAD_S, s["grasp_t"])
        carry = window(pts, s["grasp_t"], s["release_t"])
        grab = approach[-1]
        if any(not kin.limits[j][0] + 0.5 <= grab[j] <= kin.limits[j][1] - 0.5 for j in range(5)):
            raise SystemExit(f"pick {i} ({s['pill']}): the grab pose itself is outside the calibrated limits: refused")
        # the hand sometimes swung a joint past its servo stop on the way; the module would clamp it anyway,
        # so clamp here too and report by how much, refusing anything beyond MAX_CLAMP_DEG
        clamped = []
        for path in (approach, carry):
            worst = 0.0
            for q in path:
                for j in range(5):
                    lo, hi = kin.limits[j][0] + 0.5, kin.limits[j][1] - 0.5
                    v = min(max(q[j], lo), hi)
                    worst = max(worst, abs(v - q[j]))
                    q[j] = v
            clamped.append(round(worst, 1))
        if max(clamped) > MAX_CLAMP_DEG:
            raise SystemExit(f"pick {i} ({s['pill']}): the recorded path passes {max(clamped)} deg beyond a servo stop: refused")
        out.append((s, approach, carry, clamped))
    sweep = window(pts, *next(s for s in labels["segments"] if s["label"] == "lid_sweep")["t"])
    worst = 0.0
    for q in sweep:
        for j in range(5):
            v = min(max(q[j], kin.limits[j][0] + 0.5), kin.limits[j][1] - 0.5)
            worst, q[j] = max(worst, abs(v - q[j])), v
    print(f"lid sweep clamped by up to {worst:.1f} deg")
    return out, sweep


async def run(run_dir: Path, picks, speed, dry):
    steps, sweep = plan(run_dir, picks)
    for s, a, c, cl in steps:
        print(f"{s['pill']:17s} -> {s['day']}: approach {len(a)} pts, carry {len(c)} pts, clamped by up to {cl} deg")
    print(f"lid sweep: {len(sweep)} pts")
    if dry:
        return
    from viam.components.arm import Arm
    from viam.components.gripper import Gripper
    from viam.proto.component.arm import JointPositions, MoveOptions
    from armctl import connect, wait_arrival

    home = json.loads((Path(__file__).resolve().parent.parent / "taught_joints.json").read_text())["home"]
    robot = await connect()
    arm, jaw = Arm.from_robot(robot, "follower-arm"), Gripper.from_robot(robot, "follower-gripper")

    async def through(path, spd):
        # long waypoint lists time out as one call (389 points, run 11), so send them in chunks
        dense = box.densify(path)
        for k in range(0, len(dense), CHUNK):
            part = dense[k:k + CHUNK]
            await arm.move_through_joint_positions([JointPositions(values=q) for q in part],
                                                   options=MoveOptions(max_vel_degs_per_sec=spd))
        await wait_arrival(arm, dense[-1], spd)

    async def jaw_set(pct, settle=0.8):
        await jaw.do_command({"command": "set_position", "percentage": pct})
        await asyncio.sleep(settle)
        return float((await jaw.do_command({"command": "get_position"}))["position_percentage"])

    async def grip():
        """Close slowly so the jaws seat on the pill, settle, then command closed again before the lift. The jaw is
        never eased off (day-1 pick.py backed off 1%), so the servo keeps squeezing at its limit through the carry."""
        await jaw.do_command({"command": "set_motion_params", "speed": 15.0, "acceleration": 50.0})
        try:
            held = await jaw_set(0.0, settle=1.2)
            await jaw.do_command({"command": "set_position", "percentage": 0.0})
            return held
        finally:
            await jaw.do_command({"command": "set_motion_params", "speed": 30.0, "acceleration": 50.0})

    kin = calibrated(box.Kinematics())
    from linear import ik as ik_h, line

    async def hop_to(q_target, spd):
        """Up to SAFE_Z where the claw is, across at SAFE_Z, then into q_target: never low over the box."""
        q_now = list((await arm.get_joint_positions()).values)
        a, _ = kin.tip(q_now)
        b, _ = kin.tip(q_target)
        h = q_now[4] - q_now[0]
        up = line(kin, list(a), [a[0], a[1], max(SAFE_Z, a[2])], q_now, h) if a[2] < SAFE_Z else [q_now]
        hb = q_target[4] - q_target[0]
        over = ik_h(kin, [b[0], b[1], max(SAFE_Z, b[2])], up[-1], hb)
        await through(up + [over, q_target], spd)

    try:
        await through([home], speed)
        import numpy as _np
        from linear import ik as ik_h, line as line_h
        offsets = json.loads(OFFSETS.read_text()) if OFFSETS.exists() else {}
        for s, approach, carry, _ in steps:
            await jaw_set(OPEN_PCT)
            grab_q = approach[-1]
            (gx, gy, gz), axis = kin.tip(grab_q)
            # 4 Hz samples can land just before the hand reached the bottom: use the lowest point around the grab
            near = approach[-3:] + carry[:4]
            low = min(near, key=lambda q: kin.tip(q)[0][2])
            (gx, gy, gz), axis = kin.tip(low)
            gh = grab_q[4] - grab_q[0]
            radial = _np.array([gx, gy]) - kin.pan_axis()[:2]
            radial /= _np.linalg.norm(radial)
            tilt = float(_np.degrees(_np.arccos(_np.clip(-axis[2], -1, 1))))
            glean = tilt if axis[:2] @ radial > 0 else -tilt
            leans = (glean, 0.0, 5.0, 10.0, 15.0, 20.0)
            learned = offsets.get(s["pill"], [0.0, 0.0])
            # search pattern around the learned spot: centre first, then 4 mm each way, each try 1 mm deeper
            tries = [(0, 0), (SEARCH_MM, 0), (-SEARCH_MM, 0), (0, SEARCH_MM), (0, -SEARCH_MM)]
            held, used = 0.0, None
            for k, (dx, dy) in enumerate(tries):
                tx, ty, tz = gx + learned[0] + dx, gy + learned[1] + dy, gz - 1.0 * k
                above = ik_h(kin, [tx, ty, tz + DESCEND_MM], grab_q, gh, leans)
                down = line_h(kin, [tx, ty, tz + DESCEND_MM], [tx, ty, tz], above, gh, leans)
                await hop_to(above, speed)
                await through(down, 20.0)
                held = await grip()
                if held >= HELD_MIN:
                    used = [round(learned[0] + dx, 1), round(learned[1] + dy, 1)]
                    break
                print(f"{s['pill']:17s} try {k + 1}: jaw {held:.1f}% (empty), shifting", flush=True)
                await jaw_set(OPEN_PCT)
                await through(down[::-1], 20.0)
            if used is None:
                print(f"{s['pill']:17s} not found in {len(tries)} tries: skipped", flush=True)
                await jaw_set(OPEN_PCT)
                continue
            offsets[s["pill"]] = used
            OFFSETS.write_text(json.dumps(offsets, indent=1))
            await through(down[::-1], 20.0)
            print(f"{s['pill']:17s} grabbed, jaw {held:.1f}% (offset {used} mm, saved)", flush=True)
            # join the hand's carry where it is already up high, instead of dropping back to the grab height
            high = next((i for i, q in enumerate(carry) if kin.tip(q)[0][2] > tz + DESCEND_MM), len(carry) - 1)
            await hop_to(carry[high], speed)
            await through(carry[high:], speed)
            await jaw_set(DROP_OPEN_PCT)
            print(f"{s['pill']:17s} released over {s['day']}", flush=True)
        if NO_LIDS:
            await hop_to(home, speed)
            print("picks done; lids skipped", flush=True)
            return
        await jaw_set(0.0)
        await hop_to(sweep[0], speed)
        await through(sweep, speed)
        print("lid sweep done", flush=True)
        await hop_to(home, speed)
    except BaseException:
        await arm.stop()
        raise
    finally:
        await robot.close()
    if NO_LIDS:
        return
    # press every lid down at its front edge after the sweep: the sweep folds them, the press latches them
    import subprocess
    subprocess.run([sys.executable, "-B", str(Path(__file__).resolve().parent / "press_lids.py"),
                    str(run_dir / "script.json")], check=False)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--picks", default="3,4,5,6")
    ap.add_argument("--speed", type=float, default=30.0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-lids", action="store_true", help="picks and drops only")
    a = ap.parse_args()
    NO_LIDS = a.no_lids
    if a.dry_run:
        asyncio.run(run(a.run_dir, [int(v) for v in a.picks.split(",")], a.speed, True))
        sys.exit(0)
    # every live run records itself: joints, tip, jaw and wrist video, then an MP4 on the Desktop
    import signal
    import subprocess
    import time
    here = Path(__file__).resolve().parent
    out = here.parent / "runs" / f"{time.strftime('%Y-%m-%d')}-robot-run-{time.strftime('%H%M')}"
    rec = subprocess.Popen([sys.executable, "-B", str(here / "record_demo.py"), "900", str(out)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(4)
    try:
        asyncio.run(run(a.run_dir, [int(v) for v in a.picks.split(",")], a.speed, False))
    finally:
        rec.send_signal(signal.SIGINT)
        rec.wait(timeout=15)
        subprocess.run([sys.executable, "-B", str(here / "make_video.py"), str(out)], check=False)
