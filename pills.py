"""Closed-set pill ID: enroll examples of each pill type on the mat (max 5).

With >= MIN_SAMPLES arm-camera frames per type, classification uses length, width and colour
scaled by each type's own spread; one frame falls back to fixed scales.

This sorts what a pharmacist or caregiver already identified. It never claims to identify an
unknown pill: anything far from every enrolled type, or between two of them, is "reject".
"""
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

MAX_TYPES = 5
REJECT = "reject"
# Feature scales: one unit of distance = this much difference. Tune on site from T2 photos.
LAB_SCALE = 20.0       # 8-bit Lab units
LOG_AREA_SCALE = 0.25  # |ln(area ratio)|, ~28% size difference
ASPECT_SCALE = 0.3
MAX_DIST = 1.5         # beyond this from the nearest type -> reject
MIN_MARGIN = 0.3       # nearest must beat second-nearest by this much, else ambiguous -> reject
MIN_SAMPLES = 3
# Spread floors: edge noise is ~1 px, so a type measured too consistently would reject everything.
STD_FLOOR = {"lab": 3.0, "mm": 0.15, "px": 1.0}
Z_MAX = 3.5            # beyond this many spreads from the nearest type -> reject
Z_MARGIN = 1.0


@dataclass
class PillType:
    name: str
    lab: tuple
    area: float    # mm^2 when calibrated, px otherwise; enrol and classify in the same unit
    aspect: float
    n: int = 1
    size: tuple = ()      # (length, width) mean, mm when calibrated else px
    size_std: tuple = ()
    lab_std: tuple = ()
    unit: str = "px"
    camera: str = ""


def features(pill, area_scale: float = 1.0) -> tuple:
    """(lab, area, aspect, length, width) in the calibrated unit."""
    (x1, y1), (x2, y2) = pill.axis_px
    k = area_scale ** 0.5
    length = float(np.hypot(x2 - x1, y2 - y1)) * k
    return tuple(pill.lab), pill.area_px * area_scale, pill.aspect, length, length / max(pill.aspect, 1e-6)


def from_samples(name: str, feats: list, unit: str, camera: str = "") -> "PillType":
    labs = np.array([f[0] for f in feats], float)
    sizes = np.array([f[3:5] for f in feats], float)
    return PillType(name, tuple(labs.mean(0)), float(np.mean([f[1] for f in feats])),
                    float(np.mean([f[2] for f in feats])), len(feats), tuple(sizes.mean(0)),
                    tuple(sizes.std(0, ddof=1)) if len(feats) > 1 else (), tuple(labs.std(0, ddof=1)) if len(feats) > 1 else (), unit, camera)


def z_distance(t: PillType, lab, length: float, width: float) -> float:
    lab_sd = np.maximum(np.array(t.lab_std, float), STD_FLOOR["lab"])
    size_sd = np.maximum(np.array(t.size_std, float), STD_FLOOR[t.unit])
    z = np.concatenate([(np.subtract(lab, t.lab)) / lab_sd, (np.subtract((length, width), t.size)) / size_sd])
    return float(np.sqrt(np.mean(z ** 2)))


def distance(t: PillType, lab, area: float, aspect: float) -> float:
    d_lab = np.linalg.norm(np.subtract(lab, t.lab)) / LAB_SCALE
    d_area = abs(np.log(max(area, 1e-6) / max(t.area, 1e-6))) / LOG_AREA_SCALE
    d_aspect = abs(aspect - t.aspect) / ASPECT_SCALE
    return float(np.sqrt(d_lab ** 2 + d_area ** 2 + d_aspect ** 2))


class Registry:
    def __init__(self, types: list[PillType] | None = None):
        self.types: list[PillType] = []
        for t in types or []:
            self.enroll(t)

    def enroll(self, t: PillType):
        if any(x.name == t.name for x in self.types):
            raise ValueError(f"{t.name} already enrolled")
        if len(self.types) >= MAX_TYPES:
            raise ValueError(f"at most {MAX_TYPES} types; closed-set accuracy drops as the set grows")
        if t.name == REJECT:
            raise ValueError(f"'{REJECT}' is reserved")
        self.types.append(t)

    def enroll_pill(self, name: str, pill, area_scale: float = 1.0):
        """area_scale converts px^2 to mm^2 (calibration's local scale squared); 1.0 keeps px."""
        self.enroll(PillType(name, tuple(pill.lab), pill.area_px * area_scale, pill.aspect))

    def classify(self, lab, area: float, aspect: float, length: float | None = None,
                 width: float | None = None) -> tuple[str, float]:
        if not self.types:
            return REJECT, float("inf")
        use_z = length is not None and all(t.n >= MIN_SAMPLES and t.size for t in self.types)
        if use_z:
            d = sorted((z_distance(t, lab, length, width), t.name) for t in self.types)
            limit, margin = Z_MAX, Z_MARGIN
        else:
            d = sorted((distance(t, lab, area, aspect), t.name) for t in self.types)
            limit, margin = MAX_DIST, MIN_MARGIN
        best, name = d[0]
        if best > limit:
            return REJECT, best
        if len(d) > 1 and d[1][0] - best < margin:
            return REJECT, best
        return name, best

    def classify_pill(self, pill, area_scale: float = 1.0) -> tuple[str, float]:
        lab, area, aspect, length, width = features(pill, area_scale)
        return self.classify(lab, area, aspect, length, width)

    def save(self, path):
        Path(path).write_text(json.dumps([asdict(t) for t in self.types], indent=2))

    @classmethod
    def load(cls, path) -> "Registry":
        tup = ("lab", "size", "size_std", "lab_std")
        return cls([PillType(**{**d, **{k: tuple(d[k]) for k in tup if k in d}})
                    for d in json.loads(Path(path).read_text())])
