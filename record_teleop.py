"""Teleop + live recorder. Starts leader->follower mirroring, logs both arms at ~10 Hz to CSV, always stops teleop on exit.

usage: python record_teleop.py [seconds] [--no-teleop] [--follower-only]
  --no-teleop      only record (e.g. while someone moves the follower in manual mode)
  --follower-only  skip leader reads: teleop already reads the leader 100 times a second on the same serial
                   line, and the extra reads lined up with "read 39 of 48 bytes" timeouts on 23 Oct
"""
import asyncio, csv, signal, sys, time
from datetime import datetime
from pathlib import Path

from viam.robot.client import RobotClient
from viam.components.arm import Arm
from viam.components.gripper import Gripper
from viam.services.generic import Generic

HERE = Path(__file__).parent
HZ = 10


def load_env(path=HERE / ".env"):
    pairs = (l.split("=", 1) for l in path.read_text().splitlines() if "=" in l)
    return {k.strip(): v.strip().strip("'\"") for k, v in pairs}


async def main(seconds: float, teleop_on: bool, follower_only: bool = False):
    env = load_env()
    robot = await RobotClient.at_address(env["VIAM_ADDRESS"], RobotClient.Options.with_api_key(
        api_key=env["VIAM_API_KEY"], api_key_id=env["VIAM_API_KEY_ID"]))
    teleop = Generic.from_robot(robot, "teleop")
    follower, leader = Arm.from_robot(robot, "follower-arm"), Arm.from_robot(robot, "leader-arm")
    jaw = Gripper.from_robot(robot, "follower-gripper")
    out = HERE / "logs" / f"teleop-{datetime.now():%H%M%S}.csv"
    out.parent.mkdir(exist_ok=True)
    try:
        if teleop_on:
            print("teleop:", await teleop.do_command({"command": "start"}))
        with out.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["t", *[f"L{i}" for i in range(5)], *[f"F{i}" for i in range(5)], "x", "y", "z", "o_x", "o_y", "o_z", "theta", "jaw_pct", *[f"load{i}" for i in range(5)]])
            t0 = time.monotonic()
            while (t := time.monotonic() - t0) < seconds:
                try:
                    fj = (await follower.get_joint_positions()).values
                    lj = fj if follower_only else (await leader.get_joint_positions()).values
                    p = await follower.get_end_position()
                    g = (await jaw.do_command({"command": "get_position"}))["position_percentage"]
                    # servo load is only reported while the follower is in manual mode; blank otherwise
                    st = await follower.get_status() if hasattr(follower, "get_status") else {}
                    loads = [j.get("load", "") for j in (st.get("manual_mode") or {}).get("joints", [])] or [""] * 5
                    w.writerow([round(t, 2), *[round(v, 2) for v in lj], *[round(v, 2) for v in fj],
                                *[round(v, 1) for v in (p.x, p.y, p.z)], *[round(v, 3) for v in (p.o_x, p.o_y, p.o_z)], round(p.theta, 1), round(g, 1), *loads])
                    f.flush()
                    print(f"{t:5.1f}s  follower {[round(v) for v in fj]}  tip x{p.x:6.0f} y{p.y:6.0f} z{p.z:6.0f}  jaw {g:4.0f}%  lag {max(abs(a-b) for a,b in zip(lj,fj)):4.1f}°", flush=True)
                except Exception as e:  # one bad serial read must not end the session
                    print(f"{t:5.1f}s  read failed: {str(e)[:80]}", flush=True)
                await asyncio.sleep(max(0, 1 / HZ - (time.monotonic() - t0 - t)))
    finally:
        if teleop_on:
            print("teleop:", await teleop.do_command({"command": "stop"}))
            print("status:", await teleop.do_command({"command": "status"}))
        await robot.close()
        print("saved", out)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt))
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    try:
        asyncio.run(main(float(args[0]) if args else 60, "--no-teleop" not in sys.argv, "--follower-only" in sys.argv))
    except KeyboardInterrupt:
        pass
