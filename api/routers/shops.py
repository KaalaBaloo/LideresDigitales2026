from __future__ import annotations

import json
import random
from datetime import date, datetime

from fastapi import APIRouter, Query
from pydantic import BaseModel

from ai import bandit, opportunity

from .. import services
from ..core import db, now_local

router = APIRouter(prefix="/shops", tags=["comercios"])


class CampaignIn(BaseModel):
    offer_type: str
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    duration_h: float = 3


class ShopPatch(BaseModel):
    capacity: int | None = None
    vetoed_offers: list[str] | None = None
    profile: dict | None = None
    door_line: dict | None = None


@router.get("", summary="Comercios de la demo")
def list_shops():
    with db() as conn:
        return conn.execute("select id, name, street, role, station_id, main_station_id, synthetic from shops order by id").fetchall()


@router.get("/{shop_id}", summary="Perfil del comercio")
def get_shop(shop_id: int):
    with db() as conn:
        s = services.get_shop(conn, shop_id)
        s["competitors_100m"] = services.competitors_100m(conn, s)
        s["offers_catalog"] = list(bandit.load_catalog().values())
        return s


@router.patch("/{shop_id}", summary="Actualiza perfil, aforo, ofertas vetadas o línea de puerta")
def patch_shop(shop_id: int, body: ShopPatch):
    sets, params = [], []
    for k, v in body.model_dump(exclude_none=True).items():
        sets.append(f"{k}=%s")
        params.append(json.dumps(v) if k in ("profile", "door_line") else v)
    with db() as conn:
        services.get_shop(conn, shop_id)
        if sets:
            conn.execute(f"update shops set {', '.join(sets)} where id=%s", (*params, shop_id))
            conn.commit()
        return services.get_shop(conn, shop_id)


@router.get("/{shop_id}/opportunities", summary="Curva del día por segmento y franjas de pérdida")
def opportunities(shop_id: int, date_: date | None = Query(None, alias="date")):
    with db() as conn:
        shop = services.get_shop(conn, shop_id)
        return services.day_opportunities(conn, shop, date_ or now_local().date())


@router.get("/{shop_id}/campaigns", summary="Historial de campañas con resultado y motivo")
def list_campaigns(shop_id: int):
    with db() as conn:
        return conn.execute(
            "select c.*, r.entries, r.revenue, r.avg_ticket, r.uplift, r.success, r.diagnosis, r.baseline "
            "from campaigns c left join campaign_results r on r.campaign_id=c.id where c.shop_id=%s order by c.starts_at desc",
            (shop_id,),
        ).fetchall()


@router.post("/{shop_id}/campaigns", summary="Lanza una oferta (guarda su contexto completo)")
def create_campaign(shop_id: int, body: CampaignIn):
    from datetime import timedelta

    start = body.starts_at or now_local().replace(minute=0, second=0, microsecond=0)
    end = body.ends_at or start + timedelta(hours=body.duration_h)
    with db() as conn:
        shop = services.get_shop(conn, shop_id)
        c = services.create_campaign(conn, shop, body.offer_type, start, end, synthetic=True)
        conn.execute("update notifications set status='acted' where shop_id=%s and day=%s and hour=%s", (shop_id, start.date(), start.hour))
        conn.commit()
        return c


@router.get("/{shop_id}/recommendation", summary="Oferta recomendada (Thompson sampling) para una franja")
def recommendation(shop_id: int, slot: int | None = Query(None, ge=0, le=23, description="hora"), date_: date | None = Query(None, alias="date")):
    now = now_local()
    day, hour = date_ or now.date(), slot if slot is not None else now.hour
    with db() as conn:
        shop = services.get_shop(conn, shop_id)
        obs = services.observations(conn, shop_id, day)
        at = [o for o in obs if int(o["hour"]) == hour] or obs
        seg, share = opportunity.dominant_segment(at)
        odd, n_odd, n = opportunity.odd_share(at)
        rec = bandit.recommend(
            services.load_arms(conn, shop_id),
            opportunity.franja_of(hour),
            seg,
            odd,
            vetoed=set(shop["vetoed_offers"] or []),
            max_discount=(shop["profile"] or {}).get("max_discount_pct"),
            allow_over_max=set((shop["profile"] or {}).get("allowed_over_max") or []),
        )
    return {"day": day, "hour": hour, "dominant_segment": seg, "dominant_share": round(share, 3), "odd_share": round(odd, 3), "groups": n, **rec}


@router.get("/{shop_id}/notifications", summary="Notificaciones generadas para el comercio")
def notifications(shop_id: int, limit: int = Query(20, le=100)):
    with db() as conn:
        return conn.execute("select * from notifications where shop_id=%s order by day desc, hour desc limit %s", (shop_id, limit)).fetchall()
