"""One-shot arm mode switches. Each call connects, does one thing, prints the resulting state, exits.

  python armctl.py status          mode of both arms + teleop loop
  python armctl.py free [torque]   follower manual mode: push it by hand (torque 20-60, default 30; lower = softer)
  python armctl.py teleop          leader goes limp, follower copies it (follower jumps to the leader's pose first)
  python armctl.py off             stop teleop + leave manual mode: both arms stiff and holding
  python armctl.py where           joints + gripper tip pose + jaw, once
  python armctl.py align [speed]   follower moves slowly to the leader's current pose (default 30 deg/s), so teleop can start without a jump
  python armctl.py jaw <pct>       set the follower jaw (0-95) and wait until it settles; works in any mode

Logging runs separately and never changes modes:
  python record_teleop.py 120 --no-teleop
"""
import asyncio
import sys

from viam.robot.client import RobotClient
from viam.components.arm import Arm
from viam.components.gripper import Gripper
from viam.services.generic import Generic
from viam.proto.component.arm import JointPositions

from record_teleop import load_env



async def joint_limits(arm) -> list[tuple[float, float]]:
    """Limits from the arm's own kinematics: they changed mid-day on 23 Oct (shoulder -104.88 -> -100), so never hardcode them."""
    import json
    data = (await arm.get_kinematics())[1]
    return [(j["min"], j["max"]) for j in json.loads(data)["joints"]]


async def connect():
    env = load_env()
    return await RobotClient.at_address(env["VIAM_ADDRESS"], RobotClient.Options.with_api_key(
        api_key=env["VIAM_API_KEY"], api_key_id=env["VIAM_API_KEY_ID"]))


async def state(robot):
    follower = Arm.from_robot(robot, "follower-arm")
    mode = (await follower.get_status()).get("mode", "?") if hasattr(follower, "get_status") else "?"
    loop = await Generic.from_robot(robot, "teleop").do_command({"command": "status"})
    return f"follower: {mode} | teleop: {'RUNNING' if loop['running'] else 'stopped'} ({int(loop['cycles'])} cycles, last error: {loop['last_error'] or 'none'})"


async def main(cmd, args):
    robot = await connect()
    try:
        follower = Arm.from_robot(robot, "follower-arm")
        teleop = Generic.from_robot(robot, "teleop")
        if cmd == "free":
            await teleop.do_command({"command": "stop"})
            torque = int(args[0]) if args else 30
            await follower.do_command({"command": "enter_manual_mode", "torque_limit": torque, "pos_deadband_deg": 1.0})
        elif cmd == "teleop":
            await follower.do_command({"command": "exit_manual_mode"})
            await teleop.do_command({"command": "start"})
        elif cmd == "off":
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
            finally:
                await follower.do_command({"set_speed": 50})  # back to the configured default
                after = list((await follower.get_joint_positions()).values)
                print("aligned ", [round(v, 1) for v in after], f"(max error {max(abs(a - b) for a, b in zip(target, after)):.1f} deg)")
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
