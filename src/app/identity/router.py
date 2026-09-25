from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from src.app.context import AppContext
from src.app.deps import get_ctx, signed_in
from src.app.entitlement.service import Viewer
from src.app.identity.service import public_user

router = APIRouter(tags=["accounts"])


class RegisterIn(BaseModel):
    email: str
    password: str
    handle: str


class LoginIn(BaseModel):
    email: str
    password: str


@router.post("/auth/register", status_code=201, summary="Create a fan account")
def register(body: RegisterIn, ctx: AppContext = Depends(get_ctx)):
    u = ctx.identity.register(body.email, body.password, body.handle)
    return {"user": public_user(u), "token": ctx.identity.provider.issue_token(u["id"])}


@router.post("/auth/login", summary="Exchange email + password for a bearer token")
def login(body: LoginIn, ctx: AppContext = Depends(get_ctx)):
    u, token = ctx.identity.login(body.email, body.password)
    return {"user": public_user(u), "token": token}


@router.get("/me", summary="Current user, personas and what each premium persona still needs")
def me(v: Viewer = Depends(signed_in), ctx: AppContext = Depends(get_ctx)):
    return {"user": public_user(v.user), "entitlement": ctx.entitlement.status(v)}
