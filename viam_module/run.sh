#!/usr/bin/env bash
set -euo pipefail

MODULE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ ! -x "$MODULE_DIR/.venv/bin/python" ]]; then
  echo "multi-color-detector: run viam_module/setup.sh first" >&2
  exit 1
fi

export PYTHONPATH="$MODULE_DIR/..${PYTHONPATH:+:$PYTHONPATH}"
exec "$MODULE_DIR/.venv/bin/python" "$MODULE_DIR/main.py" "$@"
