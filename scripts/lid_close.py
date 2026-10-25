"""Close every lid the way Alex demonstrated (lid-teach-13): land behind the lid, drag it down toward the arm with
the claw trailing, and hold the push for as long as he did. Joint-for-joint replay of the demonstration window, with
each hold reproduced as a stop of the same length (at least MIN_HOLD_S) at full motor force.

usage: python scripts/lid_close.py [run_dir] [t_start] [t_end] [--dry-run]
HARDWARE-ONLY unless --dry-run.
"""
import asyncio
import csv

import numpy as np
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import box
from linear import calibrated, ik, line

RUN = Path(__file__).resolve().parent.parent / "runs" / "2026-10-24-lid-teach-13"
WINDOW = (11.0, 55.0)      # the lid phase of the demonstration
HOLD_BELOW_Z = 24.0        # a hold is the tip staying put below this height ...
HOLD_STILL_MM = 3.0        # ... moving less than this between samples ...
HOLD_MIN_S = 0.8           # ... for at least this long
MIN_HOLD_S = 1.5           # replayed holds last at least this long
PRESS_BELOW_MM = 2.0       # then this much further: 5 mm below the hand in total (deeper stalls the motors at full current)
LIFT_MM = 20.0             # rise before straightening the claw, and after the push
STRAIGHTEN_STEPS = 6        # claw goes from the drag's tilt to vertical in this many steps, tip kept on the lid
SINK_PER_STEP_MM = 0.5      # and pressed 0.5 mm deeper per step so the lid never springs back
# lid centres along the box: straight-line fit through the hand's Mon-Sat pushes in lid-teach-13 (each within 5 mm);
# the hand's Sunday push ended 11 mm toward Monday at the end of a diagonal drag, so every push snaps to this line
LID_SUN_Y, LID_PITCH_Y = 76.7, -30.6
LID_CENTRE_X = 219.0       # lid middle front-to-back: the hand's drags land at x 234-241 (back) and end at 198-207 (front edge)
PUSH_TARGET_Z = -11.0      # servos push in proportion to how far short of the target they are: aim deep, as day 1's
                           # stroke did (box.py STROKE "press" at -11, 39 mm under the lid tops), which latched Tue/Wed
PUSH_TORQUE = 600          # of 1000 during the push: bounds the force and the current (day-1 stroke value)
PUSH_HOLD_S = 2.0
PUSH_MIN_X = 210.0         # a vertical claw closer than this needs the elbow past its 35 deg stop; still on the lid
SAFE_Z = 130.0
SPEED = 50.0               # Alex: fast and decisive, his drags peak at 110-175 mm/s
CHUNK = 60


def lid_centre(y: float) -> float:
    k = min(6, max(0, round((y - LID_SUN_Y) / LID_PITCH_Y)))
    return LID_SUN_Y + k * LID_PITCH_Y


def plan(run: Path, t0: float, t1: float):
    kin = calibrated(box.Kinematics())
    rows = list(csv.DictReader((run / "samples.csv").open()))
    s0 = float(rows[0]["unix_time"])
    win = [(float(r["unix_time"]) - s0, [float(r[f"F{k}"]) for k in range(4)] +
            [float(r["F4"]) + (360.0 if float(r["F4"]) < -200 else 0.0)]) for r in rows
           if t0 <= float(r["unix_time"]) - s0 <= t1]
    for _, q in win:  # trim the few degrees the hand went past a servo stop (2.6 deg wrist flex in lid-teach-13)
        for j in range(5):
            q[j] = min(max(q[j], kin.limits[j][0] + 0.5), kin.limits[j][1] - 0.5)
    tips = [kin.tip(q)[0] for _, q in win]
    holds, start = {}, None
    for k in range(1, len(win)):
        still = (tips[k][2] < HOLD_BELOW_Z and abs(tips[k][0] - tips[k - 1][0]) < HOLD_STILL_MM
                 and abs(tips[k][2] - tips[k - 1][2]) < HOLD_STILL_MM)
        if still and start is None:
            start = k - 1
        if not still and start is not None:
            if win[k - 1][0] - win[start][0] >= HOLD_MIN_S:
                holds[start] = max(MIN_HOLD_S, win[k - 1][0] - win[start][0])
            start = None
    return kin, [q for _, q in win], holds, tips


