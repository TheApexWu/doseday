#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "camera-settings: run this installer as root" >&2
  exit 1
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

install -D -m 0755 \
  "$SCRIPT_DIR/apply_camera_settings.sh" \
  /usr/local/libexec/doseday/apply_camera_settings.sh
install -D -m 0644 \
  "$REPO_DIR/systemd/doseday-camera-settings.service" \
  /etc/systemd/system/doseday-camera-settings.service

systemctl daemon-reload
systemctl enable doseday-camera-settings.service
systemctl restart doseday-camera-settings.service
systemctl --no-pager --full status doseday-camera-settings.service
