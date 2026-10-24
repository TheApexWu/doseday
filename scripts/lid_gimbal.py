"""Close lids with the claw held like a gimbal: pointing straight down, jaws square to the box, never tilting or
twisting. Every motion is a straight-line slide of the claw tip.

usage: python scripts/lid_gimbal.py [days, default sun-sat] [--dry-run]
Per lid: above the back of the lid, down behind the standing lid, fold it forward around its hinge in short slides,
slide onto the lid centre, push straight down at capped force and hold, straight up.

Geometry (arm frame, mm): lid front edge x 200 (wrist-camera frames of lid-teach-13 put the jaws on the front edge at
tip x 198-205), hinge 40 mm behind it (box.py), standing lid ~42 mm tall; lid centres along the box from the fit of
the hand's pushes, Sunday 76.7, 30.6 mm apart, which matches the camera-confirmed drops. Push depth and force are day
1's lid stroke that latched Tue/Wed: aim at z -11 with torque capped at 600.
HARDWARE-ONLY unless --dry-run.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import box
from linear import calibrated, ik, line

HEADING = -103.0           # wrist roll minus pan the hand held through every lid in lid-teach-13: jaws square to the box
SUN_Y, PITCH_Y = 74.2, -30.6  # 76.7 from the fit; Alex saw the Sunday push on the lid edge: 2.5 mm to his right (-y), 24 Oct
FRONT_X, HINGE_BACK = 200.0, 40.0
CENTRE_X = FRONT_X + 19.0
# (x, z) of the claw tip folding a standing lid toward the arm around its hinge (x 240, z 28), all claw-vertical
# the hand's own Sunday path in lid-teach-13 (t 11-17 s), claw held vertical instead of tilted: in from the side at
# 48 mm, down behind the lid at the hinge, then a level drag toward the arm that folds the lid down
FOLD = [(234.0, 48.0), (240.0, 38.0), (226.0, 24.0), (215.0, 23.0), (207.0, 22.0)]
PUSH_TARGET_Z = -11.0
PUSH_TORQUE = 600
HOLD_S = 2.0
UP_Z = 48.0               # the hand moved between lids at 30-46 mm
SPEED = 25.0
CHUNK = 60


def plan(days):
    kin = calibrated(box.Kinematics())
    q = [0.0, -20.0, 10.0, 89.0, HEADING]
    out = []
    for d in days:
        y = SUN_Y + PITCH_Y * box.DAYS.index(d)
        fold = []
        for (xa, za), (xb, zb) in zip(FOLD, FOLD[1:]):
            seg = line(kin, [xa, y, za], [xb, y, zb], q, HEADING, leans=(0,))
            fold += seg
            q = seg[-1]
        onto = line(kin, [FOLD[-1][0], y, FOLD[-1][1]], [CENTRE_X, y, FOLD[-1][1] - 2.0], q, HEADING, leans=(0,))
        push = line(kin, [CENTRE_X, y, FOLD[-1][1] - 2.0], [CENTRE_X, y, PUSH_TARGET_Z], onto[-1], HEADING, leans=(0,))
        up = line(kin, [CENTRE_X, y, FOLD[-1][1] - 2.0], [CENTRE_X, y, UP_Z], onto[-1], HEADING, leans=(0,))
        if out:  # level move from the previous lid's lift to this lid's start, at UP_Z
            prev_up = out[-1][5][-1]
            fold = line(kin, list(kin.tip(prev_up)[0]), [FOLD[0][0], y, FOLD[0][1]], prev_up, HEADING, leans=(0,)) + fold
        out.append((d, y, fold, onto, push, up))
        q = up[-1]
    return kin, out


async def run(days, dry):
    kin, steps = plan(days)
    for d, y, fold, onto, push, up in steps:
        print(f"{d}: lid centre ({CENTRE_X:.0f}, {y:.1f}); fold {len(fold)} pts, push {len(push)} pts; wrist {fold[0][4]:.0f}..{up[-1][4]:.0f}")
    if dry:
        return
    from viam.components.arm import Arm
    from viam.components.gripper import Gripper
    from viam.proto.component.arm import JointPositions, MoveOptions
    from armctl import connect, wait_arrival

    robot = await connect()
    arm = Arm.from_robot(robot, "follower-arm")

    async def through(qs, timeout=None):
        dense = box.densify(qs)
        for k in range(0, len(dense), CHUNK):
            call = arm.move_through_joint_positions([JointPositions(values=q) for q in dense[k:k + CHUNK]],
                                                    options=MoveOptions(max_vel_degs_per_sec=SPEED))
            await (asyncio.wait_for(call, timeout) if timeout else call)
        await wait_arrival(arm, dense[-1], SPEED, timeout=4.0)

    try:
        await Gripper.from_robot(robot, "follower-gripper").do_command({"command": "set_position", "percentage": 0})
        import json
        home = json.loads((Path(__file__).resolve().parent.parent / "taught_joints.json").read_text())["home"]
        await through([home])  # taught home first: high and in front of the box, wherever the last run stopped
        for d, y, fold, onto, push, up in steps:
            await through(fold)
            await through(onto)
            await arm.do_command({"command": "set_torque_limit", "value": PUSH_TORQUE})
            try:
                try:
                    await through(push, timeout=6.0)
                except asyncio.TimeoutError:
                    pass  # the lid stops the claw short of the target: that is the push
                await asyncio.sleep(HOLD_S)
            finally:
                await arm.do_command({"command": "set_torque_limit", "value": 1000})
            await through(up)
            print(f"{d}: folded, pushed at the centre, held {HOLD_S:.0f} s", flush=True)
        await through([home])
    except BaseException:
        await arm.stop()
        raise
    finally:
        await robot.close()


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--dry-run"]
    days = args[0].split(",") if args else box.DAYS
    asyncio.run(run(days, "--dry-run" in sys.argv))
