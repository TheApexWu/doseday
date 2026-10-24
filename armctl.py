"""One-shot arm mode switches. Each call connects, does one thing, prints the resulting state, exits.

  python armctl.py status          mode of both arms + teleop loop
  python armctl.py free [torque]   follower manual mode: push it by hand (torque 20-60, default 30; lower = softer)
  python armctl.py teleop          leader goes limp, follower copies it (follower jumps to the leader's pose first)
  python armctl.py off             stop teleop + leave manual mode: both arms stiff and holding
  python armctl.py where           joints + gripper tip pose + jaw, once
  python armctl.py align [speed]   follower moves slowly to the leader's current pose (default 30 deg/s), so teleop can start without a jump
  python armctl.py watch           live tip x/y/z and jaw twice a second until Ctrl-C (reads only)
  python armctl.py teach <name>    save the follower's current joints as <name> in taught_joints.json
  python armctl.py goto <name>     move the follower to a taught pose slowly (30 deg/s)
  python armctl.py poses           list taught poses
  python armctl.py jaw <pct>       set the follower jaw (0-95) and wait until it settles; works in any mode

Logging runs separately and never changes modes:
  python record_teleop.py 120 --no-teleop
"""
import asyncio
import json
import sys
from pathlib import Path

from viam.robot.client import RobotClient
from viam.components.arm import Arm
from viam.components.gripper import Gripper
from viam.errors import ResourceNotFoundError
from viam.services.generic import Generic
from viam.proto.component.arm import JointPositions

from record_teleop import load_env
from actions import wait_arrival



async def joint_limits(arm) -> list[tuple[float, float]]:
    """Limits from the arm's own kinematics: they changed mid-day on 23 Oct (shoulder -104.88 -> -100), so never hardcode them."""
    import json
    data = (await arm.get_kinematics())[1]
    return [(j["min"], j["max"]) for j in json.loads(data)["joints"]]


async def connect():
    env = load_env()
    return await RobotClient.at_address(env["VIAM_ADDRESS"], RobotClient.Options.with_api_key(
        api_key=env["VIAM_API_KEY"], api_key_id=env["VIAM_API_KEY_ID"]))


def optional_teleop(robot):
    """The teleop service, or None when the leader arm it depends on isn't connected."""
    try:
        return Generic.from_robot(robot, "teleop")
    except ResourceNotFoundError:
        return None


async def state(robot):
    follower = Arm.from_robot(robot, "follower-arm")
    mode = (await follower.get_status()).get("mode", "?") if hasattr(follower, "get_status") else "?"
    teleop = optional_teleop(robot)
    if teleop is None:
        return f"follower: {mode} | teleop: absent (leader arm not connected)"
    loop = await teleop.do_command({"command": "status"})
    return f"follower: {mode} | teleop: {'RUNNING' if loop['running'] else 'stopped'} ({int(loop['cycles'])} cycles, last error: {loop['last_error'] or 'none'})"


