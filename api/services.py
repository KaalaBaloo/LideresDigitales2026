"""Lógica de aplicación sobre la BD: oportunidades, campañas, bandit y notificaciones."""
from __future__ import annotations

import json
import logging
import random
from collections import defaultdict
from datetime import date, datetime, timedelta

from fastapi import HTTPException

from ai import bandit, engine, opportunity, rules
from ai.memory import SlotStats, build_context, uplift
from ai.redactor import compose

from .core import DIST_SQL, bbox, db, settings

log = logging.getLogger(__name__)


# ------------------------------------------------------------------ lecturas
def get_shop(conn, shop_id: int) -> dict:
    s = conn.execute("select * from shops where id=%s", (shop_id,)).fetchone()
    if not s:
        raise HTTPException(404, "comercio no encontrado")
    return s


def observations(conn, shop_id: int, day: date, synthetic: bool | None = None) -> list[dict]:
    q = "select hour, segment, groups_passing, groups_entering, people_passing, people_entering, odd_groups from sensor_aggregates where shop_id=%s and day=%s"
    params: list = [shop_id, day]
    if synthetic is not None:
        q += " and synthetic=%s"
        params.append(synthetic)
    return conn.execute(q + " order by hour, segment", params).fetchall()


def station_curve(conn, station_id: str | None, dow: int) -> dict[int, dict]:
    if not station_id:
        return {}
    rows = conn.execute(
        "select hour, mean, p30, p70, period_from, period_to from madrid_ped_patterns where station_id=%s and dow=%s order by hour",
        (station_id, dow),
    ).fetchall()
    return {r["hour"]: r for r in rows}


def competitors_100m(conn, shop: dict) -> int | None:
    if not shop.get("census_id_local"):
        return None
    # Competencia directa = mismo epígrafe de actividad (p. ej. "RESTAURANTE"), no la división entera
    me = conn.execute("select epigrafe from madrid_shops where id_local=%s limit 1", (shop["census_id_local"],)).fetchone()
    if not me or not me["epigrafe"]:
        return None
    la0, la1, lo0, lo1 = bbox(shop["lat"], shop["lon"], 100)
    p = {"lat": shop["lat"], "lon": shop["lon"], "epi": me["epigrafe"], "me": shop["census_id_local"], "la0": la0, "la1": la1, "lo0": lo0, "lo1": lo1}
    r = conn.execute(
        f"select count(distinct id_local) n from madrid_shops where lat between %(la0)s and %(la1)s and lon between %(lo0)s and %(lo1)s "
        f"and epigrafe=%(epi)s and id_local<>%(me)s and {DIST_SQL} <= 100",
        p,
    ).fetchone()
    return r["n"]


def event_nearby(conn, lat: float, lon: float, when: datetime, radius_m: int = 600) -> dict | None:
    la0, la1, lo0, lo1 = bbox(lat, lon, radius_m)
    r = conn.execute(
        f"select event_id, title, venue, hour, starts_at, {DIST_SQL} as dist from madrid_events "
        "where lat between %(la0)s and %(la1)s and lon between %(lo0)s and %(lo1)s "
        "and starts_at::date <= %(d)s and coalesce(ends_at, starts_at)::date >= %(d)s "
        # solo eventos puntuales con hora (picos de salida), no exposiciones de meses
        "and hour is not null and coalesce(ends_at, starts_at) - starts_at < interval '2 days' "
        f"and {DIST_SQL} <= %(r)s order by dist limit 1",
        {"lat": lat, "lon": lon, "la0": la0, "la1": la1, "lo0": lo0, "lo1": lo1, "d": when.date(), "r": radius_m},
    ).fetchone()
    if not r:
        return None
    return {"title": r["title"], "venue": r["venue"], "hour": r["hour"], "distance_m": round(r["dist"])}


def weather_at(conn, lat: float, lon: float, start: datetime, end: datetime) -> dict:
    """T máx. y lluvia acumulada en la estación más cercana CON datos para cada magnitud."""
    out: dict = {}
    for mag, key, agg in ((83, "temp_max", "max"), (89, "rain_mm", "sum")):
        r = conn.execute(
            f"select h.station_code, {agg}(h.value) v from madrid_weather_hourly h join madrid_weather_stations s using (station_code) "
            f"where h.magnitude=%(m)s and h.ts>=%(a)s and h.ts<%(b)s group by h.station_code, s.lat, s.lon order by {DIST_SQL} limit 1",
            {"m": mag, "a": start, "b": end, "lat": lat, "lon": lon},
        ).fetchone()
        if r:
            out[key] = round(r["v"], 1)
            out[f"{key}_station"] = r["station_code"]
    return out


def load_arms(conn, shop_id: int) -> dict[tuple[str, str, str], bandit.Arm]:
    rows = conn.execute("select franja, segment, offer_type, alpha, beta from bandit_arms where shop_id=%s", (shop_id,)).fetchall()
    return {(r["franja"], r["segment"], r["offer_type"]): bandit.Arm(r["alpha"], r["beta"]) for r in rows}


