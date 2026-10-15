"""Crea 2 comercios REALES del Censo con 4 semanas de datos SINTÉTICOS (synthetic=true):

  A) un comercio de la calle Fuencarral junto a la estación PERM_PEA02_PM01 (calle principal);
  B) un comercio de una calle lateral de Gran Vía, a 60–250 m de PERM_PEA08_PM01 (Efecto Sombra).

Genera agregados del sensor, tickets y 20 campañas pasadas (incluido un 2x1 que
fracasa con grupos de 3) coherentes con la curva patrón REAL de peatones de su
estación; después cierra cada campaña con el mismo código que usa la API (uplift
frente a franjas comparables, reglas y bandit).

    DATABASE_URL=... python -m scripts.seed_synthetic_shop [--reset] [--seed 31]
Requiere haber ejecutado antes la ingesta (python -m ingest.run).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import psycopg
from psycopg.rows import dict_row

from ai.bandit import load_catalog
from ai.opportunity import SEGMENTS
from api import services
from api.core import TZ

STATION_A = "PERM_PEA02_PM01"  # Calle Fuencarral 22
STATION_B = "PERM_PEA08_PM01"  # Gran Vía 34
DAYS = 28
CAPTURE = 0.05            # fracción de los peatones de la estación que pasa por el campo de la cámara
AVG_GROUP = 1.9           # personas por grupo (media) para pasar de peatones a grupos
PURCHASE_RATE = 0.45      # fracción de grupos que entran y compran
CATALOG = load_catalog()

# Mezcla de público por franja (pesos) y prob. de grupo impar en grupos de 3–6
MIX = {
    "manana":   {"solo": 45, "dos_adultos": 25, "adulto_con_ninos": 10, "familia_numerosa": 2, "grupo_adultos_3_6": 15, "grupo_grande": 3},
    "mediodia": {"solo": 35, "dos_adultos": 30, "adulto_con_ninos": 10, "familia_numerosa": 2, "grupo_adultos_3_6": 20, "grupo_grande": 3},
    "tarde":    {"solo": 22, "dos_adultos": 26, "adulto_con_ninos": 10, "familia_numerosa": 2, "grupo_adultos_3_6": 35, "grupo_grande": 5},
    "noche":    {"solo": 20, "dos_adultos": 35, "adulto_con_ninos": 3, "familia_numerosa": 1, "grupo_adultos_3_6": 33, "grupo_grande": 8},
}
WEEKEND_FAMILY_BOOST = 2.2
BASE_CONV = {"solo": 0.06, "dos_adultos": 0.05, "adulto_con_ninos": 0.07, "familia_numerosa": 0.04, "grupo_adultos_3_6": 0.035, "grupo_grande": 0.02}
TICKET = {"solo": 17.0, "dos_adultos": 22.0, "adulto_con_ninos": 26.0, "familia_numerosa": 31.0, "grupo_adultos_3_6": 29.0, "grupo_grande": 44.0}


def franja(h: int) -> str:
    return "manana" if h < 13 else "mediodia" if h < 16 else "tarde" if h < 20 else "noche"


@dataclass
class Plan:
    shop: str          # "A" | "B"
    offer: str
    weekday: int       # 0 = lunes
    weeks_ago: int     # 1 = la semana pasada
    start_h: int
    dur_h: int
    conv_mult: float   # efecto real (oculto) de la oferta sobre la conversión
    ticket_mult: float = 1.0
    odd_p: float | None = None          # prob. de grupo impar forzada en la ventana
    dominant: str | None = None         # segmento que se refuerza en la ventana


PLANS = [
    # --- A · Fuencarral (librería/comercio) ---
    Plan("A", "2x1", 1, 2, 17, 3, 1.00, odd_p=0.68, dominant="grupo_adultos_3_6"),  # fracasa: grupos de 3
    Plan("A", "grupo_20", 1, 1, 17, 3, 1.45, odd_p=0.62, dominant="grupo_adultos_3_6"),
    Plan("A", "vecinos_10", 5, 2, 10, 3, 1.04),
    Plan("A", "2x1", 5, 1, 12, 3, 1.60, odd_p=0.15, dominant="dos_adultos"),        # funciona con parejas
    Plan("A", "pack_familia", 5, 1, 16, 3, 1.80, dominant="adulto_con_ninos"),
    Plan("A", "grupo_20", 3, 2, 18, 2, 1.35, odd_p=0.55),
    Plan("A", "vecinos_10", 3, 1, 20, 1, 1.01),                                        # después del pico
    Plan("A", "solo_15", 0, 2, 11, 3, 1.35, dominant="solo"),
    Plan("A", "pack_familia", 2, 2, 17, 3, 1.07),                                       # flojo
    Plan("A", "grupo_20", 4, 1, 17, 3, 1.40, odd_p=0.6),
    Plan("A", "2x1", 2, 1, 18, 2, 0.97, odd_p=0.58, dominant="grupo_adultos_3_6"),      # vuelve a fracasar
    Plan("A", "pack_familia", 0, 1, 16, 3, 1.70, dominant="adulto_con_ninos"),
    # --- B · lateral de Gran Vía (hostelería/comercio) ---
    Plan("B", "uno_de_cinco_gratis", 4, 2, 20, 2, 1.80, ticket_mult=0.68, dominant="grupo_grande"),  # canibaliza
    Plan("B", "2x1", 5, 2, 18, 3, 1.00, odd_p=0.64, dominant="grupo_adultos_3_6"),
    Plan("B", "grupo_20", 5, 1, 13, 3, 1.40, odd_p=0.6),
    Plan("B", "vecinos_10", 1, 2, 11, 3, 1.03),
    Plan("B", "solo_15", 2, 1, 10, 2, 1.40, dominant="solo"),
    Plan("B", "pack_familia", 6, 1, 12, 3, 1.80, dominant="adulto_con_ninos"),
    Plan("B", "grupo_20", 3, 1, 20, 2, 1.15, odd_p=0.55),
    Plan("B", "2x1", 0, 1, 19, 2, 1.50, odd_p=0.2, dominant="dos_adultos"),
]

PROFILE_A = {
    "business_type": None,  # se toma del epígrafe real del Censo
    "opening_hours": "Lun.–sáb. 10:00–21:00 · Dom. cerrado",
    "open_from": 10, "open_to": 21, "closed_weekdays": [6],
    "preferred_slot": "martes 17:00–20:00",
    "target_audience": "Grupos de 3–6 adultos y parejas",
    "also_interested": "Vecinos del barrio",
    "max_discount_pct": 20,
    "allowed_over_max": ["2x1"],  # "El 2x1 se reserva para una selección"
    "stack_promotions": False,
    "eligible_products": "Selección de temporada",
    "channel": "Escaparate",
    "max_duration_h": 3,
    "notes": "El 2x1 se reserva para una selección de productos.",
}
PROFILE_B = {
    "business_type": None,
    "opening_hours": "Todos los días 9:00–23:00",
    "open_from": 9, "open_to": 23, "closed_weekdays": [],
    "preferred_slot": "viernes y sábado 18:00–22:00",
    "target_audience": "Grupos de adultos que salen de Gran Vía",
    "also_interested": "Familias en fin de semana",
    "max_discount_pct": 25,
    "stack_promotions": False,
    "eligible_products": "Bebidas y meriendas",
    "channel": "Pizarra en la esquina con Gran Vía",
    "max_duration_h": 3,
}


# ------------------------------------------------------------------ selección de comercios reales
def pick_shop(conn, station_id: str, *, same_street: str | None, exclude_street: str | None, min_m: int, max_m: int, prefer: list[str], skip: tuple[str, ...] = ()) -> dict:
    st = conn.execute("select lat, lon from madrid_stations where station_id=%s", (station_id,)).fetchone()
    if not st:
        raise SystemExit(f"Falta la estación {station_id}: ejecuta antes `python -m ingest.run aforos censo`")
    rows = conn.execute(
        f"select id_local, rotulo, street, street_number, epigrafe, division, lat, lon, {services.DIST_SQL} as dist "
        "from madrid_shops where lat between %(lat)s-0.004 and %(lat)s+0.004 and lon between %(lon)s-0.005 and %(lon)s+0.005 "
        f"and {services.DIST_SQL} between %(a)s and %(b)s and rotulo is not null and rotulo <> ''",
        {"lat": st["lat"], "lon": st["lon"], "a": min_m, "b": max_m},
    ).fetchall()
    if same_street:
        rows = [r for r in rows if (r["street"] or "").upper() == same_street]
    if exclude_street:
        rows = [r for r in rows if exclude_street not in (r["street"] or "").upper()]
    rows = [r for r in rows if not any(k in (r["epigrafe"] or "").upper() or k in (r["rotulo"] or "").upper() for k in skip)]
    rows = [r for r in rows if not (r["rotulo"] or "").upper().startswith(("COMERCIO ", "LOCAL ")) and "NO INFORMADO" not in (r["rotulo"] or "").upper()]  # rótulos genéricos
    if not rows:
        raise SystemExit(f"No hay locales candidatos cerca de {station_id}")
    for kw in prefer:
        hits = [r for r in rows if kw in (r["epigrafe"] or "").upper()]
        if hits:
            return min(hits, key=lambda r: r["dist"])
    return min(rows, key=lambda r: r["dist"])


# ------------------------------------------------------------------ generación
def group_size(seg: str, odd_p: float, rng: random.Random) -> tuple[int, int]:
    """(adultos, niños)."""
    if seg == "solo":
        return 1, 0
    if seg == "dos_adultos":
        return 2, 0
    if seg == "adulto_con_ninos":
        a = rng.choice([1, 2, 2])
        return a, rng.choice([1, 1, 2])
    if seg == "familia_numerosa":
        return 2, rng.choice([3, 3, 4])
    if seg == "grupo_adultos_3_6":
        return (rng.choice([3, 5]) if rng.random() < odd_p else rng.choice([4, 4, 6])), 0
    return rng.randint(7, 10), 0


def poisson(lam: float, rng: random.Random) -> int:
    if lam > 30:
        return max(0, int(round(rng.gauss(lam, math.sqrt(lam)))))
    l, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= l:
            return k
        k += 1


def campaign_window(p: Plan, today: date) -> tuple[datetime, datetime]:
    d = today - timedelta(days=1)
    while d.weekday() != p.weekday:
        d -= timedelta(days=1)
    d -= timedelta(weeks=p.weeks_ago - 1)
    start = datetime.combine(d, datetime.min.time()) + timedelta(hours=p.start_h)
    return start, start + timedelta(hours=p.dur_h)


def simulate(conn, shop: dict, profile: dict, curve: dict, plans: list[tuple[Plan, datetime, datetime]], today: date, rng: random.Random, lateral: bool):
    aggs: dict[tuple, dict] = defaultdict(lambda: defaultdict(int))
    tickets = []
    for back in range(DAYS, 0, -1):
        day = today - timedelta(days=back)
        if day.weekday() in profile["closed_weekdays"]:
            continue
        for h in range(profile["open_from"], profile["open_to"]):
            ped = curve.get((day.weekday(), h))
            if not ped:
                continue
            capture = CAPTURE
            if lateral:  # Efecto Sombra: la lateral capta ~4 %, pero en el pico de la principal solo ~2 %
                peak = sorted(curve[(day.weekday(), x)] for x in range(profile["open_from"], profile["open_to"]) if (day.weekday(), x) in curve)
                capture = 0.02 if ped >= peak[int(len(peak) * 0.7)] else 0.04
            ped *= rng.uniform(0.85, 1.15)
            n_groups = poisson(ped * capture / AVG_GROUP, rng)
            when = datetime.combine(day, datetime.min.time()) + timedelta(hours=h)
            active = next((p for p, s, e in plans if s <= when < e), None)
            mix = dict(MIX[franja(h)])
            if day.weekday() >= 5:
                mix["adulto_con_ninos"] *= WEEKEND_FAMILY_BOOST
                mix["familia_numerosa"] *= WEEKEND_FAMILY_BOOST
            if active and active.dominant:
                mix[active.dominant] *= 2.5
            odd_p = active.odd_p if active and active.odd_p is not None else 0.5
            segs, weights = zip(*mix.items())
            by_seg: dict[str, list[int]] = defaultdict(list)
            for _ in range(n_groups):
                seg = rng.choices(segs, weights)[0]
                a, c = group_size(seg, odd_p, rng)
                by_seg[seg].append(a + c)
            for seg, sizes in by_seg.items():
                rng.shuffle(sizes)
                # El efecto real de la promo solo alcanza a su público: segmentos objetivo de la
                # oferta y, si exige grupo par, solo a los grupos pares (en un trío alguien queda fuera).
                def reached(size: int) -> bool:
                    if not active:
                        return False
                    o = CATALOG[active.offer]
                    return seg in o["segmentos"] and not (o.get("requiere_grupo_par") and size % 2)

                k = aggs[(day, h, seg)]
                for subset, mult in (([z for z in sizes if reached(z)], active.conv_mult if active else 1.0), ([z for z in sizes if not reached(z)], 1.0)):
                    # Entradas ≈ grupos × conversión con ruido acotado (±8 %)
                    expected = len(subset) * BASE_CONV[seg] * mult * rng.uniform(0.92, 1.08)
                    n_in = min(len(subset), int(expected) + (1 if rng.random() < expected % 1 else 0))
                    for i, size in enumerate(subset):
                        enters = i < n_in
                        k["groups_entering" if enters else "groups_passing"] += 1
                        k["people_entering" if enters else "people_passing"] += size
                        k["odd_groups"] += size % 2
                        k["frames"] += 1
                        if enters and rng.random() < PURCHASE_RATE:
                            amt = TICKET[seg] * rng.lognormvariate(0, 0.25) * (active.ticket_mult if active else 1.0)
                            ts = when + timedelta(minutes=rng.randint(0, 59))
                            tickets.append((shop["id"], ts, round(amt, 2), size, seg, True))
    return aggs, tickets


def calibrate(aggs: dict, plans_windows: list[tuple[datetime, datetime]]) -> tuple[dict, dict]:
    """conversion_ref = conversión agregada sin promo × 1,25: la meta realista de una buena
    franja. ticket_medio = ticket base por segmento (sin promo)."""
    tot = defaultdict(lambda: [0, 0])
    for (day, h, seg), k in aggs.items():
        when = datetime.combine(day, datetime.min.time()) + timedelta(hours=h)
        if any(s <= when < e for s, e in plans_windows):
            continue
        tot[seg][0] += k["groups_passing"] + k["groups_entering"]
        tot[seg][1] += k["groups_entering"]
    conv = {seg: round(1.25 * (tot[seg][1] / tot[seg][0] if tot[seg][0] >= 50 else BASE_CONV[seg]), 4) for seg in SEGMENTS}
    return conv, dict(TICKET)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true", help="borra comercios sintéticos previos")
    ap.add_argument("--seed", type=int, default=31)
    a = ap.parse_args()
    rng = random.Random(a.seed)
    today = datetime.now(TZ).date()

    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row, prepare_threshold=None) as conn:
        if a.reset:
            conn.execute("delete from shops where synthetic")
        curves = {}
        for sid in (STATION_A, STATION_B):
            rows = conn.execute("select dow, hour, mean from madrid_ped_patterns where station_id=%s", (sid,)).fetchall()
            if not rows:
                raise SystemExit(f"Sin curva patrón para {sid}: ejecuta la ingesta de aforos")
            curves[sid] = {(r["dow"], r["hour"]): r["mean"] for r in rows}

        loc_a = pick_shop(conn, STATION_A, same_street="FUENCARRAL", exclude_street=None, min_m=0, max_m=300, prefer=["LIBR", "PAPEL", "COMERCIO AL POR MENOR"], skip=("HOTEL", "HOSTAL"))
        loc_b = pick_shop(conn, STATION_B, same_street=None, exclude_street="GRAN V", min_m=60, max_m=250, prefer=["CAFETER", "BAR RESTAURANTE", "BAR", "HELADER"], skip=("HOTEL", "HOSTAL", "APARTAMENTO", "PENSI"))

        created = {}
        for key, loc, station, main_station, role, profile, vetoed in (
            ("A", loc_a, STATION_A, None, "main", PROFILE_A, ["uno_de_cinco_gratis"]),
            ("B", loc_b, STATION_B, STATION_B, "lateral", PROFILE_B, []),
        ):
            shop = conn.execute(
                "insert into shops(census_id_local, name, street, lat, lon, station_id, main_station_id, role, capacity, vetoed_offers, profile, synthetic) "
                "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,true) returning *",
                (
                    loc["id_local"], loc["rotulo"].title(), f"{(loc['street'] or '').title()} {loc['street_number'] or ''}".strip(),
                    loc["lat"], loc["lon"], station, main_station, role, 40 if key == "A" else 60, vetoed,
                    json.dumps({**profile, "business_type": (loc["epigrafe"] or "").capitalize(), "census_epigrafe": loc["epigrafe"], "distance_to_station_m": round(loc["dist"])}, ensure_ascii=False),
                ),
            ).fetchone()
            plans = [(p, *campaign_window(p, today)) for p in PLANS if p.shop == key]
            aggs, tickets = simulate(conn, shop, profile, curves[station], plans, today, rng, lateral=(role == "lateral"))
            conv, ticket = calibrate(aggs, [(s, e) for _, s, e in plans])
            conn.execute("update shops set conversion_ref=%s, avg_ticket=%s, audience=%s where id=%s",
                         (json.dumps(conv), json.dumps(ticket), json.dumps(_audience(aggs)), shop["id"]))
            with conn.cursor() as cur:
                with cur.copy("copy sensor_aggregates(shop_id, day, hour, segment, groups_passing, groups_entering, people_passing, people_entering, odd_groups, frames, synthetic) from stdin") as cp:
                    for (day, h, seg), k in aggs.items():
                        cp.write_row((shop["id"], day, h, seg, k["groups_passing"], k["groups_entering"], k["people_passing"], k["people_entering"], k["odd_groups"], k["frames"], True))
                with cur.copy("copy tickets(shop_id, ts, amount, group_size, segment, redeemed, synthetic) from stdin") as cp:
                    for t in tickets:
                        cp.write_row((t[0], t[1], t[2], t[3], t[4], False, t[5]))
            shop = services.get_shop(conn, shop["id"])
            results = []
            for p, s, e in sorted(plans, key=lambda t: t[1]):
                c = services.create_campaign(conn, shop, p.offer, s, e, synthetic=True)
                conn.execute("update tickets set campaign_id=%s, redeemed=true where shop_id=%s and ts>=%s and ts<%s", (c["id"], shop["id"], s, e))
                results.append(services.close_campaign(conn, c["id"]))
            conn.commit()
            created[key] = shop
            ok = sum(1 for r in results if r["result"]["success"])
            print(f"[{key}] {shop['name']} ({shop['street']}) id={shop['id']} · {len(aggs)} filas de sensor · {len(tickets)} tickets · "
                  f"{len(results)} campañas ({ok} con éxito)")
            for r, (p, s, _) in zip(results, sorted(plans, key=lambda t: t[1])):
                codes = ",".join(d["code"] for d in r["diagnosis"]) or "-"
                print(f"    {s:%a %d/%m %H}h {p.offer:<20} uplift={r['result']['uplift']}  {codes}")
        print("Comercio de Fuencarral -> shop_id", created["A"]["id"])


def _audience(aggs: dict) -> dict:
    tot = defaultdict(int)
    for (_, _, seg), k in aggs.items():
        tot[seg] += k["groups_passing"] + k["groups_entering"]
    s = sum(tot.values()) or 1
    return {seg: round(v / s, 3) for seg, v in sorted(tot.items(), key=lambda kv: -kv[1])}


if __name__ == "__main__":
    main()
