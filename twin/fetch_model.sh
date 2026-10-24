#!/usr/bin/env bash
# Fetch the vendor's SO-101 MuJoCo model (Apache-2.0, TheRobotStudio/SO-ARM100) into twin/vendor/.
# Pinned so the twin's arm stays the one we validated against the robot's own poses.
set -euo pipefail
SHA=a758567c3978dfeefe282ede0500085a48fe8f78
DEST="$(cd "$(dirname "$0")" && pwd)/vendor"
[ -f "$DEST/SO101/so101_new_calib_camera.xml" ] && { echo "model already in $DEST/SO101"; exit 0; }
TMP="$(mktemp -d)"
git clone -q --filter=blob:none --no-checkout https://github.com/TheRobotStudio/SO-ARM100 "$TMP/so-arm100"
git -C "$TMP/so-arm100" sparse-checkout set --no-cone /Simulation/SO101/ /LICENSE
git -C "$TMP/so-arm100" checkout -q "$SHA"
mkdir -p "$DEST"
cp -R "$TMP/so-arm100/Simulation/SO101" "$DEST/"
cp "$TMP/so-arm100/LICENSE" "$DEST/SO101/LICENSE"
rm -rf "$TMP"
echo "model in $DEST/SO101 at $SHA"
