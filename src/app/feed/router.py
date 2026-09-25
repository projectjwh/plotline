from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from src.app.context import AppContext
from src.app.deps import get_ctx, signed_in
from src.app.entitlement.service import Viewer

router = APIRouter(tags=["feed"])


@router.get("/feed", summary="Personal feed: followed titles, authors and publishers, newest first")
def feed(cursor: str | None = None, limit: int = Query(30, ge=1, le=50), lang: str | None = None,
         kinds: str | None = Query(None, description="comma-separated subset of: posts, rank_moves, new_titles, episodes"),
         v: Viewer = Depends(signed_in), ctx: AppContext = Depends(get_ctx)):
    out = ctx.feed.feed(v.user_id, cursor=cursor, limit=limit, lang=lang,
                        kinds={k.strip() for k in kinds.split(",")} if kinds else None)
    for item in out["items"]:  # title payloads go through the KPI projector like every other title payload
        if "title" in item and isinstance(item["title"], dict):
            item["title"] = ctx.kpi.project(item["title"], v.audiences)
    return out
