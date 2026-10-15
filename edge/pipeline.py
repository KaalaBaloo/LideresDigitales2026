"""Pipeline del dispositivo: imagen -> detecciones -> grupos -> agregados.

La imagen solo vive en memoria durante `process_frame`; no se escribe en disco
ni se reenvía a ningún sitio salvo al detector. Lo único que sale son agregados
(segmento, nº de grupos que pasan/entran, personas, paridad del tamaño).
"""
from __future__ import annotations

import io
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from .age_band import AgeBandEstimator, DisabledAgeBand
from .detector import Detection, Detector
from .grouping import SEGMENTS, Group, group_people


@dataclass
class DoorLine:
    """Línea virtual de la puerta en coordenadas normalizadas [0,1].

    inside: 'below' o 'above' — lado de la línea que corresponde a la entrada.
    Un grupo "entra" si su punto de apoyo medio cae en el lado interior y dentro
    del tramo horizontal de la línea.
    """

    p1: tuple[float, float] = (0.0, 0.62)
    p2: tuple[float, float] = (1.0, 0.62)
    inside: str = "below"

    @classmethod
    def from_dict(cls, d: dict | None) -> "DoorLine":
        if not d:
            return cls()
        return cls(tuple(d["p1"]), tuple(d["p2"]), d.get("inside", "below"))

    def is_inside(self, x: float, y: float) -> bool:
        (x1, y1), (x2, y2) = self.p1, self.p2
        lo, hi = min(x1, x2), max(x1, x2)
        if not (lo <= x <= hi):
            return False
        # y de la línea en x (en imagen, y crece hacia abajo)
        y_line = y1 if x2 == x1 else y1 + (y2 - y1) * (x - x1) / (x2 - x1)
        return y > y_line if self.inside == "below" else y < y_line


@dataclass
class FrameResult:
    width: int
    height: int
    detections: list[Detection]
    groups: list[Group]
    aggregates: list[dict] = field(default_factory=list)

    def debug_view(self) -> dict:
        """Cajas normalizadas y grupos, para pintar en la app (que difumina a las personas)."""
        def nbox(d: Detection) -> list[float]:
            return [round(d.x1 / self.width, 4), round(d.y1 / self.height, 4), round(d.x2 / self.width, 4), round(d.y2 / self.height, 4)]

        return {
            "width": self.width,
            "height": self.height,
            "people": len(self.detections),
            "groups": [
                {
                    "id": i,
                    "segment": g.segment,
                    "size": g.size,
                    "adults": g.n_adults,
                    "children": g.n_children,
                    "entering": g.entering,
                    "boxes": [{"box": nbox(d), "child": c, "score": round(d.score, 3)} for d, c in zip(g.members, g.children)],
                }
                for i, g in enumerate(self.groups)
            ],
            "aggregates": self.aggregates,
        }


def aggregate(groups: list[Group]) -> list[dict]:
    acc: dict[str, Counter] = defaultdict(Counter)
    for g in groups:
        c = acc[g.segment]
        if g.entering:
            c["groups_entering"] += 1
            c["people_entering"] += g.size
        else:
            c["groups_passing"] += 1
            c["people_passing"] += g.size
        c["odd_groups"] += g.size % 2
    return [{"segment": s, **{k: int(v) for k, v in acc[s].items()}} for s in SEGMENTS if s in acc]


def image_size(image: bytes) -> tuple[int, int]:
    from PIL import Image

    with Image.open(io.BytesIO(image)) as im:
        return im.size


def process_frame(
    image: bytes,
    detector: Detector,
    door: DoorLine,
    eps_factor: float = 0.6,
    child_ratio: float = 0.65,
    age_band: AgeBandEstimator | None = None,
) -> FrameResult:
    width, height = image_size(image)
    dets = detector.detect(image)
    groups = group_people(dets, eps_factor=eps_factor, child_ratio=child_ratio)
    for g in groups:
        fx, fy = g.foot
        g.entering = door.is_inside(fx / width, fy / height)
    (age_band or DisabledAgeBand()).annotate(groups)  # desactivado por defecto
    res = FrameResult(width, height, dets, groups)
    res.aggregates = aggregate(groups)
    return res
