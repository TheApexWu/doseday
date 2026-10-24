#!/usr/bin/env bash
# Downloads a third-party YOLOv8s pill detector, pinned to one upstream commit and checked by hash.
# The upstream repo has no licence, so we link to it instead of committing the weights.
set -euo pipefail
REPO="thulasi-bikku/YOLO11-Based-Pill-Recognition-OCR-Classification-System"
COMMIT="8b4988cf7ef00b18530e5a88a3350ebab80227a7"
SHA256="bba2abe45cca843e3794c0c7c80a9bf5b35e15072c2fa2e6e000cebec698bf16"
DEST="$(cd "$(dirname "$0")" && pwd)/pill-yolov8s.pt"

curl -fsSL -A "doseday-fetch/1.0" -o "$DEST.part" "https://github.com/$REPO/raw/$COMMIT/models/best.pt"
got="$(shasum -a 256 "$DEST.part" | cut -c1-64)"
if [ "$got" != "$SHA256" ]; then
  rm -f "$DEST.part"
  echo "hash mismatch: expected $SHA256, got $got" >&2
  exit 1
fi
mv "$DEST.part" "$DEST"
echo "saved $DEST"
