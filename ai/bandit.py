"""Recomendador: Thompson sampling Beta(α, β) por (franja, segmento_dominante, tipo_oferta).

Antes de muestrear se filtran las ofertas no elegibles:
  * vetadas por el comerciante;
  * descuento por encima del máximo del perfil;
  * no dirigidas al segmento dominante;
  * `requiere_grupo_par` cuando los grupos impares dominan (el 2x1 deja a alguien fuera).
Cada exclusión se devuelve con su motivo para que la app lo explique.
"""
from __future__ import annotations

import pathlib
import random
from dataclasses import dataclass

import yaml

OFFERS_FILE = pathlib.Path(__file__).with_name("offers.yaml")
ODD_DOMINANT = 0.40  # mismo umbral que la regla OFERTA_PARES_GRUPOS_IMPARES


def load_catalog(path: pathlib.Path | str = OFFERS_FILE) -> dict[str, dict]:
    with open(path, encoding="utf-8") as f:
        return {o["id"]: o for o in yaml.safe_load(f)["offers"]}


@dataclass
class Arm:
    alpha: float = 1.0
    beta: float = 1.0

    def update(self, success: bool) -> "Arm":
        return Arm(self.alpha + (1 if success else 0), self.beta + (0 if success else 1))

    @property
    def mean(self) -> float:
        return self.alpha / (self.alpha + self.beta)


def eligibility(offer: dict, segment: str | None, odd_share: float, vetoed: set[str], max_discount: float | None,
                allow_over_max: set[str] | None = None) -> str | None:
    """None si es elegible; si no, el motivo."""
    if offer["id"] in vetoed:
        return "vetada por el comercio"
    if max_discount is not None and offer.get("descuento_pct", 0) > max_discount and offer["id"] not in (allow_over_max or set()):
        return f"supera tu descuento máximo ({max_discount:g} %)"
    if segment and segment not in offer.get("segmentos", []):
        return "no encaja con el público dominante"
    if offer.get("requiere_grupo_par") and odd_share >= ODD_DOMINANT:
        return f"exige grupos pares y el {round(odd_share * 100)} % de los grupos son impares"
    return None


def recommend(
    arms: dict[tuple[str, str, str], Arm],
    franja: str,
    segment: str | None,
    odd_share: float,
    vetoed: set[str] | None = None,
    max_discount: float | None = None,
    catalog: dict[str, dict] | None = None,
    rng: random.Random | None = None,
    allow_over_max: set[str] | None = None,
) -> dict:
    catalog = catalog or load_catalog()
    rng = rng or random.Random()
    vetoed = vetoed or set()
    excluded, samples = [], []
    for oid, offer in catalog.items():
        why = eligibility(offer, segment, odd_share, vetoed, max_discount, allow_over_max)
        if why:
            excluded.append({"offer": oid, "reason": why})
            continue
        arm = arms.get((franja, segment or "*", oid), Arm())
        samples.append((rng.betavariate(arm.alpha, arm.beta), oid, arm))
    if not samples:
        return {"offer": None, "excluded": excluded, "reason": "ninguna oferta elegible"}
    samples.sort(reverse=True)
    best, oid, arm = samples[0]
    o = catalog[oid]
    return {
        "offer": oid,
        "title": o["titulo"],
        "discount_pct": o.get("descuento_pct"),
        "franja": franja,
        "segment": segment,
        "sampled": round(best, 4),
        "alpha": arm.alpha,
        "beta": arm.beta,
        "trials": int(arm.alpha + arm.beta - 2),
        "posterior_mean": round(arm.mean, 4),
        "candidates": [{"offer": i, "sampled": round(s, 4), "posterior_mean": round(a.mean, 4)} for s, i, a in samples],
        "excluded": excluded,
    }
