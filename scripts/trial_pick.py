"""Trial, not yet run (23 Oct): grip the pill at the tray spot (Alex's hand-demo grasp, run 06), carry it high over the box, release over Friday's front.
HARDWARE: park the open claw above the tray spot first, put a Tums under it, then run. Photos go to logs/."""
import asyncio, sys, time, cv2, numpy as np
from viam.components.arm import Arm
from viam.components.camera import Camera
from viam.components.gripper import Gripper
from viam.proto.component.arm import JointPositions, MoveOptions
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
from armctl import connect
from actions import wait_arrival, JAW_HELD_MIN
import box
S = str(__import__("pathlib").Path(__file__).resolve().parent.parent / "logs")
kin = box.Kinematics()
TRAY = [346.3, -108.1]
GRASP_Z, HOVER_Z = 10.6, 50.0
DROP = [247.1, -67.6, 31.0]

async def settle(grip, timeout=3.0):
    last, still, t0 = None, 0, time.monotonic()
    while still < 3 and time.monotonic() - t0 < timeout:
        await asyncio.sleep(0.15)
        now = (await grip.do_command({"command": "get_position"}))["position_percentage"]
        still = still + 1 if last is not None and abs(now - last) < 0.3 else 0
        last = now
    return last

async def go(arm, pts, speed):
    q = [float(v) for v in (await arm.get_joint_positions()).values]
    qs = [q]
    for p, lean in pts:
        qs.append(kin.ik(p, lean, qs[-1], heading=-88.0))
    path = box.densify(qs)
    await arm.move_through_joint_positions([JointPositions(values=x) for x in path[1:]], options=MoveOptions(max_vel_degs_per_sec=speed))
    ok = await wait_arrival(arm, qs[-1], speed)
    at = [round(v, 2) for v in (await arm.get_joint_positions()).values]
    print(f"  at tip {np.round(kin.tip(at)[0],1).tolist()} arrived={ok}", flush=True)
    return ok

async def main():
    robot = await connect()
    arm, grip, cam = Arm.from_robot(robot, "follower-arm"), Gripper.from_robot(robot, "follower-gripper"), Camera.from_robot(robot, "follower-cam")
    try:
        await arm.do_command({"command": "set_torque_limit", "value": 1000})
        print("descend to grasp", flush=True)
        await go(arm, [([*TRAY, HOVER_Z], 21.7), ([*TRAY, GRASP_Z], 21.7)], 15.0)
        await grip.do_command({"command": "set_position", "percentage": 0.0})
        stopped = await settle(grip)
        print(f"jaw stopped at {stopped:.1f}% (held if >= {JAW_HELD_MIN})", flush=True)
        if stopped < JAW_HELD_MIN:
            await grip.do_command({"command": "set_position", "percentage": 42.0})
            await go(arm, [([*TRAY, HOVER_Z], 21.7)], 20.0)
            print("MISS: nothing in the jaws; back at the tray hover")
            return
        await grip.do_command({"command": "set_position", "percentage": max(stopped - 1.0, 0.0)})
        print("carry", flush=True)
        await go(arm, [([*TRAY, 60.0], 21.7), ([300, -85, 115], 21.7), ([250, -68, 85], 6.0), (DROP, 6.0)], 25.0)
        held = (await grip.do_command({"command": "get_position"}))["position_percentage"]
        print(f"jaw before release {held:.1f}% (still holding if >= {JAW_HELD_MIN})", flush=True)
        await grip.do_command({"command": "set_position", "percentage": 91.0})
        await asyncio.sleep(0.6)
        await go(arm, [([250, -68, 85], 6.0)], 25.0)
        await asyncio.sleep(2.0)
        imgs, _ = await cam.get_images()
        cv2.imwrite(f"{S}/after_drop.jpg", cv2.imdecode(np.frombuffer(imgs[0].data, np.uint8), cv2.IMREAD_COLOR))
        print("released over Friday")
    finally:
        await arm.do_command({"command": "set_torque_limit", "value": 1000})
        await robot.close()

asyncio.run(main())
