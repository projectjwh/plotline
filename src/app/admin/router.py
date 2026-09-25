"""Admin: claim review, plan grants, moderation and manual event triggers."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from src.app.context import AppContext
from src.app.core.errors import Forbidden, NotFound
from src.app.core.events import TITLE_ENTERED_RISING
from src.app.deps import get_ctx, viewer
from src.app.entitlement.service import Viewer

router = APIRouter(prefix="/admin", tags=["admin"])


def admin(v: Viewer = Depends(viewer)) -> Viewer:
    if not v.is_admin:
        raise Forbidden("admins only")
    return v


class DecisionIn(BaseModel):
    decision: str            # approve | reject | revoke
    note: str | None = None


class GrantIn(BaseModel):
    user_id: str
    plan: str


class ResolveIn(BaseModel):
    target_type: str
    target_id: str
    action: str              # remove | dismiss


class BanIn(BaseModel):
    voter_key: str
    days: int | None = None  # None = permanent
    reason: str


class ModIn(BaseModel):
    fanboard_id: str
    user_id: str


class RisingIn(BaseModel):
    title_key: str
    at: str | None = None    # ISO datetime; default now


@router.get("/claims")
def claims(status: str = "pending", v: Viewer = Depends(admin), ctx: AppContext = Depends(get_ctx)):
    return ctx.verification.queue(v, status)


@router.post("/claims/{claim_id}/decision")
def decide(claim_id: str, body: DecisionIn, v: Viewer = Depends(admin), ctx: AppContext = Depends(get_ctx)):
    return ctx.verification.decide(v, claim_id, body.decision, body.note)


@router.get("/claims/{claim_id}/documents/{key}", summary="Admin-only document download")
def document(claim_id: str, key: str, v: Viewer = Depends(admin), ctx: AppContext = Depends(get_ctx)):
    data, mime = ctx.verification.document(v, claim_id, key)
    return Response(content=data, media_type=mime, headers={"Content-Disposition": f'attachment; filename="{key}"',
                                                            "X-Content-Type-Options": "nosniff"})


@router.post("/grants", status_code=204, summary="Activate a plan (billing is off; admins grant)")
def grant(body: GrantIn, v: Viewer = Depends(admin), ctx: AppContext = Depends(get_ctx)):
    if not ctx.identity.get(body.user_id):
        raise NotFound("user not found")
    ctx.entitlement.grant(body.user_id, body.plan, v.user_id)


@router.post("/grants/remove", status_code=204)
def revoke_grant(body: GrantIn, v: Viewer = Depends(admin), ctx: AppContext = Depends(get_ctx)):
    ctx.entitlement.revoke(body.user_id, body.plan)


@router.get("/reports")
def reports(status: str = "open", v: Viewer = Depends(admin), ctx: AppContext = Depends(get_ctx)):
    return ctx.community.report_queue(v, status)


@router.post("/reports/resolve", status_code=204)
def resolve(body: ResolveIn, v: Viewer = Depends(admin), ctx: AppContext = Depends(get_ctx)):
    ctx.community.resolve_report(v, body.target_type, body.target_id, body.action)


@router.post("/bans", status_code=204)
def ban(body: BanIn, v: Viewer = Depends(admin), ctx: AppContext = Depends(get_ctx)):
    ctx.community.ban(v, body.voter_key, body.days, body.reason)


@router.post("/moderators", status_code=204)
def add_mod(body: ModIn, v: Viewer = Depends(admin), ctx: AppContext = Depends(get_ctx)):
    ctx.community.add_moderator(v, body.fanboard_id, body.user_id)


@router.post("/media/{media_id}/remove", status_code=204, summary="Remove an image for everyone")
def remove_media(media_id: str, v: Viewer = Depends(admin), ctx: AppContext = Depends(get_ctx)):
    ctx.media.remove(media_id)


@router.post("/events/rising", summary="Fire title.entered_rising (until the pipeline emits it)")
def rising(body: RisingIn, v: Viewer = Depends(admin), ctx: AppContext = Depends(get_ctx)):
    ctx.market.title(body.title_key)
    ctx.bus.publish(TITLE_ENTERED_RISING, {"title_key": body.title_key, "at": body.at})
    return {"status": "published"}
