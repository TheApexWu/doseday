"""Read-only connection check: lists resources, reads arm joints and pose. Moves nothing."""
import asyncio
from pathlib import Path

from viam.robot.client import RobotClient
from viam.components.arm import Arm


def load_env(path=Path(__file__).with_name(".env")) -> dict:
    pairs = (l.split("=", 1) for l in path.read_text().splitlines() if "=" in l and not l.startswith("#"))
    return {k.strip(): v.strip().strip("'\"") for k, v in pairs}


async def main():
    env = load_env()
    opts = RobotClient.Options.with_api_key(api_key=env["VIAM_API_KEY"], api_key_id=env["VIAM_API_KEY_ID"])
    robot = await RobotClient.at_address(env["VIAM_ADDRESS"], opts)
    try:
        for r in robot.resource_names:
            print(f"{r.namespace}:{r.type}:{r.subtype}  {r.name}")
        for r in robot.resource_names:
            if r.subtype == "arm":
                arm = Arm.from_robot(robot, r.name)
                print(r.name, "joints:", [round(v, 1) for v in (await arm.get_joint_positions()).values])
                print(r.name, "end pose:", await arm.get_end_position())
    finally:
        await robot.close()


asyncio.run(main())
