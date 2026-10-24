"""One lid close estimated from Alex's Wednesday attempts (manual-1648): start far behind, catch low at the hinge,
drag forward across the lid pressing down to the clip, fast. Fitted and cleaned, not raw (hand data is imprecise).
usage: python scripts/lid_wed.py [y] [--dry-run]
"""
import asyncio, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent)); sys.path.insert(0, str(Path(__file__).resolve().parent))
import box
from linear import calibrated, ik, line

Y = -14.0  # 1 mm to Alex's left
PATH = [(273.0, 36.0), (252.0, 30.0), (238.0, 25.0), (225.0, 24.0), (212.0, 22.0), (204.0, 20.0), (194.0, 25.0)]  # 2 mm deeper across the lid: harder downward push (try 2 at 3 mm was too deep)
LEANS = (-20.0, -15.0, -25.0, -10.0, -30.0, -5.0, 0.0, 5.0, 10.0)   # trailing toward the arm like the hand
SPEED, DRAG_TORQUE = 45.0, 1000  # Alex: slower, full force


def plan(y):
    kin = calibrated(box.Kinematics())
    home = json.loads((Path(__file__).resolve().parent.parent / "taught_joints.json").read_text())["home"]
    pre = ik(kin, [PATH[0][0], y, 70.0], home, box.HEADING, (0, 5, 10, 15, 20, 25, 30))
    down = line(kin, [PATH[0][0], y, 70.0], [PATH[0][0], y, PATH[0][1]], pre, box.HEADING, LEANS)
    drag, q = [], down[-1]
    for (xa, za), (xb, zb) in zip(PATH, PATH[1:]):
        seg = line(kin, [xa, y, za], [xb, y, zb], q, box.HEADING, LEANS)
        drag += seg; q = seg[-1]
    up = line(kin, [PATH[-1][0], y, PATH[-1][1]], [PATH[-1][0], y, 70.0], q, box.HEADING, (0, 5, -5, 10, 15, 20))
    return home, [pre] + down, drag, up


async def run(y, dry):
    home, approach, drag, up = plan(y)
    print(f"y {y}: approach {len(approach)}, drag {len(drag)}, up {len(up)} points: all reach")
    if dry:
        return
    from viam.components.arm import Arm
    from viam.components.gripper import Gripper
    from viam.proto.component.arm import JointPositions, MoveOptions
    from armctl import connect, wait_arrival
    r = await connect(); arm = Arm.from_robot(r, "follower-arm")

    async def through(qs, spd, timeout=None):
        d = box.densify(qs)
        for k in range(0, len(d), 60):
            c = arm.move_through_joint_positions([JointPositions(values=v) for v in d[k:k + 60]], options=MoveOptions(max_vel_degs_per_sec=spd))
            await (asyncio.wait_for(c, timeout) if timeout else c)
        await wait_arrival(arm, d[-1], spd, timeout=3.0)
    try:
        try:  # the lid move does not need the jaw; a silent gripper servo must not stop it
            await asyncio.wait_for(Gripper.from_robot(r, "follower-gripper").do_command({"command": "set_position", "percentage": 0}), 3)
        except Exception as e:
            print(f"jaw close skipped: {str(e)[:60]}", flush=True)
        await through(approach, 40.0)
        await arm.do_command({"command": "set_torque_limit", "value": DRAG_TORQUE})
        try:
            await through(drag, SPEED, timeout=8.0)
        except asyncio.TimeoutError:
            pass
        finally:
            await arm.do_command({"command": "set_torque_limit", "value": 1000})
        await through(up, 40.0)
        await through([home], 40.0)
        print("wednesday: dragged shut", flush=True)
    except BaseException:
        await arm.stop(); raise
    finally:
        await r.close()

if __name__ == "__main__":
    if "--deeper" in sys.argv:  # lower the across-the-lid part of the drag by N mm for a harder downward push
        i = sys.argv.index("--deeper"); n = float(sys.argv[i + 1]); del sys.argv[i:i + 2]
        PATH[2:6] = [(x, z - n) for x, z in PATH[2:6]]
    args = [a for a in sys.argv[1:] if a != "--dry-run"]
    asyncio.run(run(float(args[0]) if args else Y, "--dry-run" in sys.argv))