# ------------------------------------------------------------------ oportunidades
def day_opportunities(conn, shop: dict, day: date) -> dict:
    obs = observations(conn, shop["id"], day)
    opps = opportunity.detect(obs, shop["conversion_ref"], shop["avg_ticket"])
    curve = station_curve(conn, shop["station_id"], day.weekday())
    by_hour: dict[int, dict] = defaultdict(lambda: {"segments": {}, "loss_eur": 0.0})
    for o in opps:
        h = by_hour[o.hour]
        h["segments"][o.segment] = o.to_dict()
        h["loss_eur"] = round(h["loss_eur"] + o.loss_eur, 2)
    out = {
        "shop_id": shop["id"],
        "date": day.isoformat(),
        "has_sensor_data": bool(obs),
        "hours": [{"hour": hh, **v} for hh, v in sorted(by_hour.items())],
        "summary": opportunity.summarize(opps),
        "station": {
            "station_id": shop["station_id"],
            "curve": [{"hour": hh, "mean": round(r["mean"], 1), "p30": round(r["p30"], 1), "p70": round(r["p70"], 1)} for hh, r in sorted(curve.items())],
            "note": "Curva patrón histórica (aforos permanentes, últimos 2 trimestres publicados), no tiempo real."
            + (f" Periodo {next(iter(curve.values()))['period_from']} – {next(iter(curve.values()))['period_to']}." if curve else ""),
        },
    }
    if not obs:
        last = conn.execute("select max(day) d from sensor_aggregates where shop_id=%s", (shop["id"],)).fetchone()
        out["latest_date_with_data"] = last["d"].isoformat() if last and last["d"] else None
    if shop["role"] == "lateral" and shop.get("main_station_id"):
        out["shadow_effect"] = shadow_for(conn, shop, day, obs)
    return out


def shadow_for(conn, shop: dict, day: date, obs: list[dict]) -> dict:
    main = {h: r["mean"] for h, r in station_curve(conn, shop["main_station_id"], day.weekday()).items()}
    side: dict[int, float] = defaultdict(float)
    for o in obs:
        side[int(o["hour"])] += o["people_passing"] + o["people_entering"]
    res = opportunity.shadow_effect(main, dict(side))
    res["main_station_id"] = shop["main_station_id"]
    return res


# ------------------------------------------------------------------ notificaciones
def refresh_notification(shop_id: int, day: date, hour: int) -> dict | None:
    """Recalcula la notificación de la franja (se llama tras cada lote de agregados)."""
    with db() as conn:
        shop = get_shop(conn, shop_id)
        obs = observations(conn, shop_id, day)
        if not obs:
            return None
        curve = {h: r["mean"] for h, r in station_curve(conn, shop["station_id"], day.weekday()).items()}
        franja = opportunity.franja_of(hour)
        last = conn.execute(
            "select offer_type from campaigns where shop_id=%s and context->>'franja'=%s order by starts_at desc limit 1",
            (shop_id, franja),
        ).fetchone()
        lessons = conn.execute(
            "select c.offer_type, r.uplift, r.diagnosis->0->>'text' as reason from campaign_results r join campaigns c on c.id=r.campaign_id "
            "where c.shop_id=%s and r.success=false and r.diagnosis is not null and jsonb_array_length(r.diagnosis)>0 "
            "order by c.starts_at desc limit 2",
            (shop_id,),
        ).fetchall()
        when = datetime.combine(day, datetime.min.time()) + timedelta(hours=hour)
        shadow = shadow_for(conn, shop, day, obs) if shop["role"] == "lateral" and shop.get("main_station_id") else None
        payload = engine.build_payload(
            shop,
            day,
            hour,
            obs,
            curve,
            load_arms(conn, shop_id),
            last_offer_in_franja=last["offer_type"] if last else None,
            past_lessons=[{"offer": l["offer_type"], "uplift": round(l["uplift"], 2) if l["uplift"] is not None else None, "reason": l["reason"]} for l in lessons],
            event_nearby=event_nearby(conn, shop["lat"], shop["lon"], when),
            weather=weather_at(conn, shop["lat"], shop["lon"], when, when + timedelta(hours=1)),
            competitors_100m=competitors_100m(conn, shop),
            shadow=shadow,
            rng=random.Random(f"{shop_id}-{day}-{hour}"),
        )
        text, source = compose(payload, settings().anthropic_api_key, settings().anthropic_model)
        row = conn.execute(
            "insert into notifications(shop_id, day, hour, payload, text, text_source, synthetic) values (%s,%s,%s,%s,%s,%s,%s) "
            "on conflict (shop_id, day, hour) do update set payload=excluded.payload, text=excluded.text, "
            "text_source=excluded.text_source, created_at=now(), status='new' returning *",
            (shop_id, day, hour, json.dumps(payload, ensure_ascii=False, default=str), text, source, True),
        ).fetchone()
        conn.commit()
        return row


