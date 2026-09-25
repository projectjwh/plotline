"""Premium endpoints: verified and entitled personas only. Competitor titles are visible at full depth (spec decision)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from src.app.context import AppContext
from src.app.core.errors import Invalid
from src.app.deps import get_ctx, viewer
from src.app.entitlement.service import EntitlementService, Viewer, owns_title

router = APIRouter(prefix="/premium", tags=["premium"])


def premium(v: Viewer = Depends(viewer)) -> Viewer:
    EntitlementService.require_premium(v)
    return v


@router.get("/titles/{comic_id:path}", summary="Full-depth title profile")
def title(comic_id: str, v: Viewer = Depends(premium), ctx: AppContext = Depends(get_ctx)):
    t = ctx.market.title(comic_id)
    return {**ctx.kpi.project(t, v.audiences), "fan_rating": ctx.fan.rating_summary(comic_id),
            "wishlist": ctx.fan.wishlist_totals(comic_id), "followers": ctx.fan.follower_count("title", comic_id)}


@router.get("/valuation/{comic_id:path}", summary="Valuation band (model) with drivers and assumptions")
def valuation(comic_id: str, v: Viewer = Depends(premium), ctx: AppContext = Depends(get_ctx)):
    t = ctx.market.title(comic_id)
    return {"comic_id": comic_id, "title": t["title"], **ctx.valuation.value(t)}


@router.get("/compare", summary="Side-by-side (2–6 titles)")
def compare(ids: str = Query(..., description="comma-separated comic_ids"), v: Viewer = Depends(premium),
            ctx: AppContext = Depends(get_ctx)):
    keys = [x.strip() for x in ids.split(",") if x.strip()]
    if not 2 <= len(keys) <= 6:
        raise Invalid("compare 2 to 6 titles")
    return [{**ctx.kpi.project(ctx.market.title(k), v.audiences), "fan_rating": ctx.fan.rating_summary(k),
             "wishlist": ctx.fan.wishlist_totals(k)} for k in keys]


@router.get("/screener", summary="Scouting screener (readiness, status, genre, format)")
def screener(genre: str | None = None, status: str | None = None, content_type: str | None = None,
             platform: str | None = None, min_readiness: int | None = Query(None, ge=0, le=100),
             sort: str = "readiness", limit: int = Query(50, le=200), offset: int = Query(0, ge=0),
             v: Viewer = Depends(premium), ctx: AppContext = Depends(get_ctx)):
    r = ctx.market.titles(genre=genre, status=status, content_type=content_type, platform=platform,
                          min_readiness=min_readiness, sort=sort, limit=limit, offset=offset)
    items = []
    for t in r["items"]:
        items.append({**ctx.kpi.project(t, v.audiences), "wishlist": ctx.fan.wishlist_totals(t["comic_id"])})
    return {"total": r["total"], "items": items}


@router.get("/portfolio", summary="Titles covered by the caller's approved claims")
def portfolio(v: Viewer = Depends(premium), ctx: AppContext = Depends(get_ctx)):
    u = ctx.market.titles(limit=100000)["items"]
    mine = [t for t in u if owns_title(v.claims, t)]
    return {"claims": [{k: c[k] for k in ("claim_type", "entity_ref", "entity_name")} for c in v.claims],
            "titles": ctx.kpi.project_many(mine, v.audiences),
            "summary": {"titles": len(mine),
                        "avg_plotscore": round(sum(t["plotscore"] or 0 for t in mine) / len(mine), 1) if mine else None,
                        "total_views": sum(t["views"] or 0 for t in mine)}}
