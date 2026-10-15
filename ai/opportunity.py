"""Detector de oportunidad perdida y "Efecto Sombra".

Oportunidad por franja horaria h y segmento s:
    expuestos[h,s]  = grupos que pasan por delante (incluye los que entran)
    potencial[h,s]  = expuestos[h,s] × conversión_referencia[s]
    pérdida_€[h,s]  = max(0, potencial[h,s] − grupos_que_entran[h,s]) × ticket_medio[s]

Efecto Sombra (calle lateral): la estación de la calle principal más cercana marca
el pico de gente; en la lateral medimos cuánto de ese flujo se desvía. Si en las
horas pico de la principal la lateral capta menos que su ratio habitual, ese
déficit es flujo "en sombra" que una acción en la esquina podría atraer.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, asdict
from statistics import median, quantiles

SEGMENTS = ("solo", "dos_adultos", "adulto_con_ninos", "familia_numerosa", "grupo_adultos_3_6", "grupo_grande")

FRANJAS = {"manana": (9, 13), "mediodia": (13, 16), "tarde": (16, 20), "noche": (20, 24)}


def franja_of(hour: int) -> str:
    for name, (a, b) in FRANJAS.items():
        if a <= hour < b:
            return name
    return "madrugada"


@dataclass
class Opportunity:
    hour: int
    segment: str
    exposed: int
    entering: int
    conversion_ref: float
    potential: float
    lost_groups: float
    avg_ticket: float
    loss_eur: float

    def to_dict(self) -> dict:
        d = asdict(self)
        for k in ("potential", "lost_groups", "loss_eur", "conversion_ref"):
            d[k] = round(d[k], 2)
        return d


def detect(observations: list[dict], conversion_ref: dict[str, float], avg_ticket: dict[str, float]) -> list[Opportunity]:
    """observations: filas {hour, segment, groups_passing, groups_entering} (agregados del sensor)."""
    acc: dict[tuple[int, str], list[int]] = defaultdict(lambda: [0, 0])
    for o in observations:
        k = (int(o["hour"]), o["segment"])
        acc[k][0] += int(o.get("groups_passing", 0)) + int(o.get("groups_entering", 0))
        acc[k][1] += int(o.get("groups_entering", 0))
    out = []
    for (h, s), (exposed, entering) in sorted(acc.items()):
        conv = float(conversion_ref.get(s, 0.0))
        pot = exposed * conv
        lost = max(0.0, pot - entering)
        ticket = float(avg_ticket.get(s, 0.0))
        out.append(Opportunity(h, s, exposed, entering, conv, pot, lost, ticket, lost * ticket))
    return out


def summarize(opps: list[Opportunity], top: int = 3) -> dict:
    by_hour: dict[int, float] = defaultdict(float)
    by_seg: dict[str, float] = defaultdict(float)
    for o in opps:
        by_hour[o.hour] += o.loss_eur
        by_seg[o.segment] += o.loss_eur
    worst = sorted(by_hour.items(), key=lambda kv: kv[1], reverse=True)[:top]
    return {
        "total_loss_eur": round(sum(by_hour.values()), 2),
        "worst_hours": [{"hour": h, "loss_eur": round(v, 2)} for h, v in worst if v > 0],
        "loss_by_segment": {s: round(v, 2) for s, v in sorted(by_seg.items(), key=lambda kv: -kv[1]) if v > 0},
    }


def dominant_segment(observations: list[dict], hour: int | None = None) -> tuple[str | None, float]:
    """Segmento con más grupos expuestos (opcionalmente en una hora) y su cuota."""
    cnt: dict[str, int] = defaultdict(int)
    for o in observations:
        if hour is None or int(o["hour"]) == hour:
            cnt[o["segment"]] += int(o.get("groups_passing", 0)) + int(o.get("groups_entering", 0))
    total = sum(cnt.values())
    if not total:
        return None, 0.0
    seg, n = max(cnt.items(), key=lambda kv: kv[1])
    return seg, n / total


MULTI_PERSON = tuple(s for s in SEGMENTS if s != "solo")


def odd_share(observations: list[dict], segments: tuple[str, ...] | None = MULTI_PERSON) -> tuple[float, int, int]:
    """Cuota de grupos de tamaño impar entre los grupos de 2+ personas (quien va solo no
    "se queda fuera" de un 2x1). Devuelve (cuota, impares, total)."""
    odd = total = 0
    for o in observations:
        if segments and o["segment"] not in segments:
            continue
        odd += int(o.get("odd_groups", 0))
        total += int(o.get("groups_passing", 0)) + int(o.get("groups_entering", 0))
    return (odd / total if total else 0.0), odd, total


def shadow_effect(main_curve: dict[int, float], side_flow: dict[int, float], peak_quantile: float = 0.7) -> dict:
    """Compara la curva de la calle principal con el flujo medido en la lateral.

    main_curve: hora -> peatones medios de la estación principal (curva patrón real).
    side_flow:  hora -> personas observadas en la lateral (sensor; unidades del sensor).
    El ratio de referencia es el p70 de side/main en las horas con datos: lo que la
    lateral consigue captar en sus buenas horas.
    """
    hours = sorted(h for h in side_flow if main_curve.get(h, 0) > 0)
    if len(hours) < 3:
        return {"available": False, "reason": "menos de 3 horas con datos en ambas calles"}
    ratios = [side_flow[h] / main_curve[h] for h in hours]
    ratio_ref = quantiles(ratios, n=10)[6] if len(ratios) >= 4 else max(ratios)
    mains = [main_curve[h] for h in hours]
    peak_thr = quantiles(mains, n=10)[int(peak_quantile * 10) - 1] if len(mains) >= 4 else max(mains)
    peaks = []
    for h in hours:
        if main_curve[h] < peak_thr:
            continue
        expected = main_curve[h] * ratio_ref
        deficit = max(0.0, expected - side_flow[h])
        peaks.append(
            {
                "hour": h,
                "main_pedestrians": round(main_curve[h], 1),
                "side_observed": round(side_flow[h], 1),
                "side_expected": round(expected, 1),
                "deficit": round(deficit, 1),
                "capture_ratio": round(side_flow[h] / main_curve[h], 4),
            }
        )
    peaks.sort(key=lambda p: -p["deficit"])
    return {
        "available": True,
        "ratio_ref": round(ratio_ref, 4),
        "ratio_median": round(median(ratios), 4),
        "peak_threshold": round(peak_thr, 1),
        "shadow_hours": [p for p in peaks if p["deficit"] > 0],
    }
