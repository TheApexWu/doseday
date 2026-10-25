#!/bin/bash
# One command to save and share work: tests, commit everything on your branch, push.
#   ./tools/checkpoint.sh "T1 calibration: residual 1.8 mm"
# Run it every ~30 min, after every test result, and before any arm run.
set -euo pipefail
cd "$(dirname "$0")/.."
msg=${1:-"checkpoint $(date +%H:%M)"}
branch=$(git branch --show-current)
if [ "$branch" = "main" ]; then
    echo "on main: switch to your branch first (git switch -c <name>/<task>)"; exit 1
fi
log=$(mktemp)
if ! python3 -B -m pytest -q >"$log" 2>&1; then
    tail -5 "$log"
    msg="WIP (tests failing) $msg"   # still push: a failing push beats unshared work
fi
git add -A
if git diff --cached --quiet; then
    echo "nothing new to commit"
else
    git commit -q -m "$msg"
fi
git push -q -u origin "$branch" && echo "pushed $branch: $(git log --oneline -1)"
