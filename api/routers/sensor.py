from __future__ import annotations

from datetime import datetime

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from ai.opportunity import SEGMENTS

from .. import services
from ..core import db, require_sensor_key, settings

router = APIRouter(prefix="/sensor", tags=["sensor"])


class SegmentAggregate(BaseModel):
    segment: str
    groups_passing: int = Field(0, ge=0)
    groups_entering: int = Field(0, ge=0)
    people_passing: int = Field(0, ge=0)
    people_entering: int = Field(0, ge=0)
    odd_groups: int = Field(0, ge=0)


class AggregatesIn(BaseModel):
    """Lo único que sube el dispositivo: recuentos por segmento. Sin imágenes ni coordenadas."""

    shop_id: int
    ts: datetime
    frames: int = 1
    aggregates: list[SegmentAggregate]
    detector: str | None = None
    synthetic: bool = True
    eval: dict | None = None


@router.post("/aggregates", dependencies=[Depends(require_sensor_key)], summary="Recibe agregados del dispositivo edge")
def post_aggregates(body: AggregatesIn, bg: BackgroundTasks):
    bad = [a.segment for a in body.aggregates if a.segment not in SEGMENTS]
    if bad:
        raise HTTPException(422, f"segmentos desconocidos: {bad}")
    day, hour = body.ts.date(), body.ts.hour
    with db() as conn:
        services.get_shop(conn, body.shop_id)
        for a in body.aggregates:
            conn.execute(
                "insert into sensor_aggregates(shop_id, day, hour, segment, groups_passing, groups_entering, people_passing, people_entering, odd_groups, frames, synthetic) "
                "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) on conflict (shop_id, day, hour, segment, synthetic) do update set "
                "groups_passing=sensor_aggregates.groups_passing+excluded.groups_passing, groups_entering=sensor_aggregates.groups_entering+excluded.groups_entering, "
                "people_passing=sensor_aggregates.people_passing+excluded.people_passing, people_entering=sensor_aggregates.people_entering+excluded.people_entering, "
                "odd_groups=sensor_aggregates.odd_groups+excluded.odd_groups, frames=sensor_aggregates.frames+excluded.frames, updated_at=now()",
                (body.shop_id, day, hour, a.segment, a.groups_passing, a.groups_entering, a.people_passing, a.people_entering, a.odd_groups, body.frames, body.synthetic),
            )
        if body.eval:
            e = body.eval
            conn.execute(
                "insert into sensor_eval(shop_id, frame_name, count_true, count_pred, segment_match, synthetic) values (%s,%s,%s,%s,%s,%s)",
                (body.shop_id, e.get("frame_name"), e.get("count_true"), e.get("count_pred"), e.get("segment_match"), body.synthetic),
            )
        conn.commit()
    bg.add_task(services.refresh_notification, body.shop_id, day, hour)
    return {"stored": len(body.aggregates), "day": day, "hour": hour, "notification": "recalculando"}


@router.post("/debug-frame", summary="Demo: cajas y grupos de un fotograma (vía servicio edge; no se guarda)")
async def debug_frame(image: UploadFile = File(...), shop_id: int = Form(1)):
    data = await image.read()
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(
                f"{settings().edge_url}/edge/debug",
                data={"shop_id": str(shop_id)},
                files={"image": (image.filename or "frame.png", data, image.content_type or "image/png")},
                headers={"X-Sensor-Key": settings().sensor_api_key},
            )
    finally:
        del data  # la API no conserva la imagen
    if r.status_code != 200:
        raise HTTPException(r.status_code, r.text[:300])
    return r.json()


@router.get("/eval", summary="Precisión del sensor frente al ground truth")
def eval_summary(shop_id: int | None = None):
    with db() as conn:
        return conn.execute(
            "select count(*) frames, avg(1 - abs(count_pred-count_true)::float/nullif(count_true,0)) count_accuracy, avg(segment_match) segment_match, "
            "sum(count_true) people_true, sum(count_pred) people_pred from sensor_eval where (%s::int is null or shop_id=%s)",
            (shop_id, shop_id),
        ).fetchone()
