"""Replay one time window of a recorded run's joint path (e.g. the lid sweep), wrist roll held at its current value.

usage: python scripts/replay_segment.py <samples.csv> <t_start_s> <t_end_s> [speed]
All five joints come from the recording, the roll corrected for the old one-turn offset, so the claw turns exactly
as the hand's did. The arm first rises above the segment's start so it never drags into a lid.
HARDWARE-ONLY.
"""
import asyncio
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import box

ABOVE_MM = 60.0
HOLD_BELOW_Z = 22.0   # tip height under which a local low is a press (closed lid tops at 28)
HOLD_S = 0.6


async def main(path: Path, t0: float, t1: float, speed: float):
    from viam.components.arm import Arm
    from viam.components.gripper import Gripper
    from viam.proto.component.arm import JointPositions, MoveOptions
    from armctl import connect, wait_arrival

    rows = list(csv.DictReader(path.open()))
    start = float(rows[0]["unix_time"])
    # recordings before the 24 Oct wrist power-cycle read the roll one full turn low (-468 for -108)
    seg = [[float(r[f"F{k}"]) for k in range(4)] + [float(r["F4"]) + (360.0 if float(r["F4"]) < -200 else 0.0)]
           for r in rows if t0 <= float(r["unix_time"]) - start <= t1]
    if len(seg) < 2:
        sys.exit("no samples in that window")
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from linear import calibrated
    kin = calibrated(box.Kinematics())
    robot = await connect()
    arm = Arm.from_robot(robot, "follower-arm")
    try:
        path_q = seg
        tip0, _ = kin.tip(path_q[0])
        for lean in (0, 10, 20, 30, 40, -10, -20):
            try:
                above = kin.ik([tip0[0], tip0[1], tip0[2] + ABOVE_MM], float(lean), path_q[0])[:4] + [path_q[0][4]]
                break
            except ValueError as e:
                err = e
        else:
            sys.exit(f"no reachable point above the segment start: {err}")
        # the claw pushes lids shut as one closed block; open jaws straddle a lid instead (24 Oct)
        await Gripper.from_robot(robot, "follower-gripper").do_command({"command": "set_position", "percentage": 0})
        await asyncio.sleep(1.0)
        await arm.do_command({"set_speed": speed})
        await arm.move_to_joint_positions(JointPositions(values=above))
        await wait_arrival(arm, above, speed)
        # split at the hand's pressing lows (tip below HOLD_BELOW_Z, lowest within +-2 samples) and hold each one,
        # so every lid gets the sustained push the hand gave it instead of a fly-through
        tips_z = [kin.tip(q)[0][2] for q in path_q]
        lows = [i for i in range(2, len(path_q) - 2)
                if tips_z[i] < HOLD_BELOW_Z and tips_z[i] <= min(tips_z[i - 2:i + 3])]
        cuts = [0] + lows + [len(path_q) - 1]
        await arm.move_to_joint_positions(JointPositions(values=path_q[0]))
        await wait_arrival(arm, path_q[0], speed)
        for a_i, b_i in zip(cuts, cuts[1:]):
            dense = box.densify(path_q[a_i:b_i + 1])
            for k in range(0, len(dense), 60):  # one long call times out (389 points, run 11)
                await arm.move_through_joint_positions([JointPositions(values=q) for q in dense[k:k + 60]],
                                                       options=MoveOptions(max_vel_degs_per_sec=speed))
            await wait_arrival(arm, dense[-1], speed, timeout=4.0)
            if b_i in lows:
                await asyncio.sleep(HOLD_S)
        print(f"held {len(lows)} presses", flush=True)
        print(f"replayed {len(seg)} samples ({t0}-{t1} s) as {len(dense)} waypoints", flush=True)
    except BaseException:
        await arm.stop()
        raise
    finally:
        await arm.do_command({"set_speed": 50})
        await robot.close()


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1]), float(sys.argv[2]), float(sys.argv[3]),
                     float(sys.argv[4]) if len(sys.argv) > 4 else 30.0))
