import asyncio
import copy
import os
from pathlib import Path

from viam.app.viam_client import ViamClient
from viam.rpc.dial import DialOptions
from viam.robot.client import RobotClient
from viam.components.arm import Arm
from viam.components.gripper import Gripper
from viam.components.camera import Camera
from viam.components.switch import Switch
from viam.services.vision import VisionClient


DETECTOR_NAME = "demo-anything-detector"
DAY_COLORS = {
    "SUNDAY": "#F47F8B",
    "MONDAY": "#F5C94E",
    "TUESDAY": "#F4DF35",
    "WEDNESDAY": "#A5E637",
    "THURSDAY": "#7CBCE9",
    "FRIDAY": "#35C9CE",
    "SATURDAY": "#C58BE8",
}
LOCAL_ENV = Path(__file__).with_name(".env")


def load_local_environment() -> None:
    """Load local, gitignored credentials without overriding exported values."""
    if not LOCAL_ENV.exists():
        return

    for raw_line in LOCAL_ENV.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        os.environ.setdefault(name.strip(), value.strip())


def wait_for_valid_day() -> tuple[str, str]:
    """Pause execution until the user enters a configured day."""
    while True:
        print("DAY OF THE WEEK", flush=True)

        try:
            day = input().strip().upper()
        except EOFError:
            raise SystemExit(
                "The terminal closed before receiving input."
            )

        color = DAY_COLORS.get(day)
        if color is not None:
            print(f"{day} accepted. Continuing...", flush=True)
            return day, color

        print(
            f"{day!r} is not a valid command. Enter one of: "
            f"{', '.join(DAY_COLORS)}.",
            flush=True,
        )


async def connect() -> RobotClient:
    """Connect to the machine shown in the Viam Control tab."""
    options = RobotClient.Options.with_api_key(
        api_key=os.environ["VIAM_API_KEY"],
        api_key_id=os.environ["VIAM_API_KEY_ID"],
    )

    return await RobotClient.at_address(
        os.environ["VIAM_MACHINE_ADDRESS"],
        options,
    )


async def update_detector_color(
    machine: RobotClient,
    color: str,
) -> None:
    """Update the detector color in the Viam cloud configuration."""
    metadata = await machine.get_cloud_metadata()

    cloud_options = DialOptions.with_api_key(
        api_key=os.environ["VIAM_API_KEY"],
        api_key_id=os.environ["VIAM_API_KEY_ID"],
    )

    async with await ViamClient.create_from_dial_options(
        cloud_options
    ) as viam_client:
        cloud = viam_client.app_client

        part = await cloud.get_robot_part(
            metadata.machine_part_id
        )

        # Preserve the complete machine configuration.
        config = copy.deepcopy(dict(part.robot_config or {}))
        services = config.get("services", [])

        detector = next(
            (
                service
                for service in services
                if service.get("name") == DETECTOR_NAME
            ),
            None,
        )

        if detector is None:
            raise RuntimeError(
                f"Could not find {DETECTOR_NAME!r} in the "
                "machine part's services configuration."
            )

        attributes = detector.setdefault("attributes", {})
        previous_color = attributes.get("detect_color")
        attributes["detect_color"] = color

        await cloud.update_robot_part(
            robot_part_id=metadata.machine_part_id,
            name=part.name,
            robot_config=config,
            last_known_update=part.last_updated,
        )

        print(
            f"{DETECTOR_NAME}: detect_color changed "
            f"from {previous_color!r} to {color!r}",
            flush=True,
        )


async def main() -> None:
    load_local_environment()

    # Nothing below this line runs until a configured day is entered.
    day, color = wait_for_valid_day()

    async with await connect() as machine:
        print("Connected. Resources:")
        print(machine.resource_names)

        await update_detector_color(
            machine,
            color,
        )
        print(f"Applied the {day} detector color {color}.", flush=True)

        # Allow the machine time to apply the new configuration.
        await asyncio.sleep(2)

        follower_arm: Arm = Arm.from_robot(
            machine,
            "follower-arm",
        )
        result = await follower_arm.get_end_position()
        print(
            "follower-arm get_end_position "
            f"return value: {result}"
        )

        follower_gripper: Gripper = Gripper.from_robot(
            machine,
            "follower-gripper",
        )
        result = await follower_gripper.is_moving()
        print(
            "follower-gripper is_moving "
            f"return value: {result}"
        )

        follower_cam: Camera = Camera.from_robot(
            machine,
            "follower-cam",
        )
        result = await follower_cam.get_images()
        print(
            "follower-cam get_images "
            f"return value: {result}"
        )

        leader_arm: Arm = Arm.from_robot(
            machine,
            "leader-arm",
        )
        result = await leader_arm.get_end_position()
        print(
            "leader-arm get_end_position "
            f"return value: {result}"
        )

        leader_gripper: Gripper = Gripper.from_robot(
            machine,
            "leader-gripper",
        )
        result = await leader_gripper.is_moving()
        print(
            "leader-gripper is_moving "
            f"return value: {result}"
        )

        home_pose: Switch = Switch.from_robot(
            machine,
            "home-pose",
        )
        result = await home_pose.get_position()
        print(
            "home-pose get_position "
            f"return value: {result}"
        )

        detector: VisionClient = VisionClient.from_robot(
            machine,
            DETECTOR_NAME,
        )
        result = await detector.get_properties()
        print(
            f"{DETECTOR_NAME} get_properties "
            f"return value: {result}"
        )


if __name__ == "__main__":
    asyncio.run(main())