async def main(cmd, args):
    robot = await connect()
    try:
        follower = Arm.from_robot(robot, "follower-arm")
        teleop = optional_teleop(robot)
        if cmd == "free":
            if teleop:
                await teleop.do_command({"command": "stop"})
            torque = int(args[0]) if args else 30
            await follower.do_command({"command": "enter_manual_mode", "torque_limit": torque, "pos_deadband_deg": 1.0})
        elif cmd == "teleop":
            if teleop is None:
                sys.exit("teleop needs the leader arm, and the robot doesn't see it (check its USB cable)")
            await follower.do_command({"command": "exit_manual_mode"})
            await teleop.do_command({"command": "start"})
        elif cmd == "off":
            if teleop:
                await teleop.do_command({"command": "stop"})
            await follower.do_command({"command": "exit_manual_mode"})
        elif cmd == "where":
            j = (await follower.get_joint_positions()).values
            p = await follower.get_end_position()
            jaw = (await Gripper.from_robot(robot, "follower-gripper").do_command({"command": "get_position"}))["position_percentage"]
            print(f"joints {[round(v, 1) for v in j]}  tip x{p.x:.0f} y{p.y:.0f} z{p.z:.0f}  jaw {jaw:.0f}%")
        elif cmd == "align":
            speed = float(args[0]) if args else 30.0
            if not 12 <= speed <= 60:
                sys.exit("align speed must be 12-60 deg/s (below 12 the servos misbehave; above 60 is not careful)")
            await teleop.do_command({"command": "stop"})
            await follower.do_command({"command": "exit_manual_mode"})
            target = list((await Arm.from_robot(robot, "leader-arm").get_joint_positions()).values)
            lims = await joint_limits(follower)
            target = [min(max(v, lo + 0.5), hi - 0.5) for v, (lo, hi) in zip(target, lims)]
            before = list((await follower.get_joint_positions()).values)
            print("leader  ", [round(v, 1) for v in target])
            print("follower", [round(v, 1) for v in before], f"(max gap {max(abs(a - b) for a, b in zip(target, before)):.1f} deg)")
            await follower.do_command({"set_speed": speed})
            try:
                await follower.move_to_joint_positions(JointPositions(values=target))
                if not await wait_arrival(follower, target, speed):
                    print("warning: the follower did not reach the leader's pose in time")
            finally:
                await follower.do_command({"set_speed": 50})  # back to the configured default
                after = list((await follower.get_joint_positions()).values)
                print("aligned ", [round(v, 1) for v in after], f"(max error {max(abs(a - b) for a, b in zip(target, after)):.1f} deg)")
        elif cmd == "watch":
            jaw = Gripper.from_robot(robot, "follower-gripper")
            try:
                while True:
                    p = await follower.get_end_position()
                    pct = (await jaw.do_command({"command": "get_position"}))["position_percentage"]
                    print(f"\rtip x {p.x:6.1f}  y {p.y:6.1f}  z {p.z:6.1f} mm   jaw {pct:4.1f}%   ", end="", flush=True)
                    await asyncio.sleep(0.5)
            except (KeyboardInterrupt, asyncio.CancelledError):
                print()
        elif cmd in ("teach", "goto", "poses"):
            path = Path(__file__).with_name("taught_joints.json")
            poses = json.loads(path.read_text()) if path.exists() else {}
            if cmd == "poses":
                for name in sorted(poses):
                    print(f"{name:20s} {[round(v, 1) for v in poses[name]]}")
            elif not args:
                sys.exit(f"{cmd} needs a pose name, e.g. tray_hover, drop_wed_hover, lid_wed_press")
            elif cmd == "teach":
                joints = [round(v, 2) for v in (await follower.get_joint_positions()).values]
                note = " (replaced)" if args[0] in poses else ""
                poses[args[0]] = joints
                path.write_text(json.dumps(poses, indent=1, sort_keys=True))
                print(f"taught {args[0]} = {joints}{note}; {len(poses)} poses")
            else:
                if args[0] not in poses:
                    sys.exit(f"{args[0]} is not taught; `python armctl.py poses` lists them")
                await teleop.do_command({"command": "stop"})
                await follower.do_command({"command": "exit_manual_mode"})
                lims = await joint_limits(follower)
                target = [min(max(v, lo + 0.5), hi - 0.5) for v, (lo, hi) in zip(poses[args[0]], lims)]
                await follower.do_command({"set_speed": 30})
                try:
                    await follower.move_to_joint_positions(JointPositions(values=target))
                    if not await wait_arrival(follower, target, 30):
                        print(f"warning: the follower did not reach {args[0]} in time")
                finally:
                    await follower.do_command({"set_speed": 50})
                print(f"at {args[0]}: {[round(v, 1) for v in (await follower.get_joint_positions()).values]}")
        elif cmd == "jaw":
            if not args or not 0 <= float(args[0]) <= 95:
                sys.exit("jaw needs a percentage 0-95 (95 is the open limit)")
            jaw = Gripper.from_robot(robot, "follower-gripper")
            await jaw.do_command({"command": "set_position", "percentage": float(args[0])})
            last, still = None, 0
            while still < 3:  # set_position returns before the jaw settles on this deployment
                await asyncio.sleep(0.1)
                now = (await jaw.do_command({"command": "get_position"}))["position_percentage"]
                still = still + 1 if last is not None and abs(now - last) < 0.5 else 0
                last = now
            print(f"jaw settled at {last:.1f}%")
        elif cmd != "status":
            sys.exit(__doc__)
        print(await state(robot))
    finally:
        await robot.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    asyncio.run(main(sys.argv[1], sys.argv[2:]))
