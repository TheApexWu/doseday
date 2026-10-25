import asyncio
import json
import os
import uuid
from typing import Any, ClassVar, List, Mapping, Optional, Sequence, Tuple, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from typing_extensions import Self
from viam.components.camera import Camera
from viam.media.video import ViamImage
from viam.proto.app.robot import ComponentConfig
from viam.proto.common import PointCloudObject, ResourceName
from viam.proto.service.vision import (
    Classification,
    Detection,
    Detection3D,
    GetPropertiesResponse,
)
from viam.resource.base import ResourceBase
from viam.resource.easy_resource import EasyResource
from viam.resource.types import Model, ModelFamily
from viam.services.vision import CaptureAllResult, Vision
from viam.utils import ValueTypes, struct_to_dict


ALLOWED_COLORS = {
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
}
ALLOWED_SHAPES = {"round", "oval", "capsule", "other"}


def _multipart_body(
    image_bytes: bytes,
    image_filename: str,
    image_mime: str,
    target_color: str,
    target_shape: str,
) -> Tuple[bytes, str]:
    boundary = f"viam-pill-{uuid.uuid4().hex}"
    chunks: list[bytes] = []

    for name, value in (
        ("target_color", target_color),
        ("target_shape", target_shape),
    ):
        chunks.extend([
            f"--{boundary}\r\n".encode(),
            (
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
            ).encode(),
            value.encode(),
            b"\r\n",
        ])

    chunks.extend([
        f"--{boundary}\r\n".encode(),
        (
            'Content-Disposition: form-data; name="image"; '
            f'filename="{image_filename}"\r\n'
        ).encode(),
        f"Content-Type: {image_mime}\r\n\r\n".encode(),
        image_bytes,
        b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ])
    return b"".join(chunks), boundary


def _label_for_detection(
    detection: Mapping[str, Any],
    target_color: str,
    target_shape: str,
) -> str:
    colors = detection.get("colors") or []
    detected_color = target_color
    if colors and isinstance(colors[0], Mapping):
        detected_color = str(colors[0].get("name") or target_color)
    detected_shape = str(detection.get("shape") or target_shape)
    return f"{detected_color}-{detected_shape}"


