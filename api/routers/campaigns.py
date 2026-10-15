from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from .. import services
from ..core import db

router = APIRouter(prefix="/campaigns", tags=["campañas"])


class ResultIn(BaseModel):
    """Opcional: si el comercio aporta sus propias cifras de la franja de la promo."""

    entries: int | None = Field(None, ge=0)
    exposed: int | None = Field(None, ge=0)
    revenue: float | None = Field(None, ge=0)
    purchases: int | None = Field(None, ge=0)


@router.post("/{campaign_id}/result", summary="Cierra la campaña: uplift frente a franjas comparables, diagnóstico y aprendizaje")
def campaign_result(campaign_id: int, body: ResultIn | None = None):
    with db() as conn:
        out = services.close_campaign(conn, campaign_id, body.model_dump(exclude_none=True) if body else None)
        conn.commit()
        return out
