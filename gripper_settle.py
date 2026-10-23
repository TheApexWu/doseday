import asyncio, time
from pathlib import Path
from viam.robot.client import RobotClient
from viam.components.gripper import Gripper

env = {k.strip(): v.strip().strip("'\"") for k, v in (l.split("=", 1) for l in Path(__file__).with_name(".env").read_text().splitlines() if "=" in l)}

async def pos(g):
    return (await g.do_command({"command": "get_position"}))["position_percentage"]

async def set_and_settle(g, pct, tol=0.5, still_reads=3, timeout=6.0):
    """Command the jaw, then poll until the reading stops changing. Returns (final %, seconds, trace)."""
    t0 = time.monotonic()
    await g.do_command({"command": "set_position", "percentage": pct})
    last, still, trace = await pos(g), 0, []
    while time.monotonic() - t0 < timeout:
        await asyncio.sleep(0.1)
        p = await pos(g)
        trace.append(round(p, 1))
        still = still + 1 if abs(p - last) < tol else 0
        last = p
        if still >= still_reads:
            break
    return round(last, 1), round(time.monotonic() - t0, 2), trace

async def main():
    robot = await RobotClient.at_address(env["VIAM_ADDRESS"], RobotClient.Options.with_api_key(api_key=env["VIAM_API_KEY"], api_key_id=env["VIAM_API_KEY_ID"]))
    try:
        g = Gripper.from_robot(robot, "follower-gripper")
        print("start", round(await pos(g), 1))
        for target in (90, 0):
            final, secs, trace = await set_and_settle(g, target)
            print(f"-> {target}%: settled at {final}% after {secs}s  trace {trace}")
            await asyncio.sleep(1)
    finally:
        await robot.close()

asyncio.run(main())
