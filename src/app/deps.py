"""FastAPI dependencies: context, viewer (who is asking) and client IP."""
from __future__ import annotations

from fastapi import Depends, Header, Request

from src.app.context import AppContext
from src.app.core import http
from src.app.core.errors import Forbidden, Unauthorized
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


def verified(v: Viewer = Depends(signed_in)) -> Viewer:
    """Signed in with a confirmed email: needed to rate, wish, keep lists, claim, or post under an account."""
    if not v.verified:
        raise Forbidden("confirm your email first", code="email_unverified")
    return v


def client_ip(request: Request, ctx: AppContext = Depends(get_ctx)) -> str:
    return http.client_ip({k.lower(): v for k, v in request.headers.items()},
                          request.client.host if request.client else "",
                          trust_proxy=ctx.settings.trust_proxy, ip_header=ctx.settings.client_ip_header)