def _unique_viam_detections(
    payload: Mapping[str, Any],
    target_color: str,
    target_shape: str,
) -> List[Detection]:
    if not payload.get("ok"):
        raise RuntimeError(str(payload.get("error") or "Brev detection failed"))

    result = payload.get("result")
    if not isinstance(result, Mapping):
        raise RuntimeError("Brev response is missing a result object")

    detections = result.get("detections")
    if not isinstance(detections, list):
        raise RuntimeError("Brev response is missing its detections list")

    # A robot must not choose arbitrarily when two pills satisfy the request.
    if result.get("match_status") != "unique" or len(detections) != 1:
        return []

    source = detections[0]
    if not isinstance(source, Mapping):
        raise RuntimeError("Brev returned an invalid detection")
    box = source.get("bbox")
    if not isinstance(box, Mapping):
        raise RuntimeError("Brev detection is missing a bounding box")

    try:
        detection = {
            "x_min": int(box["x_min"]),
            "y_min": int(box["y_min"]),
            "x_max": int(box["x_max"]),
            "y_max": int(box["y_max"]),
            "confidence": float(source["confidence"]),
            "class_name": _label_for_detection(
                source,
                target_color,
                target_shape,
            ),
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(f"Brev returned an invalid detection: {exc}") from exc

    if detection["x_min"] >= detection["x_max"]:
        raise RuntimeError("Brev returned an invalid horizontal bounding box")
    if detection["y_min"] >= detection["y_max"]:
        raise RuntimeError("Brev returned an invalid vertical bounding box")
    if not 0 <= detection["confidence"] <= 1:
        raise RuntimeError("Brev returned confidence outside [0, 1]")

    return [cast(Detection, detection)]


class CloudPillDetector(Vision, EasyResource):
    MODEL: ClassVar[Model] = Model(
        ModelFamily("doseday", "cloud-pill-vision"),
        "cloud-pill-detector",
    )

    @classmethod
    def new(
        cls,
        config: ComponentConfig,
        dependencies: Mapping[ResourceName, ResourceBase],
    ) -> Self:
        self = super().new(config, dependencies)
        attrs = struct_to_dict(config.attributes)
        self.DEPS = dependencies
        self.camera_name = str(attrs["camera_name"]).strip()
        self.endpoint = str(attrs["endpoint"]).strip()
        self.request_timeout = float(attrs.get("timeout_seconds", 30))
        self.api_token = os.environ.get("BREV_API_TOKEN", "").strip()
        self.target_color: Optional[str] = None
        self.target_shape: Optional[str] = None
        return self

    @classmethod
    def validate_config(
        cls,
        config: ComponentConfig,
    ) -> Tuple[Sequence[str], Sequence[str]]:
        attrs = struct_to_dict(config.attributes)
        camera_name = str(attrs.get("camera_name") or "").strip()
        endpoint = str(attrs.get("endpoint") or "").strip()
        if not camera_name:
            raise ValueError("camera_name is required")
        parsed = urlsplit(endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("endpoint must be an absolute HTTP(S) URL")
        try:
            timeout = float(attrs.get("timeout_seconds", 30))
        except (TypeError, ValueError) as exc:
            raise ValueError("timeout_seconds must be a number") from exc
        if not 0 < timeout <= 120:
            raise ValueError("timeout_seconds must be greater than 0 and at most 120")
        return [camera_name], []

    def _get_camera(self, camera_name: str) -> Camera:
        resolved_name = camera_name or self.camera_name
        camera = self.DEPS.get(Camera.get_resource_name(resolved_name))
        if camera is None:
            raise RuntimeError(
                f"camera {resolved_name!r} is not a dependency; configure "
                f'"camera_name": "{resolved_name}"'
            )
        return cast(Camera, camera)

    async def _get_camera_image(self, camera_name: str) -> ViamImage:
        images, _ = await self._get_camera(camera_name).get_images()
        if not images:
            raise RuntimeError("camera returned no images")
        return images[0]

    @staticmethod
    def _encode_image(image: ViamImage) -> Tuple[bytes, str, str]:
        mime = str(image.mime_type).split("+", 1)[0].lower()
        if mime == "image/jpeg":
            return bytes(image.data), "frame.jpg", mime
        if mime == "image/png":
            return bytes(image.data), "frame.png", mime
        raise RuntimeError(
            "camera must return JPEG or PNG frames for cloud detection; "
            f"received {mime or 'an unknown MIME type'}"
        )

    def _post_detection(
        self,
        image_bytes: bytes,
        filename: str,
        mime_type: str,
        target_color: str,
        target_shape: str,
    ) -> Mapping[str, Any]:
        body, boundary = _multipart_body(
            image_bytes,
            filename,
            mime_type,
            target_color,
            target_shape,
        )
        headers = {
            "Accept": "application/json",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        }
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"

        request = Request(
            self.endpoint,
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.request_timeout) as response:
                response_body = response.read()
        except HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(
                f"Brev returned HTTP {exc.code}: {details}"
            ) from exc
        except (URLError, TimeoutError) as exc:
            raise RuntimeError(f"could not reach Brev detector: {exc}") from exc

        try:
            payload = json.loads(response_body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise RuntimeError("Brev returned non-JSON data") from exc
        if not isinstance(payload, Mapping):
            raise RuntimeError("Brev returned a non-object JSON response")
        return payload

    async def _detect(self, image: ViamImage) -> List[Detection]:
        target_color = self.target_color
        target_shape = self.target_shape
        if target_color is None or target_shape is None:
            self.logger.info("No pill target selected; returning no detections")
            return []

        image_bytes, filename, mime_type = self._encode_image(image)
        payload = await asyncio.to_thread(
            self._post_detection,
            image_bytes,
            filename,
            mime_type,
            target_color,
            target_shape,
        )
        detections = _unique_viam_detections(
            payload,
            target_color,
            target_shape,
        )
        if not detections:
            result = payload.get("result")
            status = result.get("match_status") if isinstance(result, Mapping) else None
            self.logger.warning(
                "Pill target did not produce a unique match; status=%s",
                status,
            )
        return detections

    async def capture_all_from_camera(
        self,
        camera_name: str,
        return_image: bool = False,
        return_classifications: bool = False,
        return_detections: bool = False,
        return_object_point_clouds: bool = False,
        return_detections_3d: bool = False,
        *,
        extra: Optional[Mapping[str, ValueTypes]] = None,
        timeout: Optional[float] = None,
    ) -> CaptureAllResult:
        image = await self._get_camera_image(camera_name)
        result = CaptureAllResult()
        if return_image:
            result.image = image
        if return_detections:
            result.detections = await self._detect(image)
        if return_classifications:
            result.classifications = []
        if return_object_point_clouds:
            result.objects = []
        if return_detections_3d and hasattr(result, "detections_3d"):
            result.detections_3d = []
        return result

    async def get_detections_from_camera(
        self,
        camera_name: str,
        *,
        extra: Optional[Mapping[str, ValueTypes]] = None,
        timeout: Optional[float] = None,
    ) -> List[Detection]:
        return await self._detect(await self._get_camera_image(camera_name))

    async def get_detections(
        self,
        image: ViamImage,
        *,
        extra: Optional[Mapping[str, ValueTypes]] = None,
        timeout: Optional[float] = None,
    ) -> List[Detection]:
        return await self._detect(image)

    async def get_classifications_from_camera(
        self,
        camera_name: str,
        count: int,
        *,
        extra: Optional[Mapping[str, ValueTypes]] = None,
        timeout: Optional[float] = None,
    ) -> List[Classification]:
        return []

    async def get_classifications(
        self,
        image: ViamImage,
        count: int,
        *,
        extra: Optional[Mapping[str, ValueTypes]] = None,
        timeout: Optional[float] = None,
    ) -> List[Classification]:
        return []

    async def get_detections_3d(
        self,
        camera_name: str,
        *,
        extra: Optional[Mapping[str, ValueTypes]] = None,
        timeout: Optional[float] = None,
    ) -> List[Detection3D]:
        return []

    async def get_object_point_clouds(
        self,
        camera_name: str,
        *,
        extra: Optional[Mapping[str, ValueTypes]] = None,
        timeout: Optional[float] = None,
    ) -> List[PointCloudObject]:
        return []

    async def get_properties(
        self,
        *,
        extra: Optional[Mapping[str, ValueTypes]] = None,
        timeout: Optional[float] = None,
    ) -> Vision.Properties:
        return GetPropertiesResponse(
            classifications_supported=False,
            detections_supported=True,
            object_point_clouds_supported=False,
        )

    async def do_command(
        self,
        command: Mapping[str, ValueTypes],
        *,
        timeout: Optional[float] = None,
        **kwargs: Any,
    ) -> Mapping[str, ValueTypes]:
        action = str(command.get("command") or "").strip().lower()
        if action == "set_target":
            color = str(command.get("primary_color") or "").strip().lower()
            shape = str(command.get("shape") or "").strip().lower()
            if color not in ALLOWED_COLORS:
                raise ValueError(
                    f"primary_color must be one of {sorted(ALLOWED_COLORS)}"
                )
            if shape not in ALLOWED_SHAPES:
                raise ValueError(f"shape must be one of {sorted(ALLOWED_SHAPES)}")
            self.target_color = color
            self.target_shape = shape
        elif action == "clear_target":
            self.target_color = None
            self.target_shape = None
        elif action != "get_target":
            raise ValueError(
                "command must be set_target, clear_target, or get_target"
            )

        return {
            "configured": self.target_color is not None and self.target_shape is not None,
            "primary_color": self.target_color or "",
            "shape": self.target_shape or "",
        }

    async def get_status(
        self,
        *,
        timeout: Optional[float] = None,
        **kwargs: Any,
    ) -> Mapping[str, ValueTypes]:
        return {
            "endpoint": self.endpoint,
            "camera_name": self.camera_name,
            "target_configured": (
                self.target_color is not None and self.target_shape is not None
            ),
            "primary_color": self.target_color or "",
            "shape": self.target_shape or "",
        }
