"""FastAPI dependencies: context, viewer (who is asking) and client IP."""
from __future__ import annotations

from fastapi import Depends, Header, Request

from src.app.context import AppContext
from src.app.core.errors import Unauthorized
from src.app.entitlement.service import ANON, Viewer


def get_ctx(request: Request) -> AppContext:
    return request.app.state.ctx


def viewer(authorization: str | None = Header(None), ctx: AppContext = Depends(get_ctx)) -> Viewer:
    if not authorization:
        return ANON
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise Unauthorized("use 'Authorization: Bearer <token>'")
    return ctx.entitlement.resolve(ctx.identity.user_from_token(token))


def signed_in(v: Viewer = Depends(viewer)) -> Viewer:
    if not v.user:
        raise Unauthorized("sign in required")
    return v


def client_ip(request: Request, ctx: AppContext = Depends(get_ctx)) -> str:
    if ctx.settings.trust_proxy:
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[0].strip()
    return request.client.host if request.client else ""
