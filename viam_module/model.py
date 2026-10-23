"""Viam vision service exposing every configured color in one detection response."""
from typing import Mapping, Optional, Sequence, Tuple, cast

import cv2
import numpy as np
from viam.components.camera import Camera
from viam.media.video import ViamImage
from viam.proto.app.robot import ComponentConfig
from viam.proto.common import ResourceName
from viam.proto.service.vision import Detection, GetPropertiesResponse
from viam.resource.base import ResourceBase
from viam.resource.easy_resource import EasyResource, stub_model
from viam.services.vision import CaptureAllResult, Vision
from viam.utils import ValueTypes, struct_to_dict

from multi_color_detector import detect_colors


@stub_model
class MultiColorDetector(Vision, EasyResource):
    MODEL = "doseday:vision:multi-color-detector"

    def __init__(self, name: str):
        super().__init__(name)
        self.camera_name = ""
        self.camera: Optional[Camera] = None
        self.options = {}

    @classmethod
    def new(cls, config: ComponentConfig,
            dependencies: Mapping[ResourceName, ResourceBase]):
        service = cls(config.name)
        service.reconfigure(config, dependencies)
        return service

    @classmethod
    def validate_config(cls, config: ComponentConfig) -> Tuple[Sequence[str], Sequence[str]]:
        attrs = struct_to_dict(config.attributes)
        camera_name = attrs.get("camera_name")
        if not isinstance(camera_name, str) or not camera_name:
            raise ValueError("camera_name is required and must be a string")
        cls._options(attrs)
        return [camera_name], []

    @staticmethod
    def _options(attrs: Mapping) -> dict:
        options = {
            "min_area_px": int(attrs.get("min_area_px", 200)),
            "saturation_min": int(attrs.get("saturation_min", 80)),
            "value_min": int(attrs.get("value_min", 50)),
            "black_value_max": int(attrs.get("black_value_max", 45)),
            "max_area_fraction": float(attrs.get("max_area_fraction", 0.25)),
        }
        if options["min_area_px"] < 1:
            raise ValueError("min_area_px must be positive")
        for name in ("saturation_min", "value_min", "black_value_max"):
            if not 0 <= options[name] <= 255:
                raise ValueError(f"{name} must be between 0 and 255")
        if not 0 < options["max_area_fraction"] <= 1:
            raise ValueError("max_area_fraction must be in (0, 1]")
        return options

    def reconfigure(self, config: ComponentConfig,
                    dependencies: Mapping[ResourceName, ResourceBase]):
        attrs = struct_to_dict(config.attributes)
        self.camera_name = str(attrs["camera_name"])
        resource = dependencies.get(Camera.get_resource_name(self.camera_name))
        if resource is None:
            raise ValueError(f"camera dependency not found: {self.camera_name}")
        self.camera = cast(Camera, resource)
        self.options = self._options(attrs)

    @staticmethod
    def _decode(image: ViamImage) -> np.ndarray:
        decoded = cv2.imdecode(np.frombuffer(image.data, np.uint8), cv2.IMREAD_COLOR)
        if decoded is None:
            raise ValueError(f"could not decode image ({image.mime_type})")
        return decoded

    def _detect(self, image: ViamImage) -> list[Detection]:
        return [
            Detection(
                x_min=box.x_min,
                y_min=box.y_min,
                x_max=box.x_max,
                y_max=box.y_max,
                confidence=box.confidence,
                class_name=box.label,
            )
            for box in detect_colors(self._decode(image), **self.options)
        ]

    async def _image(self, camera_name: str) -> ViamImage:
        if camera_name and camera_name != self.camera_name:
            raise ValueError(f"camera {camera_name!r} is not a configured dependency")
        if self.camera is None:
            raise RuntimeError("camera dependency is unavailable")
        images, _ = await self.camera.get_images()
        if not images:
            raise RuntimeError("camera returned no images")
        return images[0]

    async def get_detections(self, image: ViamImage, *,
                             extra: Optional[Mapping[str, ValueTypes]] = None,
                             timeout: Optional[float] = None) -> list[Detection]:
        return self._detect(image)

    async def get_detections_from_camera(self, camera_name: str, *,
                                         extra: Optional[Mapping[str, ValueTypes]] = None,
                                         timeout: Optional[float] = None) -> list[Detection]:
        return self._detect(await self._image(camera_name))

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
        image = await self._image(camera_name)
        return CaptureAllResult(
            image=image if return_image else None,
            classifications=[] if return_classifications else None,
            detections=self._detect(image) if return_detections else None,
            objects=[] if return_object_point_clouds else None,
            detections_3d=[] if return_detections_3d else None,
        )

    async def get_properties(self, *,
                             extra: Optional[Mapping[str, ValueTypes]] = None,
                             timeout: Optional[float] = None) -> GetPropertiesResponse:
        return GetPropertiesResponse(
            classifications_supported=False,
            detections_supported=True,
            object_point_clouds_supported=False,
            detections_3d_supported=False,
            default_camera=self.camera_name,
        )
