"""Configuración, pool de Postgres y utilidades comunes de la API."""
from __future__ import annotations

import math
from contextlib import contextmanager
from datetime import datetime
from functools import lru_cache
from zoneinfo import ZoneInfo

from fastapi import Header, HTTPException
from pydantic_settings import BaseSettings

TZ = ZoneInfo("Europe/Madrid")


class Settings(BaseSettings):
    database_url: str = ""
    supabase_url: str = ""
    supabase_key: str = ""
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-5-5"
    cors_origins: str = "http://localhost:5173"
    edge_url: str = "http://localhost:8001"
    sensor_api_key: str = ""


@lru_cache
def settings() -> Settings:
    return Settings()


@lru_cache
def pool():
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool

    # prepare_threshold=None: compatible con el pooler de Supabase en modo transacción
    return ConnectionPool(
        settings().database_url,
        min_size=1,
        max_size=5,
        kwargs={"row_factory": dict_row, "prepare_threshold": None},
        open=True,
    )


@contextmanager
def db():
    if not settings().database_url:
        raise HTTPException(503, "DATABASE_URL no configurada")
    with pool().connection() as conn:
        yield conn


def now_local() -> datetime:
    return datetime.now(TZ).replace(tzinfo=None)


def require_sensor_key(x_sensor_key: str | None = Header(None)) -> None:
    key = settings().sensor_api_key
    if key and x_sensor_key != key:
        raise HTTPException(401, "X-Sensor-Key inválida")


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def bbox(lat: float, lon: float, radius_m: float) -> tuple[float, float, float, float]:
    dlat = radius_m / 111_320.0
    dlon = radius_m / (111_320.0 * math.cos(math.radians(lat)))
    return lat - dlat, lat + dlat, lon - dlon, lon + dlon


# SQL de distancia (metros) reutilizable con parámetros %(lat)s / %(lon)s
DIST_SQL = (
    "(2*6371000*asin(sqrt(power(sin(radians(lat-%(lat)s)/2),2)+cos(radians(%(lat)s))*cos(radians(lat))"
    "*power(sin(radians(lon-%(lon)s)/2),2))))"
)
