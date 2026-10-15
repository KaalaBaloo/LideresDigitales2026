"""Fuentes en tiempo real de datos.madrid.es (consultadas al vuelo, con caché corta).

* Aparcamientos: dataset 50027-0-aparcamientosocupacionyservicios -> servicio SOAP
  InfoParking (operación GetListParking, parámetro tem:language). Verificado el
  15-oct-2026: 75 aparcamientos, 26 con plazas libres y hora de la lectura.
* Meteorología: dataset 300392-0-meteorologia-tiempo-real -> API JSON de
  ciudadesabiertas.madrid.es (actualización cada 20 min).
Las URLs se resuelven desde el propio CKAN (package_show) la primera vez.
"""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime

import httpx

log = logging.getLogger(__name__)
CKAN = "https://datos.madrid.es/api/3/action/package_show"
_cache: dict[str, tuple[float, object]] = {}


def _cached(key: str, ttl: float, fn):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    val = fn()
    _cache[key] = (time.time(), val)
    return val


def _resource_url(package_id: str, fmt: str, contains: str = "") -> str:
    def find():
        r = httpx.get(CKAN, params={"id": package_id}, timeout=60)
        r.raise_for_status()
        for res in r.json()["result"]["resources"]:
            if (res.get("format") or "").upper() == fmt and contains in (res.get("url") or ""):
                return res["url"]
        raise RuntimeError(f"{package_id}: sin recurso {fmt}")

    return _cached(f"url:{package_id}:{fmt}", 86400, find)


def _soap_endpoint() -> str:
    wsdl = _resource_url("50027-0-aparcamientosocupacionyservicios", "WSDL")
    return wsdl.split("?")[0]


ENVELOPE = (
    '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:tem="http://tempuri.org/">'
    "<soapenv:Body><tem:GetListParking><tem:language>ES</tem:language></tem:GetListParking></soapenv:Body></soapenv:Envelope>"
)


def _tag(block: str, name: str) -> str | None:
    m = re.search(rf"<ns2:{name}>([^<]*)</ns2:{name}>", block)
    return m.group(1).strip() if m else None


def parse_parkings(xml: str) -> list[dict]:
    out = []
    for blk in re.findall(r"<ns2:lstParking>(.*?)</ns2:lstParking>", xml, re.S):
        occ = re.search(r"<ns2:lstOccupation>(.*?)</ns2:lstOccupation>", blk, re.S)
        base = re.sub(r"<ns2:lstOccupation>.*?</ns2:lstOccupation>", "", blk, flags=re.S)
        free = moment = None
        if occ:
            free = _tag(occ.group(1), "free")
            moment = _tag(occ.group(1), "moment")
        try:
            lat, lon = float(_tag(base, "latitude")), float(_tag(base, "longitude"))
        except (TypeError, ValueError):
            continue
        out.append(
            {
                "id": _tag(base, "id"),
                "name": _tag(base, "name"),
                "address": _tag(base, "address"),
                "lat": lat,
                "lon": lon,
                "free_spaces": int(free) if free and free.lstrip("-").isdigit() else None,
                "measured_at": moment,
            }
        )
    return out


def parkings_live() -> list[dict]:
    def fetch():
        r = httpx.post(
            _soap_endpoint(),
            content=ENVELOPE.encode("utf-8"),
            headers={"Content-Type": "text/xml; charset=utf-8"},
            timeout=40,
        )
        r.raise_for_status()
        return parse_parkings(r.text)

    return _cached("parkings", 60, fetch)


def weather_now() -> list[dict]:
    """Últimas lecturas válidas de T (83) y precipitación (89) por estación."""

    def fetch():
        url = _resource_url("300392-0-meteorologia-tiempo-real", "JSON")
        r = httpx.get(url, timeout=60)
        r.raise_for_status()
        out = []
        for rec in r.json().get("records", []):
            mag = int(rec["MAGNITUD"])
            if mag not in (83, 89):
                continue
            last = None
            for h in range(24, 0, -1):
                if (rec.get(f"V{h:02d}") or "").upper() == "V":
                    last = (h, float(rec[f"H{h:02d}"]))
                    break
            if last:
                day = datetime(int(rec["ANO"]), int(rec["MES"]), int(rec["DIA"]))
                out.append({"station_code": rec["ESTACION"].lstrip("0"), "magnitude": mag, "hour": last[0] - 1, "value": last[1], "day": day.date().isoformat()})
        return out

    return _cached("weather", 600, fetch)
