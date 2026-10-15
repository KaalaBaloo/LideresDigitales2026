"""Cliente mínimo de la API CKAN de datos.madrid.es.

Nunca se codifican URLs de descarga: los datasets se descubren con package_search,
los recursos se eligen por su descripción en package_show y los datos se leen por
id de recurso (estable) con datastore_search / datastore_search_sql. Si un recurso
no tiene datastore se descarga su CSV detectando separador y codificación.
"""
from __future__ import annotations

import csv
import io
import logging
import re
import time
from dataclasses import dataclass
from typing import Iterator

import httpx

log = logging.getLogger(__name__)

BASE = "https://datos.madrid.es/api/3/action/"
PAGE = 32000  # máximo de filas por página que sirve el portal (verificado)


@dataclass
class Resource:
    id: str
    package_id: str
    description: str
    format: str
    datastore_active: bool
    url: str


class CKANError(RuntimeError):
    pass


class CKAN:
    def __init__(self, base: str = BASE, timeout: float = 180.0):
        self.base = base
        self.http = httpx.Client(timeout=timeout, headers={"User-Agent": "hora-valle-ingest/1.0"}, follow_redirects=True)

    # ------------------------------------------------------------------ bajo nivel
    def action(self, name: str, **params) -> dict:
        last: Exception | None = None
        for attempt in range(4):
            try:
                r = self.http.get(self.base + name, params=params)
                r.raise_for_status()
                body = r.json()
                if not body.get("success"):
                    raise CKANError(f"{name} -> {body.get('error')}")
                return body["result"]
            except (httpx.HTTPError, ValueError) as e:  # reintento con espera exponencial
                last = e
                time.sleep(2**attempt)
        raise CKANError(f"{name} falló tras reintentos: {last}")

    # ------------------------------------------------------------------ descubrimiento
    def search(self, q: str, rows: int = 10) -> list[dict]:
        return self.action("package_search", q=q, rows=rows)["results"]

    def package(self, package_id: str) -> dict:
        return self.action("package_show", id=package_id)

    def find_package(self, q: str, must_match: str) -> dict:
        """Primer paquete de la búsqueda cuyo título casa con la regex `must_match`."""
        rx = re.compile(must_match, re.I)
        for p in self.search(q, rows=20):
            if rx.search(p.get("title", "")):
                return self.package(p["id"])
        raise CKANError(f"Sin dataset para q={q!r} / {must_match!r}")

    @staticmethod
    def resources(pkg: dict, description: str | None = None, fmt: str | None = None) -> list[Resource]:
        rx = re.compile(description, re.I) if description else None
        out = []
        for r in pkg.get("resources", []):
            desc = r.get("description") or r.get("name") or ""
            if rx and not rx.search(desc):
                continue
            if fmt and (r.get("format") or "").upper() != fmt.upper():
                continue
            out.append(Resource(r["id"], pkg["id"], desc, r.get("format") or "", bool(r.get("datastore_active")), r.get("url") or ""))
        return out

    # ------------------------------------------------------------------ lectura
    def verify(self, resource_id: str) -> list[dict]:
        """Petición real de 1 fila: devuelve los campos. Falla si el recurso no responde."""
        res = self.action("datastore_search", resource_id=resource_id, limit=1)
        return res["fields"]

    def iter_records(self, resource_id: str, **filters) -> Iterator[dict]:
        offset = 0
        while True:
            res = self.action("datastore_search", resource_id=resource_id, limit=PAGE, offset=offset, **filters)
            recs = res["records"]
            yield from recs
            offset += len(recs)
            if len(recs) < PAGE or offset >= res.get("total", 0):
                break

    def sql(self, query: str) -> list[dict]:
        return self.action("datastore_search_sql", sql=query)["records"]

    def iter_sql(self, select_from_where: str, order_by: str = '"_id"') -> Iterator[dict]:
        offset = 0
        while True:
            recs = self.sql(f"{select_from_where} ORDER BY {order_by} LIMIT {PAGE} OFFSET {offset}")
            yield from recs
            offset += len(recs)
            if len(recs) < PAGE:
                break

    def download_csv(self, url: str) -> list[dict]:
        """Para recursos sin datastore: detecta codificación (utf-8 / latin-1) y separador (; , |)."""
        raw = self.http.get(url).content
        for enc in ("utf-8-sig", "latin-1"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        sample = text[:5000]
        delim = csv.Sniffer().sniff(sample, delimiters=";,|").delimiter
        return list(csv.DictReader(io.StringIO(text), delimiter=delim))
