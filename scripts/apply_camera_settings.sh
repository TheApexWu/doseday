#!/usr/bin/env bash
set -euo pipefail

CAMERA_DEVICE="${CAMERA_DEVICE:-/dev/v4l/by-id/usb-icSpring_icspring_camera-video-index0}"
CAMERA_WAIT_SECONDS="${CAMERA_WAIT_SECONDS:-30}"
CAMERA_EXPOSURE="${CAMERA_EXPOSURE:-100}"
CAMERA_BRIGHTNESS="${CAMERA_BRIGHTNESS:--15}"
CAMERA_CONTRAST="${CAMERA_CONTRAST:-42}"
CAMERA_GAMMA="${CAMERA_GAMMA:-55}"
CAMERA_SATURATION="${CAMERA_SATURATION:-40}"
CAMERA_WHITE_BALANCE="${CAMERA_WHITE_BALANCE:-4000}"
CAMERA_POWER_LINE_FREQUENCY="${CAMERA_POWER_LINE_FREQUENCY:-2}"

if ! command -v v4l2-ctl >/dev/null 2>&1; then
  echo "camera-settings: v4l2-ctl is required (install v4l-utils)" >&2
  exit 1
fi

for ((attempt = 0; attempt < CAMERA_WAIT_SECONDS; attempt++)); do
  [[ -e "$CAMERA_DEVICE" ]] && break
  sleep 1
done

if [[ ! -e "$CAMERA_DEVICE" ]]; then
  echo "camera-settings: camera not found: $CAMERA_DEVICE" >&2
  exit 1
fi

controls="$(v4l2-ctl -d "$CAMERA_DEVICE" --list-ctrls 2>/dev/null)"

set_control() {
  local name="$1"
  local value="$2"

  if ! grep -Eq "^[[:space:]]*${name}[[:space:]]" <<<"$controls"; then
    echo "camera-settings: skipping unsupported control $name" >&2
    return
  fi

  v4l2-ctl -d "$CAMERA_DEVICE" --set-ctrl="${name}=${value}"
}

set_control auto_exposure 1
set_control exposure_time_absolute "$CAMERA_EXPOSURE"
set_control white_balance_automatic 0
set_control white_balance_temperature "$CAMERA_WHITE_BALANCE"
set_control brightness "$CAMERA_BRIGHTNESS"
set_control contrast "$CAMERA_CONTRAST"
set_control gamma "$CAMERA_GAMMA"
set_control saturation "$CAMERA_SATURATION"
set_control backlight_compensation 0
set_control power_line_frequency "$CAMERA_POWER_LINE_FREQUENCY"

echo "camera-settings: applied settings to $CAMERA_DEVICE"
