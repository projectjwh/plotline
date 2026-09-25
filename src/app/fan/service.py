"""Fan features: ratings and reviews, follows, lists, adaptation wishlist, scout reputation, profiles."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable

from src.app.core.db import now
from src.app.core.errors import Conflict, Forbidden, Invalid, NotFound, Unauthorized
from src.app.entitlement.service import Viewer
from src.app.fan.ratings import RatingAggregator
from src.app.fan.repo import FanRepo
from src.app.fan.scout import ScoutRule

FOLLOW_TYPES = {"title", "author", "publisher"}


def _need_user(v: Viewer) -> str:
    if not v.user_id:
        raise Unauthorized("sign in to do this")
    return v.user_id


def _iso(r: dict) -> dict:
    return {k: (x.isoformat() if isinstance(x, datetime) else x) for k, x in r.items()}


class FanService:
    def __init__(self, repo: FanRepo, aggregator: RatingAggregator, scout: ScoutRule, cfg: dict, *,
                 title_exists: Callable[[str], bool], is_owner: Callable[[Viewer, str], bool],
                 handle_for: Callable[[str], str | None]):
        self.repo, self.agg, self.scout, self.cfg = repo, aggregator, scout, cfg
        self.title_exists, self.is_owner, self.handle_for = title_exists, is_owner, handle_for

    def _title(self, key: str) -> None:
        if not self.title_exists(key):
            raise NotFound(f"title '{key}' not found")

    # ratings
    def rate(self, v: Viewer, title_key: str, score: int, review: str | None) -> dict:
        uid = _need_user(v)
        self._title(title_key)
        if not (1 <= score <= 10):
            raise Invalid("score must be 1–10")
        review = (review or "").strip()[:5000] or None
        self.repo.upsert_rating(uid, title_key, score, review, self.is_owner(v, title_key))
        return self.rating_summary(title_key)

    def unrate(self, v: Viewer, title_key: str) -> None:
        self.repo.delete_rating(_need_user(v), title_key)

    def rating_summary(self, title_key: str) -> dict:
        return self.agg.aggregate(self.repo.scores(title_key))

    def reviews(self, title_key: str, limit: int = 20) -> list[dict]:
        return [{"handle": self.handle_for(r["user_id"]), "score": r["score"], "review": r["review"],
                 "owner": bool(r["is_owner"]), "updated_at": r["updated_at"].isoformat()}
                for r in self.repo.reviews(title_key, limit)]

    def refresh_owner_flags(self, v: Viewer) -> None:
        """Called when a claim is approved or revoked: re-flag that user's ratings."""
        for r in self.repo.user_ratings(v.user_id):
            self.repo.set_owner_flag(v.user_id, r["title_key"], self.is_owner(v, r["title_key"]))

    # follows
    def follow(self, v: Viewer, target_type: str, ref: str) -> None:
        uid = _need_user(v)
        if target_type not in FOLLOW_TYPES:
            raise Invalid(f"target_type must be one of {sorted(FOLLOW_TYPES)}")
        if target_type == "title":
            self._title(ref)
        self.repo.follow(uid, target_type, ref)

    def unfollow(self, v: Viewer, target_type: str, ref: str) -> None:
        self.repo.unfollow(_need_user(v), target_type, ref)

    def following(self, v: Viewer) -> list[dict]:
        return [_iso(r) for r in self.repo.user_follows(_need_user(v))]

    def follows_of(self, user_id: str) -> list[dict]:
        """Raw follow rows for another module (the feed)."""
        return self.repo.user_follows(user_id)

    def follower_count(self, target_type: str, ref: str) -> int:
        return self.repo.follower_count(target_type, ref)

    # lists
    def create_list(self, v: Viewer, name: str, public: bool = True) -> dict:
        name = name.strip()
        if not (1 <= len(name) <= 120):
            raise Invalid("list name is required (max 120 chars)")
        return _iso(self.repo.create_list(_need_user(v), name, public))

    def _own_list(self, v: Viewer, list_id: str) -> dict:
        lst = self.repo.get_list(list_id)
        if not lst:
            raise NotFound("list not found")
        if lst["user_id"] != _need_user(v):
            raise Forbidden("not your list")
        return lst

    def add_to_list(self, v: Viewer, list_id: str, title_key: str, note: str | None) -> dict:
        self._own_list(v, list_id)
        self._title(title_key)
        if not self.repo.add_item(list_id, title_key, (note or "")[:500] or None):
            raise Conflict("already in list")
        return self.get_list(v, list_id)

    def remove_from_list(self, v: Viewer, list_id: str, title_key: str) -> None:
        self._own_list(v, list_id)
        self.repo.remove_item(list_id, title_key)

    def get_list(self, v: Viewer, list_id: str) -> dict:
        lst = self.repo.get_list(list_id)
        if not lst or (not lst["public"] and lst["user_id"] != v.user_id):
            raise NotFound("list not found")
        return _iso({**lst, "owner": self.handle_for(lst["user_id"])})

    # wishlist
    def wish(self, v: Viewer, title_key: str, medium: str) -> dict:
        uid = _need_user(v)
        if medium not in self.cfg.get("wishlist_media", []):
            raise Invalid(f"medium must be one of {self.cfg.get('wishlist_media')}")
        self._title(title_key)
        if not self.repo.wish(uid, title_key, medium):
            raise Conflict("already wished for this medium")
        return self.repo.wishlist_totals(title_key)

    def wishlist_board(self, medium: str, limit: int = 20) -> list[dict]:
        if medium not in self.cfg.get("wishlist_media", []):
            raise Invalid(f"medium must be one of {self.cfg.get('wishlist_media')}")
        return self.repo.wishlist_board(medium, now() - timedelta(days=7), limit)

    def wishlist_totals(self, title_key: str) -> dict[str, int]:
        return self.repo.wishlist_totals(title_key)

    # scout
    def on_title_rising(self, payload: dict) -> int:
        """Event handler for title.entered_rising: award points to earlier followers."""
        key, at = payload["title_key"], payload.get("at") or now()
        if isinstance(at, str):
            at = datetime.fromisoformat(at)
        if at.tzinfo is not None:  # the app DB stores naive UTC
            at = at.astimezone(timezone.utc).replace(tzinfo=None)
        n = 0
        for f in self.repo.followers_before(key, at):
            pts = self.scout.points(f["created_at"], at)
            if pts > 0 and self.repo.add_scout(f["user_id"], key, f["created_at"], at, pts):
                n += 1
        return n

    def scout_leaders(self, limit: int = 20) -> list[dict]:
        return [{**r, "handle": self.handle_for(r["user_id"])} for r in self.repo.scout_leaders(limit)]

    # profile
    def profile(self, user_id: str, viewer: Viewer) -> dict:
        handle = self.handle_for(user_id)
        if not handle:
            raise NotFound("user not found")
        calls = [_iso(c) for c in self.repo.scout_calls(user_id)]
        return {"handle": handle, "ratings": len(self.repo.user_ratings(user_id)),
                "scout_points": sum(c["points"] for c in calls), "scout_calls": calls,
                "lists": [_iso(x) for x in self.repo.user_lists(user_id, public_only=viewer.user_id != user_id)]}
