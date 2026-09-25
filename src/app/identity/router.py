from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from src.app.community.anon import ip_hash
from src.app.context import AppContext
from src.app.deps import client_ip, get_ctx, signed_in
from src.app.entitlement.service import Viewer
from src.app.identity.service import public_user

router = APIRouter(tags=["accounts"])


class RegisterIn(BaseModel):
    email: str
    password: str
    handle: str
    locale: str = "en"


class LoginIn(BaseModel):
    email: str
    password: str


class TokenIn(BaseModel):
    token: str


class EmailIn(BaseModel):
    email: str


class ResetIn(BaseModel):
    token: str
    password: str


class LocaleIn(BaseModel):
    locale: str


def _ip_key(ctx: AppContext, ip: str) -> str:
    return "ip:" + ip_hash(ip, ctx.settings.ip_hash_salt)


@router.post("/auth/register", status_code=201, summary="Create a fan account (sends a verification email)")
def register(body: RegisterIn, ip: str = Depends(client_ip), ctx: AppContext = Depends(get_ctx)):
    u = ctx.identity.register(body.email, body.password, body.handle, ip_key=_ip_key(ctx, ip), locale=body.locale)
    return {"user": public_user(u), "token": ctx.identity.access_token(u)}


@router.post("/auth/login", summary="Exchange email + password for a bearer token (throttled)")
def login(body: LoginIn, ip: str = Depends(client_ip), ctx: AppContext = Depends(get_ctx)):
    u, token = ctx.identity.login(body.email, body.password, ip_key=_ip_key(ctx, ip))
    return {"user": public_user(u), "token": token}


@router.post("/auth/verify/request", status_code=202, summary="Send the verification email again")
def verify_request(v: Viewer = Depends(signed_in), ctx: AppContext = Depends(get_ctx)):
    ctx.identity.send_verification(v.user)
    return {"status": "sent"}


@router.post("/auth/verify/confirm", summary="Confirm an email with the token from the link")
def verify_confirm(body: TokenIn, ctx: AppContext = Depends(get_ctx)):
    return {"user": public_user(ctx.identity.confirm_verification(body.token))}


@router.post("/auth/password/forgot", status_code=202, summary="Email a reset link (same answer whether or not the email exists)")
def forgot(body: EmailIn, ip: str = Depends(client_ip), ctx: AppContext = Depends(get_ctx)):
    ctx.identity.forgot(body.email, ip_key=_ip_key(ctx, ip))
    return {"status": "if that address has an account, a reset link is on its way"}


@router.post("/auth/password/reset", status_code=204, summary="Set a new password; signs out every session")
def reset(body: ResetIn, ctx: AppContext = Depends(get_ctx)):
    ctx.identity.reset(body.token, body.password)


@router.get("/me", summary="Current user, personas and what each premium persona still needs")
def me(v: Viewer = Depends(signed_in), ctx: AppContext = Depends(get_ctx)):
    return {"user": public_user(v.user), "entitlement": ctx.entitlement.status(v)}


@router.patch("/me", summary="Update preferences (locale: en | ko)")
def update_me(body: LocaleIn, v: Viewer = Depends(signed_in), ctx: AppContext = Depends(get_ctx)):
    return {"user": public_user(ctx.identity.set_locale(v.user_id, body.locale))}
