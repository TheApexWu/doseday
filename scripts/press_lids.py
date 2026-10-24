"""Press each closed lid down at its front edge so it latches, the way the demo-04 hand sweep did.

usage: python scripts/press_lids.py <script.json> [days, default sun-sat] [--dry-run]
Press points come from the hand sweep's low points (labels.json): claw vertical, tip at the lid's front edge
(x 205-227 mm) on the day's centre line, pressed to z 13-18. Torque is capped while pressing, as in box.run_stroke.
HARDWARE-ONLY unless --dry-run.
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import box
from linear import BOX_HEADING, ik, line

PRESS_X = 212.0       # mid of the hand's press points (205-227)
PRESS_Z = 15.0        # hand pressed to 13-18
ABOVE_Z = 55.0
PRESS_SPEED = 15.0    # below 12 the servos misbehave
MOVE_SPEED = 30.0
PRESS_TORQUE = 600    # of 1000: day-1 stroke value; enough to latch, capped so a stuck lid stalls the arm
HOLD_S = 0.4


def plan(script, days):
    """Per day: (day, path along the box to above the lid, straight press down). Claw locked square to the box."""
    kin, fit = box.Kinematics(), script["box_fit"]
    seed = json.loads((Path(__file__).resolve().parent.parent / "taught_joints.json").read_text())["home"]
    out, prev = [], None
    for d in days:
        y = fit["sun_centre_y"] + fit["pitch_y"] * box.DAYS.index(d)
        top = [PRESS_X, y, ABOVE_Z]
        travel = line(kin, prev, top, seed, BOX_HEADING) if prev else [ik(kin, top, seed, BOX_HEADING)]
        down = line(kin, top, [PRESS_X, y, PRESS_Z], travel[-1], BOX_HEADING, leans=(0, 5, 10))
        out.append((d, travel, down))
        seed, prev = travel[-1], top
    return out


async def run(script, days, dry):
    steps = plan(script, days)
    for d, travel, down in steps:
        print(f"{d}: {len(travel)} travel pts, press {len(down)} pts, at lid {[round(v, 1) for v in travel[-1]]}")
    if dry:
        return
    from viam.components.arm import Arm
    from viam.components.gripper import Gripper
    from viam.proto.component.arm import JointPositions, MoveOptions
    from armctl import connect, wait_arrival

    robot = await connect()
    arm = Arm.from_robot(robot, "follower-arm")
    try:
        await Gripper.from_robot(robot, "follower-gripper").do_command({"command": "set_position", "percentage": 0})
        await asyncio.sleep(0.8)
        async def through(path, speed, timeout=None):
            call = arm.move_through_joint_positions([JointPositions(values=q) for q in path],
                                                    options=MoveOptions(max_vel_degs_per_sec=speed))
            await (asyncio.wait_for(call, timeout) if timeout else call)
            await wait_arrival(arm, path[-1], speed, timeout=timeout)

        for d, travel, down in steps:
            await through(travel, MOVE_SPEED)
            await arm.do_command({"command": "set_torque_limit", "value": PRESS_TORQUE})
            try:
                await through(down, PRESS_SPEED, timeout=6.0)
            except asyncio.TimeoutError:
                await arm.stop()  # a latched lid stops the claw short of PRESS_Z: that is the press
            await asyncio.sleep(HOLD_S)
            z = (await arm.get_end_position()).z
            await arm.do_command({"command": "set_torque_limit", "value": 1000})
            await through(down[::-1], MOVE_SPEED)
            print(f"{d}: pressed (wrist z at the press {z:.0f})", flush=True)
    except BaseException:
        await arm.stop()
        raise
    finally:
        await arm.do_command({"command": "set_torque_limit", "value": 1000})
        await arm.do_command({"set_speed": 50})
        await robot.close()


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--dry-run"]
    days = args[1].split(",") if len(args) > 1 else box.DAYS
    asyncio.run(run(json.loads(Path(args[0]).read_text()), days, "--dry-run" in sys.argv))
