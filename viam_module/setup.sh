#!/usr/bin/env bash
set -euo pipefail

MODULE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
python3 -m venv "$MODULE_DIR/.venv"
"$MODULE_DIR/.venv/bin/pip" install --upgrade pip
"$MODULE_DIR/.venv/bin/pip" install -r "$MODULE_DIR/requirements.txt"
