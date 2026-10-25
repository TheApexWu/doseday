#!/bin/sh
set -eu

MODULE_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec "$MODULE_DIR/pyinstaller/cloud_pill_detector/cloud_pill_detector" "$@"
