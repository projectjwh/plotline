"""Fanboards, posts, comments, votes, reports and moderation (DCInside-style)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Callable

from src.app.community import anon
from src.app.community.repo import CommunityRepo, comments, posts
from src.app.community.rules import PromotionRule
from src.app.core.errors import Conflict, Forbidden, Invalid, NotFound, RateLimited
from src.app.core.db import now
from src.app.entitlement.service import Viewer
from src.app.identity.builtin_jwt import hash_secret, verify_secret

KINDS = {"title", "genre", "free"}


@dataclass
class Actor:
    """Who is acting: a signed-in viewer, or a guest with a nickname and password. The IP is always present."""
    viewer: Viewer
    ip: str
    nick: str | None = None
    password: str | None = None


class CommunityService:
    def __init__(self, repo: CommunityRepo, rule: PromotionRule, cfg: dict, salt: str, *,
                 title_lookup: Callable[[str], dict | None], genre_exists: Callable[[str], bool],
                 badge: Callable[[Viewer, dict], bool], viewer_for: Callable[[str], Viewer],
                 handle_for: Callable[[str], str | None]):
        self.repo, self.rule, self.cfg, self.salt = repo, rule, cfg, salt
        self.title_lookup, self.genre_exists, self.badge = title_lookup, genre_exists, badge
        self._viewer_for, self._handle_for = viewer_for, handle_for  # resolvers owned by identity/entitlement

    # ---------- identity helpers ----------
    def _keys(self, a: Actor) -> tuple[str, str]:
        iph = anon.ip_hash(a.ip, self.salt)
        return iph, anon.voter_key(a.viewer.user_id, iph)

    def _guard(self, a: Actor) -> tuple[str, str]:
        iph, key = self._keys(a)
        if self.repo.is_banned(list({key, f"ip:{iph}"}), now()):
            raise Forbidden("you are banned from posting", code="banned")
        return iph, key

    def _author_fields(self, a: Actor) -> dict:
        iph, key = self._guard(a)
        base = {"ip_prefix": anon.ip_prefix(a.ip), "ip_hash": iph, "voter_key": key}
        if a.viewer.user:
            return {**base, "user_id": a.viewer.user_id, "anon_nick": None, "anon_pw_hash": None}
        nick = (a.nick or "").strip()
        if not (1 <= len(nick) <= 20) or not a.password or len(a.password) < 4:
            raise Invalid("guests need a nickname (1–20 chars) and a password (≥ 4 chars)")
        return {**base, "user_id": None, "anon_nick": nick, "anon_pw_hash": hash_secret(a.password)}

    def _rate(self, table, key: str, per_min: int) -> None:
        if self.repo.count_recent(table, key, now() - timedelta(minutes=1)) >= per_min:
            raise RateLimited("slow down: posting limit reached, try again in a minute")

    def _can_moderate(self, viewer: Viewer, fanboard_id: str) -> bool:
        return viewer.is_admin or bool(viewer.user_id and self.repo.is_mod(fanboard_id, viewer.user_id))

    def _owns(self, a: Actor, row: dict) -> bool:
        if row["user_id"]:
            return row["user_id"] == a.viewer.user_id
        return verify_secret(row["anon_pw_hash"], a.password)

    # ---------- fanboards ----------
    def fanboard(self, kind: str, ref: str) -> dict:
        """Title and genre fanboards open on first use. Free boards are created by admins."""
        if kind not in KINDS:
            raise Invalid(f"kind must be one of {sorted(KINDS)}")
        g = self.repo.fanboard_by_ref(kind, ref)
        if g:
            return g
        if kind == "title":
            t = self.title_lookup(ref)
            if not t:
                raise NotFound(f"title '{ref}' not found")
            return self.repo.create_fanboard("title", ref, t["title"])
        if kind == "genre":
            if not self.genre_exists(ref):
                raise NotFound(f"genre '{ref}' not found")
            return self.repo.create_fanboard("genre", ref, ref)
        raise NotFound(f"board '{ref}' not found")

    def create_free_board(self, viewer: Viewer, slug: str, name: str) -> dict:
        if not viewer.is_admin:
            raise Forbidden("admins only")
        if self.repo.fanboard_by_ref("free", slug):
            raise Conflict("board exists")
        return self.repo.create_fanboard("free", slug, name)

    def list_fanboards(self, kind: str | None = None, limit: int = 50) -> list[dict]:
        return self.repo.list_fanboards(kind, limit)

    def _fanboard(self, fanboard_id: str) -> dict:
        g = self.repo.fanboard(fanboard_id)
        if not g:
            raise NotFound("fanboard not found")
        return g

    # ---------- presentation ----------
    def _present(self, row: dict, fanboard: dict, *, body: bool = True) -> dict:
        verified = False
        if row["user_id"] and fanboard["kind"] == "title":
            t = self.title_lookup(fanboard["ref"])
            verified = bool(t) and self.badge(self._viewer_for(row["user_id"]), t)
        out = {k: row[k] for k in ("id", "up", "down", "created_at") if k in row}
        out["created_at"] = row["created_at"].isoformat() if row.get("created_at") else None
        out["author"] = {"guest": not row["user_id"], "name": row.get("handle") or row["anon_nick"],
                         "ip_prefix": row["ip_prefix"] if not row["user_id"] else None, "verified_owner": verified}
        for k in ("title", "views", "is_concept", "is_notice", "comment_count", "parent_id", "post_id"):
            if k in row:
                out[k] = row[k]
        if body:
            out["body"] = row["body"] if not row.get("deleted_at") else None
        out["deleted"] = bool(row.get("deleted_at"))
        return out

    def _with_handle(self, row: dict) -> dict:
        if row.get("user_id"):
            row = {**row, "handle": self._handle_for(row["user_id"])}
        return row

    # ---------- posts ----------
    def list_posts(self, fanboard_id: str, *, tab: str = "all", limit: int = 30, offset: int = 0) -> dict:
        g = self._fanboard(fanboard_id)
        if tab not in {"all", "concept", "notice"}:
            raise Invalid("tab must be all, concept or notice")
        rows = self.repo.list_posts(fanboard_id, concept_only=tab == "concept", notices_only=tab == "notice",
                                    limit=min(limit, 100), offset=offset)
        return {"fanboard": g, "items": [self._present(self._with_handle(r), g, body=False) for r in rows]}

    def create_post(self, a: Actor, fanboard_id: str, title: str, body: str, notice: bool = False) -> dict:
        g = self._fanboard(fanboard_id)
        title, body = title.strip(), body.strip()
        if not title or len(title) > self.cfg.get("max_title_len", 120):
            raise Invalid("title is required (max 120 chars)")
        if not body or len(body) > self.cfg.get("max_body_len", 20000):
            raise Invalid("body is required")
        fields = self._author_fields(a)
        self._rate(posts, fields["voter_key"], self.cfg.get("posts_per_minute", 3))
        if notice:
            t = self.title_lookup(g["ref"]) if g["kind"] == "title" else None
            if not (self._can_moderate(a.viewer, fanboard_id) or (t and self.badge(a.viewer, t))):
                raise Forbidden("only moderators and verified owners can post notices")
        row = self.repo.insert(posts, {"fanboard_id": fanboard_id, **fields, "title": title, "body": body,
                                       "up": 0, "down": 0, "views": 0, "is_concept": False, "is_notice": notice})
        return self._present(self._with_handle(row), g)

    def get_post(self, post_id: str, *, count_view: bool = True) -> dict:
        p = self.repo.get(posts, post_id)
        if not p or p["deleted_at"]:
            raise NotFound("post not found")
        if count_view:
            self.repo.incr_views(post_id)
            p["views"] += 1
        g = self._fanboard(p["fanboard_id"])
        cms = [self._present(self._with_handle(c), g) for c in self.repo.list_comments(post_id)]
        return {**self._present(self._with_handle(p), g), "fanboard": {"id": g["id"], "kind": g["kind"],
                "ref": g["ref"], "name": g["name"]}, "comments": cms}

    def edit_post(self, a: Actor, post_id: str, title: str | None, body: str | None) -> dict:
        p = self.repo.get(posts, post_id)
        if not p or p["deleted_at"]:
            raise NotFound("post not found")
        if not self._owns(a, p):
            raise Forbidden("not your post (or wrong guest password)")
        vals = {"edited_at": now()}
        if title:
            vals["title"] = title.strip()[:120]
        if body:
            vals["body"] = body.strip()
        self.repo.patch(posts, post_id, **vals)
        return self.get_post(post_id, count_view=False)

    def delete(self, a: Actor, target_type: str, target_id: str) -> None:
        table = posts if target_type == "post" else comments
        row = self.repo.get(table, target_id)
        if not row or row["deleted_at"]:
            raise NotFound(f"{target_type} not found")
        gid = row["fanboard_id"] if target_type == "post" else self.repo.get(posts, row["post_id"])["fanboard_id"]
        if not (self._owns(a, row) or self._can_moderate(a.viewer, gid)):
            raise Forbidden("not yours, and you are not a moderator")
        self.repo.patch(table, target_id, deleted_at=now())

    # ---------- comments ----------
    def comment(self, a: Actor, post_id: str, body: str, parent_id: str | None = None) -> dict:
        p = self.repo.get(posts, post_id)
        if not p or p["deleted_at"]:
            raise NotFound("post not found")
        body = body.strip()
        if not body or len(body) > 5000:
            raise Invalid("comment body is required (max 5000 chars)")
        if parent_id:
            parent = self.repo.get(comments, parent_id)
            if not parent or parent["post_id"] != post_id or parent["parent_id"]:
                raise Invalid("replies must target a top-level comment on the same post")
        fields = self._author_fields(a)
        self._rate(comments, fields["voter_key"], self.cfg.get("comments_per_minute", 10))
        row = self.repo.insert(comments, {"post_id": post_id, "parent_id": parent_id, **fields, "body": body,
                                          "up": 0, "down": 0})
        return self._present(self._with_handle(row), self._fanboard(p["fanboard_id"]))

    # ---------- votes ----------
    def vote(self, a: Actor, target_type: str, target_id: str, value: int) -> dict:
        if target_type not in {"post", "comment"} or value not in (1, -1):
            raise Invalid("vote on a post or comment with value 1 or -1")
        table = posts if target_type == "post" else comments
        row = self.repo.get(table, target_id)
        if not row or row["deleted_at"]:
            raise NotFound(f"{target_type} not found")
        _, key = self._guard(a)
        if key == row["voter_key"]:
            raise Forbidden("you cannot vote on your own post")
        if not self.repo.add_vote(target_type, target_id, key, value):
            raise Conflict("already voted")
        row = self.repo.get(table, target_id)
        if target_type == "post" and not row["is_concept"] and self.rule.is_concept(row["up"], row["down"]):
            self.repo.patch(posts, target_id, is_concept=True)
            row["is_concept"] = True
        return {"up": row["up"], "down": row["down"], "is_concept": bool(row.get("is_concept"))}

    # ---------- reports & moderation ----------
    def report(self, a: Actor, target_type: str, target_id: str, reason: str) -> None:
        if target_type not in {"post", "comment"}:
            raise Invalid("report a post or comment")
        if not self.repo.get(posts if target_type == "post" else comments, target_id):
            raise NotFound(f"{target_type} not found")
        _, key = self._keys(a)
        if not reason.strip():
            raise Invalid("give a reason")
        if not self.repo.add_report(target_type, target_id, key, reason.strip()[:500]):
            raise Conflict("already reported")

    def report_queue(self, viewer: Viewer, status: str = "open") -> list[dict]:
        if not viewer.is_admin:
            raise Forbidden("admins only")
        out = []
        for r in self.repo.report_queue(status):
            row = self.repo.get(posts if r["target_type"] == "post" else comments, r["target_id"])
            out.append({**r, "first_at": r["first_at"].isoformat() if r["first_at"] else None,
                        "excerpt": (row.get("title") or row["body"])[:140] if row else None,
                        "ip_prefix": row["ip_prefix"] if row else None, "voter_key": row["voter_key"] if row else None,
                        "deleted": bool(row and row["deleted_at"])})
        return out

    def resolve_report(self, viewer: Viewer, target_type: str, target_id: str, action: str) -> None:
        if not viewer.is_admin:
            raise Forbidden("admins only")
        if action not in {"remove", "dismiss"}:
            raise Invalid("action must be remove or dismiss")
        if action == "remove":
            self.repo.patch(posts if target_type == "post" else comments, target_id, deleted_at=now())
        self.repo.resolve_reports(target_type, target_id, "actioned" if action == "remove" else "dismissed", viewer.user_id)

    def ban(self, viewer: Viewer, voter_key: str, days: int | None, reason: str) -> None:
        if not viewer.is_admin:
            raise Forbidden("admins only")
        if not (voter_key.startswith("u:") or voter_key.startswith("ip:")):
            raise Invalid("voter_key must start with u: or ip:")
        self.repo.ban(voter_key, now() + timedelta(days=days) if days else None, reason, viewer.user_id)

    def add_moderator(self, viewer: Viewer, fanboard_id: str, user_id: str) -> None:
        if not viewer.is_admin:
            raise Forbidden("admins only")
        self._fanboard(fanboard_id)
        self.repo.add_mod(fanboard_id, user_id)

    # ---------- signals for other modules ----------
    def activity_by_title(self, hours: int = 24) -> dict[str, int]:
        act = self.repo.activity_by_fanboard(now() - timedelta(hours=hours))
        gs = self.repo.fanboards_by_ids(act.keys())
        return {gs[g]["ref"]: n for g, n in act.items() if g in gs and gs[g]["kind"] == "title"}
