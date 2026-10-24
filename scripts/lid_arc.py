"""Close lids by rotating each one about its hinge: push its back face far from the hinge, along an arc, then press
the latch down. A push at the hinge has no leverage and slides the whole box (24 Oct), so the claw stays ARC_R out
along the lid and moves at right angles to it.

usage: python scripts/lid_arc.py [days, default sun-sat] [--dry-run]

Geometry (arm frame, mm): front edge x 200, hinge 40 behind it (x 240) at the closed lid top z 28, lid ~42 long;
open lids lean 20-30 deg past upright (Alex's photo), so their free edge sits near x 258, z 66. The open lids form a
wall the claw cannot reach over, so it travels BEHIND the wall at BEHIND_X between lids, going back over each lid it
has just closed. Lid midpoints come from box.LID_Y (Alex's hand-centred pushes).
HARDWARE-ONLY unless --dry-run.
"""
import asyncio
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import box
from linear import calibrated, ik, line

HEADING = box.HEADING      # jaws along the box
HINGE_X, HINGE_Z = 240.0, 28.0
ARC_R = 30.0               # contact this far out along the lid from the hinge: leverage, still inside its ~42 mm
CLEAR = 5.0                # claw tip this far off the lid face
ARC_FROM, ARC_TO, ARC_STEP = 125.0, 0.0, 10.0   # lid angle from closed (0) to leaning back past upright
BEHIND_X, BEHIND_Z = 278.0, 46.0                # travel lane behind the wall of open lids (moved 10 mm back after a lid scrape, 24 Oct)
PRESS_X, PRESS_TARGET_Z = 205.0, 3.0            # 5 mm behind the clip; aim 25 mm under the lid top so the servos push hard
ARC_TORQUE, PRESS_TORQUE = 750, 1000  # Alex: more aggressive; the arc pushes at right angles to the lid, so it turns the lid rather than the box
HOLD_S = 2.5
OVER_Z = 50.0              # back over a just-closed lid (top 28) with the claw 10 mm thick: 12 mm clear
SPEED = 35.0
ARC_SPEED = 45.0          # fast enough that the lid swings over the top and drops shut
PRESS_SPEED = 30.0        # a snap onto the clip, not a slow squeeze
LEANS = (0, 5, 10, 15, 20, 25, 30)


def arc_point(alpha_deg, y):
    a = math.radians(alpha_deg)
    return [HINGE_X - ARC_R * math.cos(a) + CLEAR * math.sin(a), y, HINGE_Z + ARC_R * math.sin(a) + CLEAR * math.cos(a)]


def plan(days):
    kin = calibrated(box.Kinematics())
    q = json.loads((Path(__file__).resolve().parent.parent / "taught_joints.json").read_text())["home"]
    out, prev_y = [], None
    for d in days:
        y = box.LID_Y_24OCT[d]
        start = arc_point(ARC_FROM, y)
        if prev_y is None:  # come in from beyond the box's Sunday end, behind the wall
            lane = [ik(kin, [BEHIND_X, max(box.LID_Y_24OCT.values()) + 45.0, BEHIND_Z], q, HEADING, LEANS)]
            lane += line(kin, [BEHIND_X, max(box.LID_Y_24OCT.values()) + 45.0, BEHIND_Z], [BEHIND_X, y, BEHIND_Z], lane[-1], HEADING, LEANS)
        else:  # back over the lid just closed, then along the lane behind the wall
            over = line(kin, [PRESS_X, prev_y, OVER_Z], [BEHIND_X, prev_y, OVER_Z], q, HEADING, LEANS)
            lane = over + line(kin, [BEHIND_X, prev_y, OVER_Z], [BEHIND_X, y, BEHIND_Z], over[-1], HEADING, LEANS)
        into = line(kin, [BEHIND_X, y, BEHIND_Z], start, lane[-1], HEADING, LEANS)
        arc, qa = [], into[-1]
        a = ARC_FROM
        while a >= ARC_TO - 1e-6:
            qa = ik(kin, arc_point(a, y), qa, HEADING, LEANS)
            arc.append(qa)
            a -= ARC_STEP
        end = arc_point(ARC_TO, y)
        to_press = line(kin, end, [PRESS_X, y, end[2]], arc[-1], HEADING, LEANS)
        press = line(kin, [PRESS_X, y, end[2]], [PRESS_X, y, PRESS_TARGET_Z], to_press[-1], HEADING, (0, -5, 5, -10, 10))
        lift = press[::-1] + line(kin, [PRESS_X, y, end[2]], [PRESS_X, y, OVER_Z], press[0], HEADING, (0, -5, 5, -10, 10, 15, 20))
        out.append((d, y, lane + into, arc, to_press, press, lift))
        q, prev_y = lift[-1], y
    return kin, out


async def run(days, dry):
    kin, steps = plan(days)
    from box_obstacle import clearance
    for d, y, approach, arc, to_press, press, lift in steps:
        worst = min(clearance(kin, q, lids_open=False)[0] for q in approach)
        print(f"{d}: y {y:6.1f}  approach {len(approach)} pts (min gap to the closed-box body {worst:.0f} mm), arc {len(arc)} pts, press {len(press)} pts")
    if dry:
        return
    from viam.components.arm import Arm
    from viam.components.gripper import Gripper
    from viam.proto.component.arm import JointPositions, MoveOptions
    from armctl import connect, wait_arrival

    robot = await connect()
    arm = Arm.from_robot(robot, "follower-arm")

    async def through(qs, spd=SPEED, timeout=None):
        dense = box.densify(qs)
        for k in range(0, len(dense), 60):
            call = arm.move_through_joint_positions([JointPositions(values=v) for v in dense[k:k + 60]],
                                                    options=MoveOptions(max_vel_degs_per_sec=spd))
            await (asyncio.wait_for(call, timeout) if timeout else call)
        await wait_arrival(arm, dense[-1], spd, timeout=3.0)

    try:
        await Gripper.from_robot(robot, "follower-gripper").do_command({"command": "set_position", "percentage": 0})
        for d, y, approach, arc, to_press, press, lift in steps:
            await through(approach)
            await arm.do_command({"command": "set_torque_limit", "value": ARC_TORQUE})
            try:
                try:
                    await through(arc, ARC_SPEED, timeout=12.0)
                except asyncio.TimeoutError:
                    pass  # a lid that resists stalls the claw at the capped force instead of shoving the box
                await through(to_press, ARC_SPEED)
                await arm.do_command({"command": "set_torque_limit", "value": PRESS_TORQUE})
                try:
                    await through(press, PRESS_SPEED, timeout=5.0)
                except asyncio.TimeoutError:
                    pass  # the latched lid stops the claw: that is the press
                await asyncio.sleep(HOLD_S)
                z = (await arm.get_end_position()).z - 98.0
            finally:
                await arm.do_command({"command": "set_torque_limit", "value": 1000})
            await through(lift)
            print(f"{d}: arced shut and pressed (tip stopped at z {z:.0f}; lid top 28)", flush=True)
    except BaseException:
        await arm.stop()
        raise
    finally:
        await robot.close()


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--dry-run"]
    days = args[0].split(",") if args else box.DAYS
    asyncio.run(run(days, "--dry-run" in sys.argv))
