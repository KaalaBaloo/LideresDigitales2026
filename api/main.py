"""API de negocio de Hora Valle + Efecto Sombra (FastAPI, OpenAPI en /docs).

No recibe ni guarda imágenes (salvo /sensor/debug-frame, que la reenvía al edge y
la descarta): solo agregados del sensor, datos reales de Madrid y datos sintéticos
del comercio.
"""
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .core import settings
from .routers import ai, campaigns, madrid, sensor, shops

logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="Hora Valle + Efecto Sombra",
    version="1.0",
    description="Reto #31 Cátedras Telefónica · Madrid. Datos de ciudad reales (datos.madrid.es); "
    "datos de comercio e imágenes de cámara sintéticos (synthetic=true).",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings().cors_origins.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)
for r in (madrid.router, sensor.router, shops.router, campaigns.router, ai.router):
    app.include_router(r)


@app.get("/health", tags=["sistema"])
def health():
    s = settings()
    return {"ok": True, "db": bool(s.database_url), "claude": bool(s.anthropic_api_key), "model": s.anthropic_model, "edge": s.edge_url}
