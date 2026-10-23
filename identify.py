"""Pill identity by nearest enrolled example, with refusal: anything far from every enrolled pill is "unknown".

  python identify.py serve [--engine features|dinov2] [--port 8765]   gallery = data/<label>/*.png|jpg
  python identify.py check data/tums/x.png                             identify one image locally
  python identify.py client http://HOST:8765 image.jpg                 call a running server

A softmax classifier always names some class; nearest neighbour with a distance limit can say "unknown",
which is the answer that matters when a wrong pill is the failure. The limit is set from the gallery itself
(leave-one-out distances) unless --limit is given.

engines:
  features  colour (Lab) + size + roundness from vision.detect. No ML, runs anywhere. The fallback.
  dinov2    DINOv2-small crop embeddings, cosine distance. Needs torch; meant for the Brev GPU.
"""
import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import cv2
import numpy as np

import vision

HERE = Path(__file__).parent
DATA = HERE / "data"
LIMIT_MARGIN = 1.5  # unknown when farther than this times the worst leave-one-out match in the gallery
NOT_PILLS = {"scene", "reject", "unknown"}


def crops(img: np.ndarray, pad: int = 6):
    """Each detected blob with a square crop around it."""
    out = []
    for p in vision.detect(img):
        x, y, w, h = cv2.boundingRect(np.array(p.box_px, np.int32))
        s = max(w, h) + 2 * pad
        x0, y0 = int(max(p.cx - s / 2, 0)), int(max(p.cy - s / 2, 0))
        out.append((p, img[y0:y0 + s, x0:x0 + s]))
    return out


def enrol_pick(found, shape):
    """The blob nearest the image centre: enrolment photos are framed on one pill, and the largest blob is
    often tape or the organizer at the edge of a wide-angle frame."""
    cy, cx = shape[0] / 2, shape[1] / 2
    return min(found, key=lambda pc: (pc[0].cx - cx) ** 2 + (pc[0].cy - cy) ** 2)


class Features:
    """Mean Lab colour, log area and aspect, scaled by the gallery's spread so no unit dominates.
    A feature that barely varies across the gallery (two pill types of equal area) would get a tiny scale and
    turn camera noise into a large distance, so each scale has a floor at measurement noise:
    5 Lab units, 10% area, 0.1 aspect."""
    name = "features"
    FLOOR = np.array([5.0, 5.0, 5.0, 0.1, 0.1])
    min_limit = 1.0  # one noise unit: never call a pill unknown for a difference the camera can't measure

    def __init__(self):
        self.scale = None

    def raw(self, pill, _crop) -> np.ndarray:
        return np.array([*pill.lab, np.log(pill.area_px), pill.aspect], float)

    def fit(self, vecs: np.ndarray):
        self.scale = np.maximum(vecs.std(axis=0), self.FLOOR)

    def dist(self, a: np.ndarray, b: np.ndarray) -> np.ndarray:
        return np.linalg.norm((b - a) / self.scale, axis=-1)


class Dino:
    """HARDWARE-ONLY in practice: downloads facebook/dinov2-small via torch hub on first use."""
    name = "dinov2"
    min_limit = 0.05  # cosine distance; same role as Features.min_limit, to be checked on real crops

    def __init__(self):
        import torch
        self.torch = torch
        self.dev = "cuda" if torch.cuda.is_available() else "cpu"
        self.model = torch.hub.load("facebookresearch/dinov2", "dinov2_vits14").to(self.dev).eval()

    def raw(self, _pill, crop) -> np.ndarray:
        x = cv2.resize(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB), (224, 224)).astype(np.float32) / 255
        x = (x - [0.485, 0.456, 0.406]) / [0.229, 0.224, 0.225]
        t = self.torch.from_numpy(x.transpose(2, 0, 1)).float()[None].to(self.dev)
        with self.torch.no_grad():
            v = self.model(t)[0].cpu().numpy()
        return v / np.linalg.norm(v)

    def fit(self, _vecs):
        pass

    def dist(self, a, b):
        return 1 - b @ a


