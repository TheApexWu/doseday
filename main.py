import asyncio
import argparse
import copy
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
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
PRIMARY_COLORS = (
    "white",
    "black",
    "brown",
    "red",
    "orange",
    "yellow",
    "green",
    "blue",
    "purple",
    "pink",
    "gray",
    "other",
)
PILL_SHAPES = (
    "round",
    "oval",
    "capsule",
    "other",
)
LOCAL_ENV = Path(__file__).with_name(".env")
LOCAL_CV_APP = (
    Path(__file__).resolve().parent.parent
    / "YOLO11-Based-Pill-Recognition-OCR-Classification-System"
)


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


def wait_for_valid_choice(
    prompt: str,
    choices: tuple[str, ...],
) -> str:
    """Pause until the user enters one of the model's output labels."""
    while True:
        print(prompt, flush=True)

        try:
            choice = input().strip().lower()
        except EOFError:
            raise SystemExit(
                "The terminal closed before receiving input."
            )

        if choice in choices:
            print(f"{choice} accepted. Continuing...", flush=True)
            return choice

        print(
            f"{choice!r} is not valid. Enter one of: "
            f"{', '.join(choices)}.",
            flush=True,
        )


def run_local_pill_demo(port: int) -> int:
    """Launch the local CV UI without connecting to Viam or moving hardware."""
    primary_color = wait_for_valid_choice(
        "PRIMARY COLOR",
        PRIMARY_COLORS,
    )
    shape = wait_for_valid_choice(
        "SHAPE",
        PILL_SHAPES,
    )

    app_entrypoint = LOCAL_CV_APP / "main.py"
    if not app_entrypoint.is_file():
        raise SystemExit(
            f"Local CV app not found at {app_entrypoint}."
        )

    query = urllib.parse.urlencode({
        "target_color": primary_color,
        "target_shape": shape,
        "run": int(time.time()),
    })
    page_url = f"http://127.0.0.1:{port}/?{query}"
    health_url = f"http://127.0.0.1:{port}/healthz"
    environment = os.environ.copy()
    environment["PORT"] = str(port)

    print("Starting the local pill-selection demo...", flush=True)
    server = subprocess.Popen(
        [sys.executable, "-B", str(app_entrypoint)],
        cwd=LOCAL_CV_APP,
        env=environment,
    )

    try:
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            exit_code = server.poll()
            if exit_code is not None:
                raise RuntimeError(
                    "The local CV server exited before becoming ready "
                    f"(status {exit_code}). Is port {port} already in use?"
                )

            try:
                with urllib.request.urlopen(
                    health_url,
                    timeout=1,
                ) as response:
                    if response.status == 200:
                        break
            except (urllib.error.URLError, TimeoutError):
                time.sleep(0.25)
        else:
            raise RuntimeError(
                "The local CV server did not become ready within 90 seconds."
            )

        print(f"Opening {page_url}", flush=True)
        if not webbrowser.open(page_url):
            print(
                "A browser could not be opened automatically. "
                f"Open this URL manually: {page_url}",
                flush=True,
            )
        print("Press Ctrl+C here to stop the local demo.", flush=True)
        return server.wait()
    except KeyboardInterrupt:
        print("Stopping the local demo...", flush=True)
        return 0
    finally:
        if server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()


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
    primary_color = wait_for_valid_choice(
        "PRIMARY COLOR",
        PRIMARY_COLORS,
    )
    shape = wait_for_valid_choice(
        "SHAPE",
        PILL_SHAPES,
    )

    print(
        "Requested target: "
        f"day={day}, primary_color={primary_color}, shape={shape}",
        flush=True,
    )

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
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--local-demo",
        action="store_true",
        help="prompt for pill attributes and launch the local CV UI",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=10000,
        help="local demo port (default: 10000)",
    )
    arguments = parser.parse_args()

    if arguments.local_demo:
        raise SystemExit(run_local_pill_demo(arguments.port))

    asyncio.run(main())
