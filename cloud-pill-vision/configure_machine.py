import argparse
import asyncio
import copy
import os
from pathlib import Path
from urllib.parse import urlsplit

from viam.app.viam_client import ViamClient
from viam.rpc.dial import DialOptions


MODULE_NAME = "doseday_cloud-pill-vision"
MODULE_ID = "doseday:cloud-pill-vision"
MODULE_VERSION = "0.1.3"
SERVICE_NAME = "cloud-pill-detector"
MODEL = "doseday:cloud-pill-vision:cloud-pill-detector"


def load_environment() -> None:
    env_file = Path(__file__).resolve().parent.parent / ".env"
    if not env_file.exists():
        return
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        os.environ.setdefault(name.strip(), value.strip())


def upsert_named(items, name, value):
    for index, item in enumerate(items):
        if item.get("name") == name:
            items[index] = value
            return "updated"
    items.append(value)
    return "added"


async def configure(part_id: str, endpoint: str, apply: bool) -> None:
    parsed = urlsplit(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise SystemExit("--endpoint must be an absolute HTTP(S) URL")

    load_environment()
    required = ("VIAM_API_KEY", "VIAM_API_KEY_ID")
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise SystemExit(f"Missing environment variables: {', '.join(missing)}")

    options = DialOptions.with_api_key(
        api_key=os.environ["VIAM_API_KEY"],
        api_key_id=os.environ["VIAM_API_KEY_ID"],
    )
    async with await ViamClient.create_from_dial_options(options) as client:
        part = await client.app_client.get_robot_part(part_id)
        config = copy.deepcopy(dict(part.robot_config or {}))
        modules = config.setdefault("modules", [])
        services = config.setdefault("services", [])

        module_action = upsert_named(modules, MODULE_NAME, {
            "name": MODULE_NAME,
            "type": "registry",
            "module_id": MODULE_ID,
            "version": MODULE_VERSION,
        })
        service_action = upsert_named(services, SERVICE_NAME, {
            "name": SERVICE_NAME,
            "api": "rdk:service:vision",
            "model": MODEL,
            "attributes": {
                "camera_name": "follower-cam",
                "endpoint": endpoint,
                "timeout_seconds": 30,
            },
        })

        print(
            f"Dry run: module would be {module_action}; "
            f"service would be {service_action}."
        )
        print(f"Module: {MODULE_ID}@{MODULE_VERSION}")
        print(f"Service: {SERVICE_NAME} using follower-cam")
        print(f"Endpoint: {endpoint}")
        if not apply:
            return

        await client.app_client.update_robot_part(
            robot_part_id=part_id,
            name=part.name,
            robot_config=config,
            last_known_update=part.last_updated,
        )
        print("Applied configuration to the machine part.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Add the cloud pill Vision service to a Viam machine part."
    )
    parser.add_argument("--part-id", required=True)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write the configuration; omission performs a dry run",
    )
    args = parser.parse_args()
    asyncio.run(configure(args.part_id, args.endpoint, args.apply))
