from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from src.app.community.service import Actor
from src.app.context import AppContext
from src.app.deps import client_ip, get_ctx, viewer
from src.app.entitlement.service import Viewer

router = APIRouter(tags=["community"])


class GuestFields(BaseModel):
    nick: str | None = None          # guests only
    password: str | None = None      # guests only (needed to edit/delete later)


class PostIn(GuestFields):
    title: str
    body: str
    notice: bool = False


class PostEdit(GuestFields):
    title: str | None = None
    body: str | None = None


class CommentIn(GuestFields):
    body: str
    parent_id: str | None = None


class VoteIn(BaseModel):
    target_type: str
    target_id: str
    value: int


class ReportIn(BaseModel):
    target_type: str
    target_id: str
    reason: str


class BoardIn(BaseModel):
    slug: str
    name: str


def _actor(v: Viewer, ip: str, g: GuestFields | None = None) -> Actor:
    return Actor(viewer=v, ip=ip, nick=g.nick if g else None, password=g.password if g else None)


@router.get("/fanboards", summary="Fanboards by activity")
def fanboards(kind: str | None = None, limit: int = Query(50, le=200), ctx: AppContext = Depends(get_ctx)):
    return ctx.community.list_fanboards(kind, limit)


@router.get("/fanboards/by/{kind}/{ref:path}", summary="Open a title/genre fanboard (created on first use)")
def fanboard_by_ref(kind: str, ref: str, ctx: AppContext = Depends(get_ctx)):
    return ctx.community.fanboard(kind, ref)


@router.get("/fanboards/{fanboard_id}/posts", summary="Post list (tab: all | concept | notice)")
def posts(fanboard_id: str, tab: str = "all", limit: int = Query(30, le=100), offset: int = Query(0, ge=0),
          ctx: AppContext = Depends(get_ctx)):
    return ctx.community.list_posts(fanboard_id, tab=tab, limit=limit, offset=offset)


@router.post("/fanboards/{fanboard_id}/posts", status_code=201, summary="Write a post (account or guest)")
def create_post(fanboard_id: str, body: PostIn, v: Viewer = Depends(viewer), ip: str = Depends(client_ip),
                ctx: AppContext = Depends(get_ctx)):
    return ctx.community.create_post(_actor(v, ip, body), fanboard_id, body.title, body.body, body.notice)


@router.get("/posts/{post_id}")
def get_post(post_id: str, ctx: AppContext = Depends(get_ctx)):
    return ctx.community.get_post(post_id)


@router.patch("/posts/{post_id}", summary="Edit (owner, or guest with password)")
def edit_post(post_id: str, body: PostEdit, v: Viewer = Depends(viewer), ip: str = Depends(client_ip),
              ctx: AppContext = Depends(get_ctx)):
    return ctx.community.edit_post(_actor(v, ip, body), post_id, body.title, body.body)


@router.post("/posts/{post_id}/delete", status_code=204, summary="Delete (owner, guest with password, or moderator)")
def delete_post(post_id: str, body: GuestFields | None = None, v: Viewer = Depends(viewer),
                ip: str = Depends(client_ip), ctx: AppContext = Depends(get_ctx)):
    ctx.community.delete(_actor(v, ip, body), "post", post_id)


@router.post("/posts/{post_id}/comments", status_code=201)
def comment(post_id: str, body: CommentIn, v: Viewer = Depends(viewer), ip: str = Depends(client_ip),
            ctx: AppContext = Depends(get_ctx)):
    return ctx.community.comment(_actor(v, ip, body), post_id, body.body, body.parent_id)


@router.post("/comments/{comment_id}/delete", status_code=204)
def delete_comment(comment_id: str, body: GuestFields | None = None, v: Viewer = Depends(viewer),
                   ip: str = Depends(client_ip), ctx: AppContext = Depends(get_ctx)):
    ctx.community.delete(_actor(v, ip, body), "comment", comment_id)


@router.post("/votes", summary="Up/down vote once per voter (account or IP)")
def vote(body: VoteIn, v: Viewer = Depends(viewer), ip: str = Depends(client_ip), ctx: AppContext = Depends(get_ctx)):
    return ctx.community.vote(_actor(v, ip), body.target_type, body.target_id, body.value)


@router.post("/reports", status_code=202)
def report(body: ReportIn, v: Viewer = Depends(viewer), ip: str = Depends(client_ip), ctx: AppContext = Depends(get_ctx)):
    ctx.community.report(_actor(v, ip), body.target_type, body.target_id, body.reason)
    return {"status": "received"}


@router.post("/boards", status_code=201, summary="Admin: create a free board")
def create_board(body: BoardIn, v: Viewer = Depends(viewer), ctx: AppContext = Depends(get_ctx)):
    return ctx.community.create_free_board(v, body.slug, body.name)
