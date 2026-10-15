"""Conectores de datos.madrid.es. Cada uno descubre su dataset por búsqueda CKAN,
verifica el recurso con una petición real y carga con procedencia.

IDs verificados el 15-oct-2026 (solo como referencia; el código los redescubre):
  aforos   300321-0-aforos-peatones-bicicletas   / "Aforos peatones. AAAA"
  censo    200085-0-censo-locales                 / "Actividades", "Terrazas"
  agenda   300107-0-agenda-actividades-eventos    / CSV con datastore
  meteo    300360-0-meteorologicos-estaciones, 300352-0-meteorologicos-horarios
  parking  300542-0-aparcamientos-municipales (plazas); ocupación en vivo por SOAP (api/madrid_live.py)
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from datetime import datetime, timedelta

import pandas as pd

from .ckan import CKAN, CKANError, Resource
from .normalize import fix_text, parse_int, parse_number, utm_to_latlon
from .patterns import build_patterns, filter_quarters, last_quarters
from .store import Store

log = logging.getLogger(__name__)


def _pick_by_year(resources: list[Resource], rx: str) -> list[tuple[int, Resource]]:
    out = []
    for r in resources:
        m = re.search(rx, r.description, re.I)
        if m and r.datastore_active:
            out.append((int(m.group(1)), r))
    return sorted(out, key=lambda t: t[0], reverse=True)


# =============================================================== Aforos peatonales
def ingest_aforos(ck: CKAN, store: Store, n_quarters: int = 2) -> dict:
    pkg = ck.find_package("aforos peatones bicicletas", r"aforos de peatones")
    yearly = _pick_by_year(ck.resources(pkg, r"aforos peatones"), r"peatones\.?\s*(\d{4})")
    if not yearly:
        raise CKANError("No hay recursos 'Aforos peatones. AAAA' con datastore")

    frames: list[pd.DataFrame] = []
    used: list[Resource] = []
    for _year, res in yearly[:2]:  # los 2 últimos trimestres pueden repartirse entre 2 recursos anuales
        ck.verify(res.id)
        recs = list(ck.iter_records(res.id))
        df = pd.DataFrame.from_records(recs)
        df["resource_id"] = res.id
        frames.append(df)
        used.append(res)
        df_ts = pd.to_datetime(df["fecha"], format="%d/%m/%Y %H:%M", errors="coerce")
        n_q = (df_ts.dt.year * 10 + (df_ts.dt.month - 1) // 3 + 1).nunique()
        if n_q >= n_quarters:
            break

    raw = pd.concat(frames, ignore_index=True)
    raw["ts"] = pd.to_datetime(raw["fecha"], format="%d/%m/%Y %H:%M", errors="coerce")
    raw["pedestrians"] = raw["peatones"].map(parse_int)
    raw["station_id"] = raw["identificador"].str.strip()
    raw = raw.dropna(subset=["ts", "pedestrians", "station_id"])

    quarters = last_quarters(raw, n_quarters)
    counts = filter_quarters(raw, quarters)
    period_from, period_to = counts["ts"].min().date(), counts["ts"].max().date()

    # Estaciones: valores más frecuentes no nulos por estación
    stations = []
    for sid, g in counts.groupby("station_id"):
        def mode(col, conv=lambda v: v):
            vals = [conv(v) for v in g[col].dropna()]
            vals = [v for v in vals if v not in (None, "")]
            return Counter(vals).most_common(1)[0][0] if vals else None

        stations.append(
            (
                sid,
                fix_text(mode("direccion")),
                fix_text(mode("distrito")),
                fix_text(mode("observaciones_direccion")),
                mode("latitude", lambda v: parse_number(v, kind="dotted_coord")),
                mode("longitude", lambda v: parse_number(v, kind="dotted_coord")),
                pkg["id"],
                g["resource_id"].iloc[0],
            )
        )

    pats = build_patterns(counts[["station_id", "ts", "pedestrians"]])
    res_ids = ",".join(r.id for r in used)

    with store.run("aforos", pkg["id"], res_ids) as info:
        store.upsert(
            "madrid_stations",
            ["station_id", "address", "district", "notes", "lat", "lon", "source_dataset", "source_resource"],
            stations,
            ["station_id"],
        )
        n = store.upsert(
            "madrid_ped_counts",
            ["station_id", "ts", "pedestrians", "source_dataset", "source_resource"],
            ((r.station_id, r.ts.to_pydatetime(), int(r.pedestrians), pkg["id"], r.resource_id) for r in counts.itertuples()),
            ["station_id", "ts"],
        )
        store.upsert(
            "madrid_ped_patterns",
            ["station_id", "dow", "hour", "mean", "p30", "p70", "n_obs", "period_from", "period_to", "source_dataset", "source_resource"],
            ((p.station_id, int(p.dow), int(p.hour), float(p.mean), float(p.p30), float(p.p70), int(p.n_obs), period_from, period_to, pkg["id"], res_ids) for p in pats.itertuples()),
            ["station_id", "dow", "hour"],
        )
        info["rows"] = n
        info["detail"] = {"quarters": quarters, "period": [str(period_from), str(period_to)], "stations": len(stations), "patterns": len(pats)}
    return info


# =============================================================== Censo de locales
def ingest_censo(ck: CKAN, store: Store) -> dict:
    pkg = ck.find_package("censo locales actividades terrazas", r"^censo de locales, sus actividades y terrazas de hosteler.{1,2}a y restauraci.{1,2}n$")
    act = [r for r in ck.resources(pkg, r"^actividades$") if r.datastore_active]
    ter = [r for r in ck.resources(pkg, r"^terrazas$") if r.datastore_active]
    if not act:
        raise CKANError("Censo: recurso 'Actividades' sin datastore")
    ra = act[0]
    ck.verify(ra.id)

    # Solo locales abiertos con puerta a calle (≈106k filas de 226k)
    q = (
        'SELECT "id_local","id_epigrafe","rotulo","desc_vial_acceso","num_acceso","desc_distrito_local",'
        '"desc_barrio_local","desc_seccion","desc_division","desc_epigrafe","coordenada_x_local","coordenada_y_local" '
        f'FROM "{ra.id}" WHERE "id_situacion_local"=\'1\' AND "id_tipo_acceso_local"=\'1\''
    )
    rows = []
    for r in ck.iter_sql(q):
        x = parse_number(r["coordenada_x_local"])
        y = parse_number(r["coordenada_y_local"])
        lat, lon = utm_to_latlon(x, y)
        if lat is None:
            continue
        rows.append(
            (
                r["id_local"], r["id_epigrafe"] or "", fix_text(r["rotulo"]), fix_text(r["desc_vial_acceso"]),
                (r["num_acceso"] or "").lstrip("0") or None, fix_text(r["desc_distrito_local"]), fix_text(r["desc_barrio_local"]),
                fix_text(r["desc_seccion"]), fix_text(r["desc_division"]), fix_text(r["desc_epigrafe"]),
                x, y, lat, lon, pkg["id"], ra.id,
            )
        )
    with store.run("censo", pkg["id"], ra.id) as info:
        info["rows"] = store.upsert(
            "madrid_shops",
            ["id_local", "id_epigrafe", "rotulo", "street", "street_number", "district", "barrio", "seccion", "division",
             "epigrafe", "utm_x", "utm_y", "lat", "lon", "source_dataset", "source_resource"],
            rows,
            ["id_local", "id_epigrafe"],
        )

    if ter:
        rt = ter[0]
        ck.verify(rt.id)
        trows = []
        for r in ck.iter_records(rt.id):
            lat, lon = utm_to_latlon(parse_number(r.get("coordenada_x_local")), parse_number(r.get("coordenada_y_local")))
            hours = {k: r.get(k) for k in ("hora_ini_LJ_es", "hora_fin_LJ_es", "hora_ini_VS_es", "hora_fin_VS_es")}
            trows.append(
                (
                    r["id_terraza"], r.get("id_local"), fix_text(r.get("rotulo")), fix_text(r.get("desc_ubicacion_terraza")),
                    lat, lon, parse_int(r.get("mesas_es")), parse_int(r.get("sillas_es")), _json(hours), pkg["id"], rt.id,
                )
            )
        with store.run("terrazas", pkg["id"], rt.id) as tinfo:
            tinfo["rows"] = store.upsert(
                "madrid_terraces",
                ["id_terraza", "id_local", "rotulo", "location", "lat", "lon", "tables_count", "chairs_count", "hours", "source_dataset", "source_resource"],
                trows,
                ["id_terraza"],
            )
    return info


def _json(d) -> str:
    import json

    return json.dumps(d, ensure_ascii=False)


# =============================================================== Agenda de eventos
def ingest_agenda(ck: CKAN, store: Store) -> dict:
    pkg = ck.find_package("agenda actividades eventos", r"^agenda de actividades y eventos$")
    res = [r for r in ck.resources(pkg, fmt="CSV") if r.datastore_active]
    if res:
        r0 = res[0]
        ck.verify(r0.id)
        recs = list(ck.iter_records(r0.id))
    else:  # alternativa sin datastore: descarga del CSV
        r0 = ck.resources(pkg, fmt="CSV")[0]
        recs = ck.download_csv(r0.url)

    def dt(v):
        try:
            return datetime.strptime(v[:19], "%Y-%m-%d %H:%M:%S") if v else None
        except ValueError:
            return None

    rows = []
    for r in recs:
        lat, lon = parse_number(r.get("LATITUD")), parse_number(r.get("LONGITUD"))
        rows.append(
            (
                r["ID-EVENTO"], fix_text(r.get("TITULO")), dt(r.get("FECHA")), dt(r.get("FECHA-FIN")), r.get("HORA"),
                fix_text(r.get("NOMBRE-INSTALACION")), fix_text(r.get("DISTRITO-INSTALACION")), r.get("GRATUITO") == "1",
                (r.get("TIPO") or "").rsplit("/", 1)[-1] or None, lat, lon, pkg["id"], r0.id,
            )
        )
    with store.run("agenda", pkg["id"], r0.id) as info:
        info["rows"] = store.upsert(
            "madrid_events",
            ["event_id", "title", "starts_at", "ends_at", "hour", "venue", "district", "free", "event_type", "lat", "lon", "source_dataset", "source_resource"],
            rows,
            ["event_id"],
        )
    return info


# =============================================================== Meteorología
MAGNITUDES = {83: "T", 89: "P", 86: "HR"}  # temperatura, precipitación, humedad relativa


def ingest_meteo(ck: CKAN, store: Store, days_back: int = 60) -> dict:
    est = ck.find_package("meteorologicos estaciones", r"estaciones de control")
    r_est = [r for r in ck.resources(est, fmt="CSV") if r.datastore_active][0]
    ck.verify(r_est.id)
    st_rows = []
    for r in ck.iter_records(r_est.id):
        mags = [k for k in ("T (83)", "P (89)", "HR (86)") if (r.get(k) or "").strip().upper() == "X"]
        st_rows.append((r["CODIGO_CORTO"], fix_text(r["ESTACION"]), parse_number(r["LATITUD"]), parse_number(r["LONGITUD"]), mags, est["id"], r_est.id))

    hor = ck.find_package("meteorologicos horarios", r"datos horarios")
    cands = [r for r in ck.resources(hor, r"desde\s+\d{4}", fmt="CSV") if r.datastore_active]
    if not cands:
        raise CKANError("Meteo horarios: no hay recurso 'Desde AAAA' con datastore")
    r_h = cands[0]
    ck.verify(r_h.id)
    since = datetime.now() - timedelta(days=days_back)
    where = " OR ".join(f'"MAGNITUD"=\'{m}\'' for m in MAGNITUDES)
    q = (
        f'SELECT * FROM "{r_h.id}" WHERE ({where}) AND ("ANO"::int*10000+"MES"::int*100+"DIA"::int) >= '
        f"{since.year * 10000 + since.month * 100 + since.day}"
    )
    rows = []
    for r in ck.iter_sql(q):
        day = datetime(int(r["ANO"]), int(r["MES"]), int(r["DIA"]))
        for h in range(1, 25):
            if (r.get(f"V{h:02d}") or "").upper() != "V":
                continue
            v = parse_number(r.get(f"H{h:02d}"))
            if v is None:
                continue
            rows.append((r["ESTACION"].lstrip("0"), day + timedelta(hours=h - 1), int(r["MAGNITUD"]), v, hor["id"], r_h.id))
    # Los horarios históricos se publican al cerrar cada mes: el mes en curso sale del feed
    # "tiempo real acumulado" (300754, últimos ~30 días, mismo formato H01..H24/V01..V24).
    try:
        acc = ck.find_package("meteorologia tiempo real acumulado", r"tiempo real acumulado")
        url = next(r.url for r in ck.resources(acc, fmt="JSON"))
        recs = ck.http.get(url).json().get("records", [])
        n0 = len(rows)
        for r in recs:
            if int(r["MAGNITUD"]) not in MAGNITUDES:
                continue
            day = datetime(int(r["ANO"]), int(r["MES"]), int(r["DIA"]))
            for h in range(1, 25):
                if (r.get(f"V{h:02d}") or "").upper() != "V":
                    continue
                v = parse_number(r.get(f"H{h:02d}"))
                if v is not None:
                    rows.append((r["ESTACION"].lstrip("0"), day + timedelta(hours=h - 1), int(r["MAGNITUD"]), v, acc["id"], url))
        log.info("meteo: %s lecturas del feed acumulado", len(rows) - n0)
    except (CKANError, StopIteration, ValueError) as e:
        log.warning("meteo: feed acumulado no disponible (%s)", e)

    with store.run("meteo", hor["id"], r_h.id) as info:
        store.upsert(
            "madrid_weather_stations",
            ["station_code", "name", "lat", "lon", "magnitudes", "source_dataset", "source_resource"],
            st_rows,
            ["station_code"],
        )
        info["rows"] = store.upsert(
            "madrid_weather_hourly",
            ["station_code", "ts", "magnitude", "value", "source_dataset", "source_resource"],
            rows,
            ["station_code", "ts", "magnitude"],
        )
    return info


# =============================================================== Aparcamientos (plazas)
def ingest_parking_capacity(ck: CKAN, store: Store) -> dict:
    pkg = ck.find_package("aparcamientos municipales plazas", r"aparcamientos municipales\. n.{1,2}mero de plazas")
    r0 = [r for r in ck.resources(pkg, fmt="CSV") if r.datastore_active][0]
    ck.verify(r0.id)
    rows = [
        (
            r["CODIGO APARC"], fix_text(r["NOMBRE APARC"]), fix_text(r.get("TIPO")), parse_int(r.get("PZS ROTACION")),
            parse_int(r.get("PZS TOTALES")), parse_number(r.get("LATITUD")), parse_number(r.get("LONGITUD")), pkg["id"], r0.id,
        )
        for r in ck.iter_records(r0.id)
    ]
    with store.run("parking_capacity", pkg["id"], r0.id) as info:
        info["rows"] = store.upsert(
            "madrid_parking_capacity",
            ["code", "name", "parking_type", "spaces_rotation", "spaces_total", "lat", "lon", "source_dataset", "source_resource"],
            rows,
            ["code"],
        )
    return info


CONNECTORS = {
    "aforos": ingest_aforos,
    "censo": ingest_censo,
    "agenda": ingest_agenda,
    "meteo": ingest_meteo,
    "parking": ingest_parking_capacity,
}
