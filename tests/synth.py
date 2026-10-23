"""Synthetic mats for tests and for a no-hardware dry run: python tests/synth.py out_dir"""
import json
import sys
from pathlib import Path

import cv2
import numpy as np

BLACK, WHITE = 15, 240
OVAL_C, CAPSULE_C, ROUND_C, BLUE_C = (235, 235, 235), (40, 60, 120), (0, 140, 255), (200, 40, 20)


def mat(w=640, h=480, kind="black", noise=0.0, seed=0) -> np.ndarray:
    img = np.full((h, w, 3), WHITE if kind == "white" else BLACK, np.uint8)
    if kind == "split":
        img[:, w // 2:] = WHITE
    if noise:
        n = np.random.default_rng(seed).normal(0, noise, img.shape)
        img = np.clip(img.astype(float) + n, 0, 255).astype(np.uint8)
    return img


def ellipse(img, cx, cy, major, minor, angle_deg, color):
    """cv2.ellipse angle rotates the major axis toward +y (down), same as vision's convention;
    test_convention_ground_truth checks that by sampling pixels rather than trusting this."""
    cv2.ellipse(img, (int(cx), int(cy)), (int(major / 2), int(minor / 2)), angle_deg, 0, 360, color, -1)


def capsule(img, cx, cy, length, width, angle_deg, color):
    """Rectangle with round caps; length is end to end."""
    u = np.array([np.cos(np.radians(angle_deg)), np.sin(np.radians(angle_deg))])
    n = np.array([-u[1], u[0]])
    r, half = width / 2, (length - width) / 2
    c = np.array([cx, cy], float)
    a, b = c - u * half, c + u * half
    poly = np.array([a + n * r, b + n * r, b - n * r, a - n * r], np.int32)
    cv2.fillConvexPoly(img, poly, color)
    for p in (a, b):
        cv2.circle(img, tuple(int(v) for v in p), int(r), color, -1)


def scene() -> tuple[np.ndarray, dict]:
    """Split mat: 3 white ovals + merged pair on black; 2 brown capsules + 1 blue unknown on white."""
    img = mat(kind="split", noise=4)
    truth = {"ovals": [(80, 100, 30), (200, 300, 120), (120, 400, 75)], "capsules": [(420, 120, 45), (540, 330, 160)]}
    for x, y, a in truth["ovals"]:
        ellipse(img, x, y, 60, 24, a, OVAL_C)
    ellipse(img, 230, 120, 60, 24, 0, OVAL_C)  # merged pair: 20 px apart across the minor axis
    ellipse(img, 230, 140, 60, 24, 0, OVAL_C)
    for x, y, a in truth["capsules"]:
        capsule(img, x, y, 56, 20, a, CAPSULE_C)
    cv2.circle(img, (480, 420), 13, BLUE_C, -1)
    return img, truth


def single(color, kind, shape="ellipse"):
    img = mat(kind=kind)
    (ellipse if shape == "ellipse" else capsule)(img, 320, 240, 60 if shape == "ellipse" else 56,
                                                  24 if shape == "ellipse" else 20, 30, color)
    return img


def frames(color, length, width, n=10, seed=0, kind="black"):
    """n one-pill frames of the same type: random spot and angle, sensor noise."""
    rng = np.random.default_rng(seed)
    out = []
    for i in range(n):
        img = mat(kind=kind, noise=3, seed=seed * 100 + i)
        ellipse(img, rng.uniform(200, 440), rng.uniform(150, 330), length, width, rng.uniform(0, 180), color)
        out.append(img)
    return out


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    out.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import provenance
    imgs = {"scene.png": scene()[0], "enroll_oval.png": single(OVAL_C, "black"),
            "enroll_capsule.png": single(CAPSULE_C, "white", "capsule")}
    for i, f in enumerate(frames(OVAL_C, 60, 24, seed=1)):
        imgs[f"data/small_oval/{i:02d}.png"] = f
    for i, f in enumerate(frames(OVAL_C, 64, 25.5, seed=2)):
        imgs[f"data/big_oval/{i:02d}.png"] = f
    for name, img in imgs.items():
        (out / name).parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(out / name), img)
        provenance.write(out / name, provenance.SYNTHETIC)
    print("wrote", len(imgs), "images (synthetic sidecars; on site use capture.py)")
    print(json.dumps({"next": "python demo.py loo --data data --allow-foreign"}))
