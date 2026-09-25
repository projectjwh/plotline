"""Public market endpoints. Every title row passes through the KPI projector."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from src.app.context import AppContext
from src.app.core.errors import Forbidden
from src.app.deps import get_ctx, viewer
from src.app.entitlement.service import Viewer

router = APIRouter(tags=["market"])


def _p(ctx: AppContext, v: Viewer, rows):
    return ctx.kpi.project_many(rows, v.audiences)


def _guard_field(ctx: AppContext, v: Viewer, field: str | None) -> None:
    """Sorting or filtering by a hidden KPI would leak it, so treat that as access to it."""
    if field and ctx.kpi.level(field, v.audiences) == "hidden":
        raise Forbidden(f"'{field}' is a premium KPI", code="premium_required")


@router.get("/market/overview", summary="Indices, breadth, movers, new listings, most discussed")
def overview(limit: int = Query(8, le=50), v: Viewer = Depends(viewer), ctx: AppContext = Depends(get_ctx)):
    o = ctx.market.overview(limit)
    for k in ("gainers", "losers", "rank_up", "listings"):
        o[k] = _p(ctx, v, o[k])
    act = ctx.community.activity_by_title(24)
    top = sorted(act.items(), key=lambda kv: -kv[1])[:limit]
    discussed = []
    for cid, n in top:
        t = ctx.title_or_none(cid)
        if t:
            discussed.append({**ctx.kpi.project(t, v.audiences), "fan_activity_24h": n})
    o["most_discussed"] = discussed
    return o


@router.get("/market/indices", summary="Composite and genre indices (summary + 30-point spark)")
def indices(ctx: AppContext = Depends(get_ctx)):
    return [{k: i[k] for k in ("code", "name", "constituents", "value", "change_pct", "as_of") if k in i}
            | {"spark": [p["value"] for p in i["series"][-30:]]} for i in ctx.market.indices()]


@router.get("/market/indices/{code}", summary="One index with its full series")
def index(code: str, ctx: AppContext = Depends(get_ctx)):
    return ctx.market.index(code)


@router.get("/market/movers", summary="gainers | losers | rank_up | rank_down")
def movers(kind: str = "gainers", limit: int = Query(20, le=100), v: Viewer = Depends(viewer),
           ctx: AppContext = Depends(get_ctx)):
    return _p(ctx, v, ctx.market.movers(kind, limit))


@router.get("/market/breadth")
def breadth(ctx: AppContext = Depends(get_ctx)):
    return ctx.market.breadth()


@router.get("/market/listings", summary="New listings (first seen in the last N days)")
def listings(days: int | None = Query(None, ge=1, le=365), v: Viewer = Depends(viewer), ctx: AppContext = Depends(get_ctx)):
    return _p(ctx, v, ctx.market.listings(days))


@router.get("/market/treemap", summary="Heat-map data grouped by genre, publisher or platform")
def treemap(group_by: str = "genre", v: Viewer = Depends(viewer), ctx: AppContext = Depends(get_ctx)):
    return [{**g, "titles": _p(ctx, v, g["titles"])} for g in ctx.market.treemap(group_by)]


@router.get("/titles", summary="Filterable, sortable title list")
def titles(genre: str | None = None, platform: str | None = None, status: str | None = None,
           content_type: str | None = None, author: str | None = None, publisher: str | None = None,
           q: str | None = None, sort: str = "plotscore", desc: bool = True,
           limit: int = Query(50, le=200), offset: int = Query(0, ge=0),
           v: Viewer = Depends(viewer), ctx: AppContext = Depends(get_ctx)):
    _guard_field(ctx, v, sort)
    r = ctx.market.titles(genre=genre, platform=platform, status=status, content_type=content_type, author=author,
                          publisher=publisher, q=q, sort=sort, desc=desc, limit=limit, offset=offset)
    return {"total": r["total"], "items": _p(ctx, v, r["items"])}


@router.get("/titles/{comic_id:path}", summary="Title page: market data + fan signals")
def title(comic_id: str, v: Viewer = Depends(viewer), ctx: AppContext = Depends(get_ctx)):
    t = ctx.market.title(comic_id)
    return {**ctx.kpi.project(t, v.audiences),
            "fan_rating": ctx.fan.rating_summary(comic_id),
            "wishlist": ctx.fan.wishlist_totals(comic_id),
            "followers": ctx.fan.follower_count("title", comic_id),
            "viewer_owns": bool(v.user) and ctx.is_owner(v, comic_id)}


@router.get("/search")
def search(q: str = Query(..., min_length=1), limit: int = Query(20, le=100), v: Viewer = Depends(viewer),
           ctx: AppContext = Depends(get_ctx)):
    return _p(ctx, v, ctx.market.titles(q=q, limit=limit)["items"])


@router.get("/genres", summary="Genre (sector) board")
def genres(ctx: AppContext = Depends(get_ctx)):
    return ctx.market.genres()


@router.get("/publishers", summary="Publisher board")
def publishers(ctx: AppContext = Depends(get_ctx)):
    return ctx.market.publishers()


@router.get("/credits/{kind}/{name}", summary="IMDb-style credits for an author or publisher")
def credits(kind: str, name: str, v: Viewer = Depends(viewer), ctx: AppContext = Depends(get_ctx)):
    if kind not in ("author", "publisher"):
        raise Forbidden("kind must be author or publisher")
    works = ctx.market.titles(**{kind: name}, limit=200)["items"]
    return {"kind": kind, "name": name, "followers": ctx.fan.follower_count(kind, name),
            "works": _p(ctx, v, works)}


@router.get("/kpis/catalog", summary="The persona × KPI visibility matrix (from config/policy/kpis.yaml)")
def kpi_catalog(ctx: AppContext = Depends(get_ctx)):
    return ctx.kpi.catalog()
