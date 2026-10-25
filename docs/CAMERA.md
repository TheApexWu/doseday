# Camera and vision service

## Vision service

`demo-anything-detector` is Viam's built-in `color_detector` on `follower-cam`. It boxes orange regions
(`#FFA500`) and labels them `orange-object`. It is not connected to arm planning or motion. In the Viam app,
open **CONTROL**, select `demo-anything-detector`, and choose `follower-cam` to see the overlay.

To verify the same service from the SDK without moving the arm:

```
PILL_CAMERA=follower-cam python tools/vision_probe.py
```

The command uses the same `VIAM_ADDRESS`, `VIAM_API_KEY_ID`, and `VIAM_API_KEY` environment variables as
`arm.py`. Override the service name with `PILL_VISION_SERVICE`.

## Camera settings at boot

The icSpring camera defaults to automatic exposure, which can lift a black mat to gray. On the robot, install
the supplied systemd service to apply an initial manual baseline at every boot:

```
sudo ./scripts/install_camera_settings_service.sh
```

Watch `follower-cam` in the Viam Control tab, then edit the defaults in `scripts/apply_camera_settings.sh` if the
lighting requires a different exposure. Reinstall and apply changes immediately with:

```
sudo ./scripts/install_camera_settings_service.sh
```

The defaults select 60 Hz anti-flicker. Persistent site overrides can be placed in
`/etc/default/doseday-camera-settings`, for example `CAMERA_EXPOSURE=80` or
`CAMERA_POWER_LINE_FREQUENCY=1` for a 50 Hz location. The other settings can also be overridden with the
environment variables declared at the top of the script.
