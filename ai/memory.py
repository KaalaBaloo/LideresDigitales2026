"""Memoria de campañas: contexto completo y éxito medido como UPLIFT.

Éxito = la conversión (grupos que entran / grupos expuestos) durante la promo
supera en ≥ SUCCESS_UPLIFT a la de franjas COMPARABLES sin promo (misma tienda,
mismo día de la semana y mismas horas de semanas anteriores). No se usan ventas
brutas: así una tarde con más gente no parece un éxito de la oferta.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from statistics import mean

from .opportunity import franja_of

SUCCESS_UPLIFT = 0.10  # Objetivo de la app: ≥10 % más entradas a igual flujo


@dataclass
class SlotStats:
    exposed: int       # grupos que pasan por delante (incl. los que entran)
    entering: int
    revenue: float = 0.0
    purchases: int = 0

    @property
    def conversion(self) -> float:
        return self.entering / self.exposed if self.exposed else 0.0

    @property
    def avg_ticket(self) -> float:
        return self.revenue / self.purchases if self.purchases else 0.0


def build_context(
    starts_at: datetime,
    ends_at: datetime,
    dominant_segment: str | None,
    dominant_share: float,
    odd_share: float,
    peak_hour: int | None,
    event_nearby: dict | None,
    weather: dict | None,
    competitors_100m: int,
) -> dict:
    """Contexto que se guarda con cada campaña (campaigns.context)."""
    return {
        "franja": franja_of(starts_at.hour),
        "weekday": starts_at.weekday(),
        "start_hour": starts_at.hour,
        "end_hour": ends_at.hour,
        "dominant_segment": dominant_segment,
        "dominant_share": round(dominant_share, 3),
        "odd_share": round(odd_share, 3),
        "group_parity": "impar" if odd_share >= 0.5 else "par",
        "peak_hour": peak_hour,
        "event_nearby": event_nearby,
        "weather": weather or {},
        "competitors_100m": competitors_100m,
    }


def uplift(promo: SlotStats, baselines: list[SlotStats], threshold: float = SUCCESS_UPLIFT) -> dict:
    valid = [b for b in baselines if b.exposed > 0]
    if not valid or promo.exposed == 0:
        return {"uplift": None, "success": None, "reason": "sin franjas comparables sin promo"}
    base_conv = mean(b.conversion for b in valid)
    base_entries = mean(b.entering for b in valid)
    base_ticket = mean(b.avg_ticket for b in valid if b.purchases) if any(b.purchases for b in valid) else 0.0
    up = (promo.conversion / base_conv - 1) if base_conv else None
    ticket_change = (promo.avg_ticket / base_ticket - 1) if base_ticket and promo.purchases else None
    return {
        "uplift": None if up is None else round(up, 4),
        "success": None if up is None else up >= threshold,
        "promo_conversion": round(promo.conversion, 4),
        "baseline_conversion": round(base_conv, 4),
        "promo_entries": promo.entering,
        "baseline_entries": round(base_entries, 1),
        "entries_change": round(promo.entering / base_entries - 1, 4) if base_entries else None,
        "ticket_change": None if ticket_change is None else round(ticket_change, 4),
        "promo_avg_ticket": round(promo.avg_ticket, 2),
        "baseline_avg_ticket": round(base_ticket, 2),
        "n_baselines": len(valid),
        "threshold": threshold,
    }
