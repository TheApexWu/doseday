"""Build wrist-cam.mp4 from a recorded run folder at its measured frame rate and copy it to the footage folder.

usage: python scripts/make_video.py <run_dir>
"""
import csv
import shutil
import subprocess
import sys
from pathlib import Path

FOOTAGE = Path.home() / "Desktop" / "Projects" / "Hackathons" / "Doseday-Footage"

run = Path(sys.argv[1])
rows = list(csv.DictReader((run / "samples.csv").open()))
if len(rows) < 2:
    sys.exit(f"{run}: no samples recorded")
span = float(rows[-1]["unix_time"]) - float(rows[0]["unix_time"])
fps = round((len(rows) - 1) / span, 2)
mp4 = run / "wrist-cam.mp4"
subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-framerate", str(fps), "-i", str(run / "frames" / "%05d.jpg"),
                "-frames:v", str(len(rows)), "-c:v", "libx264", "-pix_fmt", "yuv420p", str(mp4)], check=True)
FOOTAGE.mkdir(parents=True, exist_ok=True)
shutil.copy(mp4, FOOTAGE / f"{run.name}-wrist-cam.mp4")
print(f"{len(rows)} samples over {span:.0f} s -> {FOOTAGE / (run.name + '-wrist-cam.mp4')}")
