from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from src.app.context import AppContext
from src.app.deps import get_ctx, signed_in, viewer
from src.app.entitlement.service import Viewer

router = APIRouter(tags=["fan"])


class RatingIn(BaseModel):
    score: int
    review: str | None = None


class FollowIn(BaseModel):
    target_type: str
    ref: str


class ListIn(BaseModel):
    name: str
    public: bool = True


class ListItemIn(BaseModel):
    title_key: str
    note: str | None = None


class WishIn(BaseModel):
    medium: str


@router.put("/ratings/{comic_id:path}", summary="Rate a title 1–10 (optional review)")
def rate(comic_id: str, body: RatingIn, v: Viewer = Depends(signed_in), ctx: AppContext = Depends(get_ctx)):
    return ctx.fan.rate(v, comic_id, body.score, body.review)


@router.delete("/ratings/{comic_id:path}", status_code=204)
def unrate(comic_id: str, v: Viewer = Depends(signed_in), ctx: AppContext = Depends(get_ctx)):
    ctx.fan.unrate(v, comic_id)


@router.get("/reviews/{comic_id:path}")
def reviews(comic_id: str, limit: int = Query(20, le=100), ctx: AppContext = Depends(get_ctx)):
    return ctx.fan.reviews(comic_id, limit)


@router.post("/follows", status_code=204)
def follow(body: FollowIn, v: Viewer = Depends(signed_in), ctx: AppContext = Depends(get_ctx)):
    ctx.fan.follow(v, body.target_type, body.ref)


@router.post("/follows/remove", status_code=204)
def unfollow(body: FollowIn, v: Viewer = Depends(signed_in), ctx: AppContext = Depends(get_ctx)):
    ctx.fan.unfollow(v, body.target_type, body.ref)


@router.get("/me/follows")
def my_follows(v: Viewer = Depends(signed_in), ctx: AppContext = Depends(get_ctx)):
    return ctx.fan.following(v)


@router.post("/lists", status_code=201)
def create_list(body: ListIn, v: Viewer = Depends(signed_in), ctx: AppContext = Depends(get_ctx)):
    return ctx.fan.create_list(v, body.name, body.public)


@router.get("/lists/{list_id}")
def get_list(list_id: str, v: Viewer = Depends(viewer), ctx: AppContext = Depends(get_ctx)):
    return ctx.fan.get_list(v, list_id)


@router.post("/lists/{list_id}/items", status_code=201)
def add_item(list_id: str, body: ListItemIn, v: Viewer = Depends(signed_in), ctx: AppContext = Depends(get_ctx)):
    return ctx.fan.add_to_list(v, list_id, body.title_key, body.note)


@router.post("/lists/{list_id}/items/remove", status_code=204)
def remove_item(list_id: str, body: ListItemIn, v: Viewer = Depends(signed_in), ctx: AppContext = Depends(get_ctx)):
    ctx.fan.remove_from_list(v, list_id, body.title_key)


@router.post("/wishlist/{comic_id:path}", summary="Wish for an adaptation (anime, drama, film, game)")
def wish(comic_id: str, body: WishIn, v: Viewer = Depends(signed_in), ctx: AppContext = Depends(get_ctx)):
    return ctx.fan.wish(v, comic_id, body.medium)


@router.get("/wishlist", summary="Most-wished titles for a medium")
def wishlist(medium: str = "anime", limit: int = Query(20, le=100), ctx: AppContext = Depends(get_ctx)):
    return ctx.fan.wishlist_board(medium, limit)


@router.get("/users/{handle}", summary="Fan profile: scout calls, lists")
def profile(handle: str, v: Viewer = Depends(viewer), ctx: AppContext = Depends(get_ctx)):
    return ctx.fan.profile(ctx.identity.by_handle(handle)["id"], v)


@router.get("/scouts", summary="Scout leaderboard")
def scouts(limit: int = Query(20, le=100), ctx: AppContext = Depends(get_ctx)):
    return ctx.fan.scout_leaders(limit)
