#!/bin/sh
cd `dirname $0`

# Create a virtual environment to run our code
VENV_NAME="venv"
PYTHON="$VENV_NAME/bin/python"

if ! $PYTHON -m pip install pyinstaller -Uqq; then
    exit 1
fi

$PYTHON -m PyInstaller \
    --clean \
    --onedir \
    --name cloud_pill_detector \
    --distpath dist/pyinstaller \
    --collect-all viam \
    --exclude-module=PIL \
    src/main.py

cp run.sh dist/main
chmod +x dist/main

TAR_FILES="meta.json ./dist/main ./dist/pyinstaller/cloud_pill_detector"
FIRST_RUN=$($PYTHON -c "import json; print(json.load(open('meta.json')).get('first_run', ''))" 2>/dev/null)
if [ -n "$FIRST_RUN" ] && [ -f "$FIRST_RUN" ]; then
    TAR_FILES="$TAR_FILES $FIRST_RUN"
fi
tar -czvf dist/archive.tar.gz $TAR_FILES
