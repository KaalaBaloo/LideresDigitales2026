"""Diagnóstico por reglas: por qué una promo funcionó o no (o por qué no lanzarla).

Orden, umbrales y textos viven en ai/rules.yaml. Cada regla devuelve
{code, evidence (numérica), confidence, text}. Las reglas que necesitan el
resultado de una campaña se omiten cuando solo hay contexto prospectivo.

Entrada `ctx`:
  offer:   entrada del catálogo (con requiere_grupo_par)
  context: odd_share, start_hour, peak_hour, weather{temp_max, rain_mm}, competitors_100m, ...
  result:  salida de memory.uplift (opcional)
"""
from __future__ import annotations

import pathlib
from typing import Callable

import yaml

RULES_FILE = pathlib.Path(__file__).with_name("rules.yaml")


def load_rules(path: pathlib.Path | str = RULES_FILE) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [r for r in yaml.safe_load(f)["rules"] if r.get("enabled", True)]


def _clip(x: float) -> float:
    return round(max(0.05, min(0.95, x)), 2)


def _failed(ctx) -> bool | None:
    res = ctx.get("result") or {}
    return None if res.get("success") is None else not res["success"]


def r_pares(ctx, p, base):
    offer, c = ctx.get("offer") or {}, ctx.get("context") or {}
    share = c.get("odd_share")
    if not offer.get("requiere_grupo_par") or share is None or share < p["min_odd_share"]:
        return None
    failed = _failed(ctx)
    conf = base + (share - p["min_odd_share"]) + (0.15 if failed else 0 if failed is None else -0.25)
    return {"odd_share": round(share, 3), "odd_pct": round(share * 100), "offer": offer.get("id")}, conf


def r_tras_pico(ctx, p, base):
    c = ctx.get("context") or {}
    s, pk = c.get("start_hour"), c.get("peak_hour")
    if s is None or pk is None or s - pk < p["min_delay_h"]:
        return None
    delay = s - pk
    return {"start_hour": s, "peak_hour": pk, "delay_h": delay}, base + 0.1 * delay + (0.1 if _failed(ctx) else 0)


def r_ticket(ctx, p, base):
    res = ctx.get("result") or {}
    e, t = res.get("entries_change"), res.get("ticket_change")
    if e is None or t is None or e < p["min_entries_change"] or t > p["max_ticket_change"]:
        return None
    return (
        {"entries_change": e, "ticket_change": t, "entries_pct": round(e * 100), "ticket_drop_pct": round(-t * 100)},
        base + min(0.3, -t),
    )


def r_clima(ctx, p, base):
    w = (ctx.get("context") or {}).get("weather") or {}
    temp, rain = w.get("temp_max"), w.get("rain_mm")
    parts, ev = [], {}
    if temp is not None and temp >= p["hot_c"]:
        parts.append(f"{temp:.0f} ºC")
        ev["temp_max"] = temp
    if rain is not None and rain >= p["rain_mm"]:
        parts.append(f"{rain:.1f} l/m² de lluvia")
        ev["rain_mm"] = rain
    if not parts:
        return None
    ev["weather_desc"] = " y ".join(parts)
    return ev, base + (0.15 if _failed(ctx) else 0)


def r_competencia(ctx, p, base):
    n = (ctx.get("context") or {}).get("competitors_100m")
    if n is None or n < p["min_competitors"]:
        return None
    return {"competitors_100m": n}, base + min(0.3, (n - p["min_competitors"]) * 0.03)


RULE_FUNCS: dict[str, Callable] = {
    "OFERTA_PARES_GRUPOS_IMPARES": r_pares,
    "PROMO_TRAS_PICO": r_tras_pico,
    "TICKET_BAJO_CANIBALIZA": r_ticket,
    "CAUSA_EXTERNA_CLIMA": r_clima,
    "COMPETENCIA_ALTA": r_competencia,
}


def diagnose(ctx: dict, rules: list[dict] | None = None) -> list[dict]:
    out = []
    for r in rules or load_rules():
        fn = RULE_FUNCS.get(r["code"])
        if not fn:
            continue
        hit = fn(ctx, r.get("params", {}), r.get("confidence_base", 0.5))
        if not hit:
            continue
        evidence, conf = hit
        text = " ".join(r["text"].format(**evidence).split())
        out.append({"code": r["code"], "evidence": {k: v for k, v in evidence.items() if k != "weather_desc"}, "confidence": _clip(conf), "text": text})
    return out
