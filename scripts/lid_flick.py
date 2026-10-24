"""Flick a lid shut: get behind its upper back face (lid_arc's lane), then snap only the wrist so the claw tip
whips toward the arm and slaps the lid over its hinge. Nothing else moves, so the box is not dragged.

usage: python scripts/lid_flick.py <day> [--dry-run]
HARDWARE-ONLY unless --dry-run.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import box
import lid_arc
from linear import ik, line

BEHIND_X, BEHIND_Z = 244.0, 40.0  # behind the lid: the 24 Oct flick from here shut Monday
FLICK_DEG = 40.0          # wrist-flex snap
FLICK_SPEED = 180.0       # deg/s: as fast as the servo will go


def plan(day):
    kin, steps = lid_arc.plan([day])
    _, y, approach, arc, *_ = steps[0]
    behind = ik(kin, [BEHIND_X, y, BEHIND_Z], arc[0], lid_arc.HEADING, (25.0, 30.0, 20.0, 35.0, 15.0))
    best = None
    lo, hi = kin.limits[3]
    for sign in (1, -1):  # the wrist direction that swings the tip toward the arm (smaller x)
        q = list(behind)
        q[3] = min(max(q[3] + sign * FLICK_DEG, lo + 0.5), hi - 0.5)
        lo, hi = kin.limits[3]
        if lo + 0.5 <= q[3] <= hi - 0.5:
            dx = kin.tip(q)[0][0] - kin.tip(behind)[0][0]
            if best is None or dx < best[0]:
                best = (dx, q)
    if best is None or best[0] >= 0:
        raise SystemExit(f"{day}: no wrist flick toward the arm fits the wrist limits")
    flick = best[1]
    # the flick shuts the lid; the latch needs a hard press at the front edge straight after
    y = kin.tip(behind)[0][1]
    above = ik(kin, [lid_arc.PRESS_X, y, 45.0], flick, lid_arc.HEADING, lid_arc.LEANS)
    press = line(kin, [lid_arc.PRESS_X, y, 45.0], [lid_arc.PRESS_X, y, lid_arc.PRESS_TARGET_Z], above, lid_arc.HEADING, (0, -5, 5, -10, 10))
    return kin, approach, behind, flick, above, press


async def run(day, dry):
    kin, approach, behind, flick, above, press = plan(day)
    a, b = kin.tip(behind)[0], kin.tip(flick)[0]
    print(f"{day}: behind lid at ({a[0]:.0f},{a[1]:.0f},{a[2]:.0f}); flick wrist {behind[3]:.0f} -> {flick[3]:.0f}, tip to ({b[0]:.0f},{b[2]:.0f})")
    if dry:
        return
    from viam.components.arm import Arm
    from viam.components.gripper import Gripper
    from viam.proto.component.arm import JointPositions, MoveOptions
    from armctl import connect, wait_arrival
    import json
    home = json.loads((Path(__file__).resolve().parent.parent / "taught_joints.json").read_text())["home"]
    robot = await connect()
    arm = Arm.from_robot(robot, "follower-arm")
    try:
        await Gripper.from_robot(robot, "follower-gripper").do_command({"command": "set_position", "percentage": 0})
        dense = box.densify(approach + [behind])
        for k in range(0, len(dense), 60):
            await arm.move_through_joint_positions([JointPositions(values=v) for v in dense[k:k + 60]],
                                                   options=MoveOptions(max_vel_degs_per_sec=35.0))
        await wait_arrival(arm, behind, 35.0, timeout=3.0)
        await arm.do_command({"set_speed": FLICK_SPEED})
        await arm.move_to_joint_positions(JointPositions(values=flick))
        await wait_arrival(arm, flick, FLICK_SPEED, timeout=2.0)
        await arm.do_command({"set_speed": 40.0})
        await arm.move_to_joint_positions(JointPositions(values=above))
        await wait_arrival(arm, above, 40.0, timeout=3.0)
        await arm.do_command({"command": "set_torque_limit", "value": 1000})
        try:
            await asyncio.wait_for(arm.move_through_joint_positions([JointPositions(values=v) for v in press],
                                                                   options=MoveOptions(max_vel_degs_per_sec=30.0)), 4.0)
        except asyncio.TimeoutError:
            pass  # the shut lid stops the claw: that is the latch press
        await asyncio.sleep(2.5)
        z = (await arm.get_end_position()).z - 98.0
        await arm.move_through_joint_positions([JointPositions(values=v) for v in press[::-1]], options=MoveOptions(max_vel_degs_per_sec=30.0))
        print(f"{day}: pressed the latch, tip stopped at z {z:.0f}", flush=True)
        await arm.do_command({"set_speed": 35.0})
        await arm.move_to_joint_positions(JointPositions(values=home))
        await wait_arrival(arm, home, 35.0)
        print(f"{day}: flicked", flush=True)
    except BaseException:
        await arm.stop()
        raise
    finally:
        await arm.do_command({"set_speed": 50})
        await robot.close()


if __name__ == "__main__":
    asyncio.run(run(sys.argv[1], "--dry-run" in sys.argv))