async def run(run_dir: Path, t0: float, t1: float, dry: bool):
    kin, path, holds, tips = plan(run_dir, t0, t1)
    for i, d in holds.items():
        q = path[i]
        (x0, y, z0), axis = kin.tip(q)
        h = q[4] - q[0]
        radial = np.array([x0, y]) - kin.pan_axis()[:2]
        radial /= np.linalg.norm(radial)
        tilt = float(np.degrees(np.arccos(np.clip(-axis[2], -1, 1))))
        lean0 = tilt if axis[:2] @ radial > 0 else -tilt
        xt, qk, yt = LID_CENTRE_X, q, lid_centre(y)
        for k in range(1, STRAIGHTEN_STEPS + 1):
            f = k / STRAIGHTEN_STEPS
            qk = kin.ik([x0 + (xt - x0) * f, y + (yt - y) * f, z0 - SINK_PER_STEP_MM * k], lean0 * (1 - f), qk, heading=h)
        y_hand, y = y, yt
        zf = z0 - SINK_PER_STEP_MM * STRAIGHTEN_STEPS - PRESS_BELOW_MM
        line(kin, [xt, y, z0 - SINK_PER_STEP_MM * STRAIGHTEN_STEPS], [xt, y, zf], qk, h, leans=(0,))
        print(f"{box.DAYS[round((y - LID_SUN_Y) / LID_PITCH_Y)]}: hand pushed at y {y_hand:4.0f}, push at lid centre ({xt:.0f}, {y:.1f}); drag ends at tilt {lean0:+.0f} deg, straighten on the lid, vertical push to {zf:.0f} mm, hold {d:.1f} s")
    if dry:
        return
    from viam.components.arm import Arm
    from viam.components.gripper import Gripper
    from viam.proto.component.arm import JointPositions, MoveOptions
    from armctl import connect, wait_arrival

    robot = await connect()
    arm = Arm.from_robot(robot, "follower-arm")

    async def through(qs):
        dense = box.densify(qs)
        for k in range(0, len(dense), CHUNK):
            await arm.move_through_joint_positions([JointPositions(values=q) for q in dense[k:k + CHUNK]],
                                                   options=MoveOptions(max_vel_degs_per_sec=SPEED))
        await wait_arrival(arm, dense[-1], SPEED, timeout=4.0)

    try:
        await Gripper.from_robot(robot, "follower-gripper").do_command({"command": "set_position", "percentage": 0})
        await arm.do_command({"command": "set_torque_limit", "value": 1000})
        first = path[0]
        tip0, _ = kin.tip(first)
        above = ik(kin, [tip0[0], tip0[1], SAFE_Z], first, first[4] - first[0])
        await through([above, first])
        keep = sorted(holds)[:MAX_LIDS] if MAX_LIDS else sorted(holds)
        cuts = keep + ([len(path) - 1] if not MAX_LIDS else [])
        prev = 0
        for c in cuts:
            if c > prev:
                await through(path[prev:c + 1])
            if c in keep:
                # the drag folded the lid and is holding it down: never lift here (the lid springs back). Keep the tip
                # on the lid and straighten the claw to vertical in small steps, sinking 1 mm per step so the pressure
                # never lets up, then push straight down and hold
                q = path[c]
                (x0, y, z0), axis = kin.tip(q)
                h = q[4] - q[0]
                radial = np.array([x0, y]) - kin.pan_axis()[:2]
                radial /= np.linalg.norm(radial)
                tilt = float(np.degrees(np.arccos(np.clip(-axis[2], -1, 1))))
                lean0 = tilt if axis[:2] @ radial > 0 else -tilt
                xt = LID_CENTRE_X
                yt = lid_centre(y)
                straighten, qk = [], q
                for k in range(1, STRAIGHTEN_STEPS + 1):
                    f = k / STRAIGHTEN_STEPS
                    qk = kin.ik([x0 + (xt - x0) * f, y + (yt - y) * f, z0 - SINK_PER_STEP_MM * k], lean0 * (1 - f), qk, heading=h)
                    straighten.append(qk)
                y = yt
                zs = z0 - SINK_PER_STEP_MM * STRAIGHTEN_STEPS
                down = line(kin, [xt, y, zs], [xt, y, PUSH_TARGET_Z], straighten[-1], h, leans=(0,))
                await through([q] + straighten)
                await arm.do_command({"command": "set_torque_limit", "value": PUSH_TORQUE})
                try:
                    try:
                        await asyncio.wait_for(through(down), 6.0)
                    except asyncio.TimeoutError:
                        pass  # the lid stops the claw short of the target: that is the push
                    await asyncio.sleep(max(PUSH_HOLD_S, holds[c]))
                    z = (await arm.get_end_position()).z + 98.0 * -1.0
                finally:
                    await arm.do_command({"command": "set_torque_limit", "value": 1000})
                down = line(kin, [xt, y, max(z, PUSH_TARGET_Z)], [xt, y, zs], straighten[-1], h, leans=(0,))
                await through(down)
                z = zs
                up = line(kin, [xt, y, z], [xt, y, z + LIFT_MM], down[-1], h, leans=(0, 5, 10, 15, 20))
                await through(up)
                print(f"pushed at lid centre ({xt:.0f}, {y:.0f}) toward z {PUSH_TARGET_Z:.0f} at {PUSH_TORQUE / 10:.0f}% force, held {max(PUSH_HOLD_S, holds[c]):.1f} s", flush=True)
            prev = c
        last = path[-1]
        tip1, _ = kin.tip(last)
        await through([last, ik(kin, [tip1[0], tip1[1], SAFE_Z], last, last[4] - last[0])])
        print(f"closed: {len(holds)} holds", flush=True)
    except BaseException:
        await arm.stop()
        raise
    finally:
        await robot.close()


MAX_LIDS = 0

if __name__ == "__main__":
    if "--lids" in sys.argv:
        i = sys.argv.index("--lids")
        MAX_LIDS = int(sys.argv[i + 1])
        del sys.argv[i:i + 2]
    args = [a for a in sys.argv[1:] if a != "--dry-run"]
    run_dir = Path(args[0]) if args else RUN
    t0, t1 = (float(args[1]), float(args[2])) if len(args) > 2 else WINDOW
    asyncio.run(run(run_dir, t0, t1, "--dry-run" in sys.argv))
