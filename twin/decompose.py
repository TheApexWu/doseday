"""Split the vendor's arm meshes into convex pieces (CoACD) so contact follows the real shapes.

MuJoCo collides each mesh as its convex hull: the claw's hull fills the gap between the jaws and the wrist's
hollows, so it rests on an open lid where the real claw passes. Pieces land in assets/coacd/ with a manifest that
scene.write_arm reads.

    python twin/decompose.py          once, after fetch_model.sh (a few minutes)
"""
import json
import re
import sys
import time
from pathlib import Path

import coacd
import numpy as np
import trimesh

VENDOR = Path(__file__).resolve().parent / "vendor" / "SO101"
SRC = VENDOR / "so101_new_calib_camera.xml"
OUT = VENDOR / "assets" / "coacd"
MANIFEST = OUT / "manifest.json"
THRESHOLD = 0.05  # CoACD concavity: lower = more, tighter pieces


def collision_meshes(xml: str) -> list[str]:
    return sorted(set(re.findall(r'<geom type="mesh" class="collision"[^>]*mesh="([^"]+)"', xml)))


def main() -> int:
    xml = SRC.read_text()
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
    for name in collision_meshes(xml):
        if name in manifest:
            continue
        t0 = time.time()
        mesh = trimesh.load(VENDOR / "assets" / f"{name}.stl", force="mesh")
        parts = coacd.run_coacd(coacd.Mesh(np.asarray(mesh.vertices), np.asarray(mesh.faces)), threshold=THRESHOLD)
        files = []
        for i, (v, f) in enumerate(parts):
            out = OUT / f"{name}_{i}.stl"
            trimesh.Trimesh(v, f).export(out)
            files.append(out.name)
        manifest[name] = files
        MANIFEST.write_text(json.dumps(manifest, indent=1))
        print(f"{name}: {len(files)} pieces in {time.time() - t0:.0f} s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
