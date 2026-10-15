"""Servicio "edge": simula el dispositivo de la tienda (Render web service aparte).

Es el ÚNICO componente que recibe imágenes y el único con HF_TOKEN. Procesa cada
fotograma en memoria, lo descarta y envía SOLO agregados a la API de negocio.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from pydantic_settings import BaseSettings

from .detector import Detector, HFDetrDetector
from .evaluate import evaluate
from .pipeline import DoorLine, process_frame

log = logging.getLogger("edge")
TZ = ZoneInfo("Europe/Madrid")
MAX_BYTES = 8 * 1024 * 1024


class EdgeSettings(BaseSettings):
    hf_token: str = ""
    hf_provider: str = "hf-inference"
    detector_model: str = "facebook/detr-resnet-50"
    detector_threshold: float = 0.7
    eps_factor: float = 0.6
    child_ratio: float = 0.65
    api_url: str = "http://localhost:8000"
    sensor_api_key: str = ""


settings = EdgeSettings()
app = FastAPI(title="Hora Valle · Edge (simulador de dispositivo)", version="1.0")
_detector: Detector | None = None
_door_cache: dict[int, tuple[float, DoorLine]] = {}


def detector() -> Detector:
    global _detector
    if _detector is None:
        if not settings.hf_token:
            raise HTTPException(503, "HF_TOKEN no configurado en el servicio edge")
        _detector = HFDetrDetector(settings.hf_token, settings.detector_model, settings.hf_provider, settings.detector_threshold)
    return _detector


def _check_key(key: str | None) -> None:
    if settings.sensor_api_key and key != settings.sensor_api_key:
        raise HTTPException(401, "X-Sensor-Key inválida")


def door_for(shop_id: int, override: str | None) -> DoorLine:
    if override:
        return DoorLine.from_dict(json.loads(override))
    hit = _door_cache.get(shop_id)
    if hit and time.time() - hit[0] < 300:
        return hit[1]
    door = DoorLine()
    try:
        r = httpx.get(f"{settings.api_url}/shops/{shop_id}", timeout=20)
        if r.status_code == 200:
            door = DoorLine.from_dict(r.json().get("door_line"))
    except httpx.HTTPError:
        log.warning("no se pudo leer la línea de puerta de la tienda %s; uso la de defecto", shop_id)
    _door_cache[shop_id] = (time.time(), door)
    return door


async def _read(image: UploadFile) -> bytes:
    data = await image.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "imagen demasiado grande")
    return data


@app.get("/health")
def health():
    return {"ok": True, "detector": settings.detector_model, "provider": settings.hf_provider, "hf_token": bool(settings.hf_token)}


@app.post("/edge/frames")
async def frames(
    image: UploadFile = File(...),
    shop_id: int = Form(...),
    ts: str | None = Form(None, description="ISO local; por defecto ahora (Europe/Madrid)"),
    frame_name: str | None = Form(None),
    truth: str | None = Form(None, description="JSON de ground truth de este fotograma"),
    door_line: str | None = Form(None),
    x_sensor_key: str | None = Header(None),
):
    _check_key(x_sensor_key)
    data = await _read(image)
    res = process_frame(data, detector(), door_for(shop_id, door_line), settings.eps_factor, settings.child_ratio)
    del data  # privacidad por diseño: la imagen se descarta aquí

    when = datetime.fromisoformat(ts) if ts else datetime.now(TZ).replace(tzinfo=None)
    payload = {
        "shop_id": shop_id,
        "ts": when.isoformat(timespec="seconds"),
        "frames": 1,
        "aggregates": res.aggregates,
        "detector": settings.detector_model,
        "synthetic": True,  # las imágenes de prueba son sintéticas
    }
    if truth:
        payload["eval"] = {"frame_name": frame_name, **evaluate(res.groups, json.loads(truth))}
    try:
        r = httpx.post(f"{settings.api_url}/sensor/aggregates", json=payload, headers={"X-Sensor-Key": settings.sensor_api_key}, timeout=60)
        r.raise_for_status()
        api_resp = r.json()
    except httpx.HTTPError as e:
        raise HTTPException(502, f"La API no aceptó los agregados: {e}") from e
    return {"sent": payload, "api": api_resp}


@app.post("/edge/debug")
async def debug(
    image: UploadFile = File(...),
    shop_id: int = Form(1),
    door_line: str | None = Form(None),
    x_sensor_key: str | None = Header(None),
):
    """Cajas y grupos de un fotograma para la vista "Sensor demo". No guarda nada."""
    _check_key(x_sensor_key)
    data = await _read(image)
    res = process_frame(data, detector(), door_for(shop_id, door_line), settings.eps_factor, settings.child_ratio)
    del data
    return res.debug_view()
