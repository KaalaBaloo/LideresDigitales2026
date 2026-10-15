from __future__ import annotations

from datetime import date, datetime, timedelta

from fastapi import APIRouter, HTTPException, Query

from .. import madrid_live
from ..core import DIST_SQL, bbox, db, haversine_m

router = APIRouter(prefix="/madrid", tags=["madrid (datos reales)"])


@router.get("/stations", summary="Estaciones permanentes de aforo peatonal")
def stations():
    with db() as conn:
        return conn.execute(
            "select s.*, (select min(period_from) from madrid_ped_patterns p where p.station_id=s.station_id) period_from, "
            "(select max(period_to) from madrid_ped_patterns p where p.station_id=s.station_id) period_to "
            "from madrid_stations s order by station_id"
        ).fetchall()


@router.get("/patterns/{station_id}", summary="Curva patrón: día de la semana × hora (media, p30, p70)")
def patterns(station_id: str, dow: int | None = Query(None, ge=0, le=6, description="0=lunes")):
    with db() as conn:
        q = "select dow, hour, mean, p30, p70, n_obs, period_from, period_to, source_dataset, source_resource from madrid_ped_patterns where station_id=%s"
        params: list = [station_id]
        if dow is not None:
            q += " and dow=%s"
            params.append(dow)
        rows = conn.execute(q + " order by dow, hour", params).fetchall()
    if not rows:
        raise HTTPException(404, "estación sin curva patrón")
    return {"station_id": station_id, "points": rows}


@router.get("/shops/nearby", summary="Locales del Censo (abiertos, puerta a calle) cerca de un punto")
def shops_nearby(lat: float, lon: float, radius: int = Query(100, ge=10, le=1000), division: str | None = None, limit: int = Query(200, le=1000)):
    la0, la1, lo0, lo1 = bbox(lat, lon, radius)
    p = {"lat": lat, "lon": lon, "la0": la0, "la1": la1, "lo0": lo0, "lo1": lo1, "r": radius, "div": division, "lim": limit}
    with db() as conn:
        rows = conn.execute(
            f"select id_local, rotulo, street, street_number, epigrafe, division, seccion, lat, lon, round({DIST_SQL}::numeric,1) distance_m, "
            "source_dataset, source_resource from madrid_shops where lat between %(la0)s and %(la1)s and lon between %(lo0)s and %(lo1)s "
            f"and {DIST_SQL} <= %(r)s and (%(div)s::text is null or division=%(div)s) order by distance_m limit %(lim)s",
            p,
        ).fetchall()
    return {"count": len(rows), "items": rows}


@router.get("/parkings/live", summary="Ocupación de aparcamientos en tiempo real (SOAP municipal)")
def parkings_live(lat: float | None = None, lon: float | None = None, radius: int = Query(1500, le=10000)):
    try:
        items = madrid_live.parkings_live()
    except Exception as e:
        raise HTTPException(502, f"servicio de aparcamientos no disponible: {e}") from e
    with db() as conn:
        caps = conn.execute("select name, spaces_rotation, spaces_total, lat, lon from madrid_parking_capacity where lat is not null").fetchall()
    out = []
    for it in items:
        if lat is not None and lon is not None:
            it["distance_m"] = round(haversine_m(lat, lon, it["lat"], it["lon"]))
            if it["distance_m"] > radius:
                continue
        # plazas del inventario (300542) emparejadas por cercanía (< 120 m)
        best = min(caps, key=lambda c: haversine_m(it["lat"], it["lon"], c["lat"], c["lon"]), default=None)
        if best and haversine_m(it["lat"], it["lon"], best["lat"], best["lon"]) < 120:
            cap = best["spaces_rotation"] or best["spaces_total"]
            it["capacity"] = cap
            if cap and it["free_spaces"] is not None:
                it["occupancy_pct"] = round(100 * (1 - it["free_spaces"] / cap), 1)
        out.append(it)
    out.sort(key=lambda x: x.get("distance_m", 0))
    return {
        "source_dataset": "50027-0-aparcamientosocupacionyservicios",
        "capacity_dataset": "300542-0-aparcamientos-municipales",
        "with_live_data": sum(1 for x in out if x["free_spaces"] is not None),
        "items": out,
    }


@router.get("/events", summary="Agenda de actividades y eventos")
def events(
    from_: date = Query(None, alias="from"),
    to: date | None = None,
    lat: float | None = None,
    lon: float | None = None,
    radius: int = Query(1000, le=10000),
    limit: int = Query(200, le=1000),
):
    from_ = from_ or date.today()
    to = to or from_ + timedelta(days=7)
    with db() as conn:
        if lat is not None and lon is not None:
            la0, la1, lo0, lo1 = bbox(lat, lon, radius)
            rows = conn.execute(
                f"select *, round({DIST_SQL}::numeric) distance_m from madrid_events where lat between %(la0)s and %(la1)s and lon between %(lo0)s and %(lo1)s "
                f"and {DIST_SQL} <= %(r)s and starts_at::date <= %(to)s and coalesce(ends_at, starts_at)::date >= %(fr)s order by starts_at limit %(lim)s",
                {"lat": lat, "lon": lon, "la0": la0, "la1": la1, "lo0": lo0, "lo1": lo1, "r": radius, "fr": from_, "to": to, "lim": limit},
            ).fetchall()
        else:
            rows = conn.execute(
                "select * from madrid_events where starts_at::date <= %s and coalesce(ends_at, starts_at)::date >= %s order by starts_at limit %s",
                (to, from_, limit),
            ).fetchall()
    return {"from": from_, "to": to, "count": len(rows), "items": rows}


@router.get("/weather/now", summary="Meteorología en tiempo real (T y precipitación)")
def weather_now():
    try:
        return {"source_dataset": "300392-0-meteorologia-tiempo-real", "fetched_at": datetime.now().isoformat(timespec="seconds"), "items": madrid_live.weather_now()}
    except Exception as e:
        raise HTTPException(502, f"servicio meteorológico no disponible: {e}") from e


@router.get("/provenance", summary="Últimas cargas de datos de datos.madrid.es")
def provenance():
    with db() as conn:
        return conn.execute(
            "select distinct on (connector) connector, source_dataset, source_resource, started_at, finished_at, rows_loaded, status, detail "
            "from ingest_runs order by connector, started_at desc"
        ).fetchall()
