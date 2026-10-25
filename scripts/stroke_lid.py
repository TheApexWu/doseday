"""Lid stroke with a camera check: stage 1 moves to the hover over <day> and saves a wrist frame; stage 2 (--go) runs
box.py's stroke, straightens the claw on the lid without lifting, and pushes straight down deep at capped force.

usage: python scripts/stroke_lid.py <day> [--go]
HARDWARE-ONLY.
"""
import asyncio, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
import box
from linear import calibrated
from viam.components.arm import Arm
from viam.components.camera import Camera
from viam.components.gripper import Gripper
from viam.proto.component.arm import JointPositions
from armctl import connect, wait_arrival

day, go = sys.argv[1], "--go" in sys.argv
LID_TOP_Z, DEEP_MM, DEEP_TORQUE = 28.0, 30.0, 800  # aim 30 mm under the lid top at 80% force (Alex: deeper, 24 Oct)
OUT = str(ROOT / "logs") + "/"

def straighten(kin, q, steps=6, sink=0.5):
    """From a tilted claw pressing on the lid to vertical, tip kept on the spot and sinking a little each step."""
    import numpy as np
    (x, y, z), axis = kin.tip(q)
    radial = np.array([x, y]) - kin.pan_axis()[:2]
    radial /= np.linalg.norm(radial)
    tilt = float(np.degrees(np.arccos(np.clip(-axis[2], -1, 1))))
    lean0 = tilt if axis[:2] @ radial > 0 else -tilt
    out, qk = [], q
    for i in range(1, steps + 1):
        qk = kin.ik([x, y, z - sink * i], lean0 * (1 - i / steps), qk, heading=q[4] - q[0])
        out.append(qk)
    return out


async def main():
    kin = calibrated(box.Kinematics())
    home = json.load(open(ROOT / "taught_joints.json"))["home"]
    wps = box.plan(kin, box.Box.load(), day, home)
    r = await connect()
    arm = Arm.from_robot(r, "follower-arm")
    try:
        if not go:
            await Gripper.from_robot(r, "follower-gripper").do_command({"command": "set_position", "percentage": 0})
            for name in ("pre", "hover"):
                q = next(w["joints"] for w in wps if w["name"] == name)
                await arm.do_command({"set_speed": 25})
                await arm.move_to_joint_positions(JointPositions(values=q))
                await wait_arrival(arm, q, 25)
            res = await Camera.from_robot(r, "follower-cam").get_images()
            open(OUT + f"stroke_{day}_hover.jpg", "wb").write((res[0] if isinstance(res, tuple) else res)[0].data)
            print("at hover; frame saved")
        else:
            # the day-1 stroke up to its press (no lift), then: straighten to vertical on the lid without lifting and
            # push straight down deep at capped force, hold, lift
            from viam.proto.component.arm import MoveOptions
            from linear import line
            seq = [w for w in wps if w["name"] not in ("pre", "lift")]
            path = box.densify([w["joints"] for w in seq])
            await arm.do_command({"command": "set_torque_limit", "value": 600})
            try:
                for k in range(0, len(path), 60):
                    await asyncio.wait_for(arm.move_through_joint_positions([JointPositions(values=q) for q in path[k:k + 60]],
                                                                             options=MoveOptions(max_vel_degs_per_sec=25)), 20)
                await wait_arrival(arm, path[-1], 25, timeout=2.0)
                q = list((await arm.get_joint_positions()).values)
                (x, y, z), axis = kin.tip(q)
                h = q[4] - q[0]
                straight = straighten(kin, q)
                await arm.move_through_joint_positions([JointPositions(values=v) for v in straight], options=MoveOptions(max_vel_degs_per_sec=15))
                await arm.do_command({"command": "set_torque_limit", "value": DEEP_TORQUE})
                down = line(kin, [x, y, z - 3.0], [x, y, LID_TOP_Z - DEEP_MM], straight[-1], h, leans=(0,))
                try:
                    await asyncio.wait_for(arm.move_through_joint_positions([JointPositions(values=v) for v in down], options=MoveOptions(max_vel_degs_per_sec=15)), 5.0)
                except asyncio.TimeoutError:
                    pass  # the lid stops the claw: that is the push
                await asyncio.sleep(4.0)
                zp = (await arm.get_end_position()).z - 98.0
            finally:
                await arm.do_command({"command": "set_torque_limit", "value": 1000})
            up = line(kin, [x, y, max(zp, LID_TOP_Z - DEEP_MM)], [x, y, 70.0], down[-1], h, leans=(0, 5, 10, 15, 20))
            await arm.move_through_joint_positions([JointPositions(values=v) for v in up], options=MoveOptions(max_vel_degs_per_sec=25))
            ok = f"deep push stopped at tip z {zp:.0f} (lid top 28; below 28 means it pressed the lid down)"
            res = await Camera.from_robot(r, "follower-cam").get_images()
            open(OUT + f"stroke_{day}_after.jpg", "wb").write((res[0] if isinstance(res, tuple) else res)[0].data)
            print("stroke done,", ok)
    except BaseException:
        await arm.stop()
        raise
    finally:
        await r.close()

asyncio.run(main())
