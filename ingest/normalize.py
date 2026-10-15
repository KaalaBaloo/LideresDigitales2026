"""Limpieza de los valores tal como los sirve datos.madrid.es.

Problemas reales observados (oct-2026):
  * Texto UTF-8 almacenado como latin-1: 'Mart\xc3\xadn' -> 'Martín',
    con bytes no imprimibles como surrogates: 'HOSTELER\xc3\udc8dA' -> 'HOSTELERÍA'.
  * Coordenadas de aforos con puntos de miles: '40.417.386' -> 40.417386.
  * Coordenadas UTM con coma decimal: '439579,3291'.
  * Censo en UTM ETRS89 huso 30N (EPSG:25830).
"""
from __future__ import annotations

import math
import re
from functools import lru_cache

_MOJIBAKE_HINT = re.compile("[ÂÃ][\u0080-¿\udc80-\udcff]")


def fix_text(value: str | None) -> str | None:
    """Repara texto UTF-8 mal decodificado como latin-1. Idempotente."""
    if value is None:
        return None
    s = str(value)
    if not _MOJIBAKE_HINT.search(s):
        return s.strip()
    try:
        return s.encode("latin-1", "surrogateescape").decode("utf-8").strip()
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s.strip()


def parse_number(value, *, kind: str = "auto") -> float | None:
    """Convierte cadenas numéricas del portal a float.

    kind:
      'dotted_coord' -> '40.417.386' (puntos como separador de miles en coordenadas)
      'comma_decimal' -> '439579,3291'
      'auto'          -> decide por el formato
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return None if (isinstance(value, float) and math.isnan(value)) else float(value)
    s = str(value).strip()
    if not s:
        return None
    if kind == "dotted_coord" or (kind == "auto" and s.count(".") > 1):
        neg = s.startswith("-")
        digits = s.lstrip("-").replace(".", "")
        if not digits.isdigit():
            return None
        # grados de Madrid: 2 dígitos de parte entera para lat (40) y 1 para lon (-3)
        int_len = 2 if not neg else 1
        out = float(digits[:int_len] + "." + digits[int_len:])
        return -out if neg else out
    if kind == "comma_decimal" or (kind == "auto" and "," in s and "." not in s):
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def parse_int(value) -> int | None:
    if value is None:
        return None
    s = str(value).strip().replace(".", "")
    if not s:
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


@lru_cache(maxsize=1)
def _transformer():
    from pyproj import Transformer

    return Transformer.from_crs("EPSG:25830", "EPSG:4326", always_xy=True)


def utm_to_latlon(x: float | None, y: float | None) -> tuple[float | None, float | None]:
    """UTM ETRS89 30N -> (lat, lon) WGS84. Devuelve (None, None) si no hay coordenadas válidas."""
    if not x or not y or x < 100000 or y < 1000000:
        return None, None
    lon, lat = _transformer().transform(x, y)
    return lat, lon
