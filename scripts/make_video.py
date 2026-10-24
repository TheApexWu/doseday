"""Build wrist-cam.mp4 from a recorded run folder at its measured frame rate and copy it to $DOSEDAY_FOOTAGE if set.

usage: python scripts/make_video.py <run_dir>
"""
import csv
import os
import shutil
import subprocess
import sys
from pathlib import Path

FOOTAGE = os.environ.get("DOSEDAY_FOOTAGE")  # optional folder to copy each video into

run = Path(sys.argv[1])
rows = list(csv.DictReader((run / "samples.csv").open()))
if len(rows) < 2:
    sys.exit(f"{run}: no samples recorded")
span = float(rows[-1]["unix_time"]) - float(rows[0]["unix_time"])
fps = round((len(rows) - 1) / span, 2)
mp4 = run / "wrist-cam.mp4"
subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-framerate", str(fps), "-i", str(run / "frames" / "%05d.jpg"),
                "-frames:v", str(len(rows)), "-c:v", "libx264", "-pix_fmt", "yuv420p", str(mp4)], check=True)
dest = mp4
if FOOTAGE:
    Path(FOOTAGE).mkdir(parents=True, exist_ok=True)
    dest = Path(FOOTAGE) / f"{run.name}-wrist-cam.mp4"
    shutil.copy(mp4, dest)
print(f"{len(rows)} samples over {span:.0f} s -> {dest}")
