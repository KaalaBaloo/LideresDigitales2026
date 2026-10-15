"""Orquestación pura (sin BD): agregados de hoy + memoria -> JSON de notificación.

El JSON resultante es lo ÚNICO que ve el redactor (Claude o plantilla).
"""
from __future__ import annotations

import random
from datetime import date

from . import bandit, opportunity, rules
from .redactor import SEGMENT_LABELS


def peak_hour(curve: dict[int, float], open_from: int = 10, open_to: int = 21) -> int | None:
    hours = {h: v for h, v in curve.items() if open_from <= h < open_to}
    return max(hours, key=hours.get) if hours else None


def build_payload(
    shop: dict,
    day: date,
    hour: int,
    observations: list[dict],
    station_curve: dict[int, float],
    arms: dict[tuple[str, str, str], bandit.Arm],
    last_offer_in_franja: str | None = None,
    past_lessons: list[dict] | None = None,
    event_nearby: dict | None = None,
    weather: dict | None = None,
    competitors_100m: int | None = None,
    shadow: dict | None = None,
    rng: random.Random | None = None,
) -> dict:
    catalog = bandit.load_catalog()
    opps = opportunity.detect(observations, shop.get("conversion_ref", {}), shop.get("avg_ticket", {}))
    at_hour = [o for o in opps if o.hour == hour] or opps
    top = max(at_hour, key=lambda o: o.loss_eur) if at_hour else None
    seg, share = opportunity.dominant_segment(observations, hour)
    seg = seg or (top.segment if top else None)
    odd, n_odd, n_groups = opportunity.odd_share([o for o in observations if int(o["hour"]) == hour] or observations)
    franja = opportunity.franja_of(hour)
    profile = shop.get("profile") or {}
    pk = peak_hour(station_curve)

    context = {
        "hour": hour,
        "start_hour": hour,
        "peak_hour": pk,
        "dominant_segment": seg,
        "dominant_share": round(share, 2),
        "odd_share": round(odd, 2),
        "odd_groups": n_odd,
        "groups": n_groups,
        "weather": weather or {},
        "competitors_100m": competitors_100m,
        "event_nearby": event_nearby,
    }
    # Diagnóstico prospectivo: ¿qué fallaría si repites la última oferta de esta franja?
    offer_ctx = catalog.get(last_offer_in_franja) if last_offer_in_franja else None
    diag = rules.diagnose({"offer": offer_ctx, "context": context})
    if not offer_ctx:  # sin oferta previa: la regla de paridad no aplica
        diag = [d for d in diag if d["code"] != "OFERTA_PARES_GRUPOS_IMPARES"]
    diag.sort(key=lambda d: -d["confidence"])

    rec = bandit.recommend(
        arms,
        franja,
        seg,
        odd,
        vetoed=set(shop.get("vetoed_offers") or []),
        max_discount=profile.get("max_discount_pct"),
        catalog=catalog,
        rng=rng,
        allow_over_max=set(profile.get("allowed_over_max") or []),
    )
    payload = {
        "shop": {"name": shop.get("name"), "street": shop.get("street")},
        "slot": {"day": day.isoformat(), "hour": hour, "franja": franja},
        "opportunity": None
        if not top
        else {
            "hour": top.hour,
            "segment": top.segment,
            "segment_label": SEGMENT_LABELS.get(top.segment, top.segment),
            "groups_seen": top.exposed,
            "groups_entering": top.entering,
            "lost_groups": round(top.lost_groups, 1),
            "loss_eur": round(top.loss_eur, 2),
        },
        "context": {
            "dominant_segment": seg,
            "dominant_segment_label": SEGMENT_LABELS.get(seg, seg),
            "odd_groups_pct": round(odd * 100),
            "street_peak_hour": pk,
            "last_offer_in_franja": last_offer_in_franja,
        },
        "diagnosis": [{"code": d["code"], "text": d["text"], "confidence": d["confidence"]} for d in diag[:2]],
        "recommendation": {
            "offer": rec.get("offer"),
            "title": rec.get("title"),
            "discount_pct": rec.get("discount_pct"),
            "previous_trials": rec.get("trials"),
            "success_rate": rec.get("posterior_mean"),
            "excluded": [e for e in rec.get("excluded", []) if "vetada" in e["reason"] or "pares" in e["reason"]],
        },
        "lessons": (past_lessons or [])[:2],
        "synthetic_data": True,
    }
    if shadow and shadow.get("available") and shadow.get("shadow_hours"):
        s0 = shadow["shadow_hours"][0]
        payload["shadow_effect"] = {"hour": s0["hour"], "main_street_pedestrians": s0["main_pedestrians"], "capture_ratio": s0["capture_ratio"]}
    return payload
