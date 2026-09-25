from __future__ import annotations

from fastapi import APIRouter, Depends, File, Response, UploadFile

from src.app.community.anon import ip_hash, voter_key
from src.app.context import AppContext
from src.app.core.errors import Forbidden
from src.app.deps import client_ip, get_ctx, viewer
from src.app.entitlement.service import Viewer

router = APIRouter(tags=["media"])


@router.post("/media", status_code=201, summary="Upload a fanboard image (JPEG, PNG, WebP, GIF; metadata stripped)")
async def upload(file: UploadFile = File(...), v: Viewer = Depends(viewer), ip: str = Depends(client_ip),
                 ctx: AppContext = Depends(get_ctx)):
    if v.user and not v.verified:
        raise Forbidden("confirm your email to upload images", code="email_unverified")
    limit = ctx.media.cfg.get("max_image_mb", 5) * 1024 * 1024
    data = await file.read(limit + 1)   # the service rejects anything over the limit
    owner = voter_key(v.user_id, ip_hash(ip, ctx.settings.ip_hash_salt))
    return ctx.media.upload(owner, v.user is None, data)


@router.get("/media/{media_id}", summary="Serve an image")
def serve(media_id: str, ctx: AppContext = Depends(get_ctx)):
    data, mime = ctx.media.read(media_id)
    return Response(content=data, media_type=mime, headers={
        "Cache-Control": "public, max-age=86400", "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'"})
