from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException, Query

from ai import bandit, rules

from .. import services
from ..core import now_local

router = APIRouter(prefix="/ai", tags=["IA"])


@router.get("/rules", summary="Reglas de diagnóstico vigentes (ai/rules.yaml)")
def get_rules():
    return rules.load_rules()


@router.get("/offers", summary="Catálogo de ofertas y restricciones (ai/offers.yaml)")
def get_offers():
    return list(bandit.load_catalog().values())


@router.post("/notify/{shop_id}", summary="Fuerza el recálculo de la notificación de una franja")
def notify(shop_id: int, date_: date | None = Query(None, alias="date"), hour: int | None = Query(None, ge=0, le=23)):
    now = now_local()
    n = services.refresh_notification(shop_id, date_ or now.date(), hour if hour is not None else now.hour)
    if not n:
        raise HTTPException(404, "no hay agregados del sensor para esa franja")
    return n