# ------------------------------------------------------------------ campañas
def create_campaign(conn, shop: dict, offer_type: str, starts_at: datetime, ends_at: datetime, synthetic: bool = True) -> dict:
    catalog = bandit.load_catalog()
    if offer_type not in catalog:
        raise HTTPException(400, f"oferta desconocida; opciones: {sorted(catalog)}")
    if offer_type in (shop.get("vetoed_offers") or []):
        raise HTTPException(400, "oferta vetada por el comercio")
    obs = observations(conn, shop["id"], starts_at.date())
    hours = range(starts_at.hour, max(starts_at.hour + 1, ends_at.hour))
    window = [o for o in obs if int(o["hour"]) in hours] or obs
    seg, share = opportunity.dominant_segment(window)
    odd, _, _ = opportunity.odd_share(window)
    curve = {h: r["mean"] for h, r in station_curve(conn, shop["station_id"], starts_at.weekday()).items()}
    ctx = build_context(
        starts_at,
        ends_at,
        seg,
        share,
        odd,
        engine.peak_hour(curve),
        event_nearby(conn, shop["lat"], shop["lon"], starts_at),
        weather_at(conn, shop["lat"], shop["lon"], starts_at, ends_at),
        competitors_100m(conn, shop) or 0,
    )
    return conn.execute(
        "insert into campaigns(shop_id, offer_type, starts_at, ends_at, context, synthetic) values (%s,%s,%s,%s,%s,%s) returning *",
        (shop["id"], offer_type, starts_at, ends_at, json.dumps(ctx, ensure_ascii=False, default=str), synthetic),
    ).fetchone()


def _slot_stats(conn, shop_id: int, start: datetime, end: datetime) -> SlotStats:
    hours = list(range(start.hour, max(start.hour + 1, end.hour)))
    a = conn.execute(
        "select coalesce(sum(groups_passing+groups_entering),0) ex, coalesce(sum(groups_entering),0) en from sensor_aggregates "
        "where shop_id=%s and day=%s and hour = any(%s)",
        (shop_id, start.date(), hours),
    ).fetchone()
    t = conn.execute("select coalesce(sum(amount),0) rev, count(*) n from tickets where shop_id=%s and ts>=%s and ts<%s", (shop_id, start, end)).fetchone()
    return SlotStats(int(a["ex"]), int(a["en"]), float(t["rev"]), int(t["n"]))


def close_campaign(conn, campaign_id: int, override: dict | None = None) -> dict:
    c = conn.execute("select * from campaigns where id=%s", (campaign_id,)).fetchone()
    if not c:
        raise HTTPException(404, "campaña no encontrada")
    promo = _slot_stats(conn, c["shop_id"], c["starts_at"], c["ends_at"])
    if override:
        promo = SlotStats(
            override.get("exposed", promo.exposed),
            override.get("entries", promo.entering),
            override.get("revenue", promo.revenue),
            override.get("purchases", promo.purchases),
        )
    # Franjas comparables: mismo día de la semana y horas, 1–4 semanas antes, sin campaña activa
    baselines = []
    for w in range(1, 5):
        s, e = c["starts_at"] - timedelta(weeks=w), c["ends_at"] - timedelta(weeks=w)
        busy = conn.execute(
            "select 1 from campaigns where shop_id=%s and starts_at < %s and ends_at > %s limit 1", (c["shop_id"], e, s)
        ).fetchone()
        if not busy:
            st = _slot_stats(conn, c["shop_id"], s, e)
            if st.exposed:
                baselines.append(st)
    res = uplift(promo, baselines)
    catalog = bandit.load_catalog()
    diag = rules.diagnose({"offer": catalog.get(c["offer_type"]), "context": c["context"], "result": res})
    conn.execute(
        "insert into campaign_results(campaign_id, entries, revenue, avg_ticket, baseline, uplift, success, diagnosis, synthetic) "
        "values (%s,%s,%s,%s,%s,%s,%s,%s,%s) on conflict (campaign_id) do update set entries=excluded.entries, revenue=excluded.revenue, "
        "avg_ticket=excluded.avg_ticket, baseline=excluded.baseline, uplift=excluded.uplift, success=excluded.success, "
        "diagnosis=excluded.diagnosis, computed_at=now()",
        (
            campaign_id, promo.entering, promo.revenue, round(promo.avg_ticket, 2), json.dumps(res), res["uplift"], res["success"],
            json.dumps(diag, ensure_ascii=False), c["synthetic"],
        ),
    )
    if res["success"] is not None and c["status"] != "closed":
        ctx = c["context"]
        key = (c["shop_id"], ctx.get("franja"), ctx.get("dominant_segment") or "*", c["offer_type"])
        conn.execute(
            "insert into bandit_arms(shop_id, franja, segment, offer_type, alpha, beta) values (%s,%s,%s,%s,%s,%s) "
            "on conflict (shop_id, franja, segment, offer_type) do update set alpha=bandit_arms.alpha+excluded.alpha-1, beta=bandit_arms.beta+excluded.beta-1",
            (*key, 2 if res["success"] else 1, 1 if res["success"] else 2),
        )
    conn.execute("update campaigns set status='closed' where id=%s", (campaign_id,))
    return {"campaign_id": campaign_id, "result": res, "diagnosis": diag}