class Gallery:
    def __init__(self, engine, root: Path = DATA, limit: float | None = None):
        self.engine, self.labels, vecs = engine, [], []
        for d in sorted(p for p in root.iterdir() if p.is_dir() and p.name not in NOT_PILLS):
            for f in sorted([*d.glob("*.png"), *d.glob("*.jpg")]):
                found = crops(cv2.imread(str(f)))
                if not found:
                    continue
                pill, crop = enrol_pick(found, cv2.imread(str(f)).shape)
                vecs.append(engine.raw(pill, crop))
                self.labels.append(d.name)
        if len(set(self.labels)) < 1 or len(vecs) < 2:
            raise SystemExit(f"gallery in {root} needs photos in data/<label>/ (found {len(vecs)})")
        self.vecs = np.array(vecs)
        engine.fit(self.vecs)
        self.limit = limit if limit is not None else max(LIMIT_MARGIN * self.leave_one_out(), engine.min_limit)

    def leave_one_out(self) -> float:
        """Worst distance from an enrolled photo to its nearest same-label neighbour."""
        worst = 0.0
        for i, v in enumerate(self.vecs):
            d = self.engine.dist(v, self.vecs)
            d[i] = np.inf
            same = [d[j] for j, lab in enumerate(self.labels) if lab == self.labels[i] and j != i]
            if same:
                worst = max(worst, float(min(same)))
        return worst

    def name(self, pill, crop) -> dict:
        d = self.engine.dist(self.engine.raw(pill, crop), self.vecs)
        i = int(np.argmin(d))
        known = d[i] <= self.limit
        return {"label": self.labels[i] if known else "unknown", "nearest": self.labels[i],
                "dist": round(float(d[i]), 4), "limit": round(self.limit, 4),
                "cx": round(pill.cx, 1), "cy": round(pill.cy, 1)}

    def identify(self, img: np.ndarray) -> list[dict]:
        return [self.name(p, c) for p, c in crops(img)]


def make_engine(name: str):
    return Dino() if name == "dinov2" else Features()


def make_server(gallery: Gallery, port: int) -> HTTPServer:
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            self._send({"engine": gallery.engine.name, "labels": sorted(set(gallery.labels)),
                        "n": len(gallery.labels), "limit": gallery.limit})

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            img = cv2.imdecode(np.frombuffer(body, np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                return self._send({"error": "body is not an image"}, 400)
            self._send({"pills": gallery.identify(img)})

        def _send(self, obj, code=200):
            data = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *_):  # one line per request is noise during a demo
            pass

    return HTTPServer(("0.0.0.0", port), H)


def serve(gallery: Gallery, port: int):
    print(f"{gallery.engine.name}: {len(gallery.labels)} photos, labels {sorted(set(gallery.labels))}, "
          f"unknown beyond {gallery.limit:.3f}; listening on :{port}", flush=True)
    make_server(gallery, port).serve_forever()


def client(url: str, img: np.ndarray, timeout: float = 5.0) -> list[dict]:
    """Laptop side. Raises on a dead server so the caller can fall back to the features engine."""
    import requests
    ok, jpg = cv2.imencode(".jpg", img)
    r = requests.post(url, data=jpg.tobytes(), timeout=timeout,
                      headers={"Content-Type": "image/jpeg", "User-Agent": "doseday-identify/1"})
    r.raise_for_status()
    return r.json()["pills"]


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["serve", "check", "client"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--engine", default="features", choices=["features", "dinov2"])
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--limit", type=float)
    a = ap.parse_args()
    if a.cmd == "client":
        print(json.dumps(client(a.args[0], cv2.imread(a.args[1])), indent=1))
        sys.exit()
    g = Gallery(make_engine(a.engine), limit=a.limit)
    if a.cmd == "serve":
        serve(g, a.port)
    else:
        print(json.dumps(g.identify(cv2.imread(a.args[0])), indent=1))
