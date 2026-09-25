from __future__ import annotations

from datetime import datetime

from sqlalchemy import (Boolean, Column, DateTime, ForeignKey, Integer, PrimaryKeyConstraint, String, Table, Text,
                        delete, func, insert, select, update)
from sqlalchemy.engine import Engine

from src.app.core.db import metadata, new_id, now

ratings = Table(
    "ratings", metadata,
    Column("user_id", String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("title_key", String(255), nullable=False, index=True),
    Column("score", Integer, nullable=False),
    Column("review", Text),
    Column("is_owner", Boolean, nullable=False, default=False),   # verified owners' votes are excluded
    Column("created_at", DateTime, nullable=False),
    Column("updated_at", DateTime, nullable=False),
    PrimaryKeyConstraint("user_id", "title_key"),
)

follows = Table(
    "follows", metadata,
    Column("user_id", String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("target_type", String(10), nullable=False),    # title | author | publisher
    Column("target_ref", String(255), nullable=False),
    Column("created_at", DateTime, nullable=False),
    PrimaryKeyConstraint("user_id", "target_type", "target_ref"),
)

lists = Table(
    "lists", metadata,
    Column("id", String(32), primary_key=True),
    Column("user_id", String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("name", String(120), nullable=False),
    Column("public", Boolean, nullable=False, default=True),
    Column("created_at", DateTime, nullable=False),
)

list_items = Table(
    "list_items", metadata,
    Column("list_id", String(32), ForeignKey("lists.id", ondelete="CASCADE"), nullable=False),
    Column("title_key", String(255), nullable=False),
    Column("note", String(500)),
    Column("pos", Integer, nullable=False),
    PrimaryKeyConstraint("list_id", "title_key"),
)

wishlist = Table(
    "wishlist_votes", metadata,
    Column("user_id", String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("title_key", String(255), nullable=False, index=True),
    Column("medium", String(12), nullable=False),
    Column("created_at", DateTime, nullable=False),
    PrimaryKeyConstraint("user_id", "title_key", "medium"),
)

scout_events = Table(
    "scout_events", metadata,
    Column("user_id", String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("title_key", String(255), nullable=False),
    Column("followed_at", DateTime, nullable=False),
    Column("rising_at", DateTime, nullable=False),
    Column("points", Integer, nullable=False),
    PrimaryKeyConstraint("user_id", "title_key"),
)


class FanRepo:
    def __init__(self, engine: Engine):
        self.e = engine

    # ratings
    def upsert_rating(self, user_id, title_key, score, review, is_owner) -> None:
        with self.e.begin() as c:
            key = (ratings.c.user_id == user_id, ratings.c.title_key == title_key)
            if c.execute(select(ratings.c.score).where(*key)).first():
                c.execute(update(ratings).where(*key).values(score=score, review=review, is_owner=is_owner, updated_at=now()))
            else:
                t = now()
                c.execute(insert(ratings).values(user_id=user_id, title_key=title_key, score=score, review=review,
                                                 is_owner=is_owner, created_at=t, updated_at=t))

    def delete_rating(self, user_id, title_key) -> None:
        with self.e.begin() as c:
            c.execute(delete(ratings).where(ratings.c.user_id == user_id, ratings.c.title_key == title_key))

    def scores(self, title_key: str) -> list[int]:
        with self.e.connect() as c:
            return [r[0] for r in c.execute(select(ratings.c.score).where(ratings.c.title_key == title_key,
                                                                          ratings.c.is_owner.is_(False)))]

    def reviews(self, title_key: str, limit: int) -> list[dict]:
        with self.e.connect() as c:
            return [dict(r) for r in c.execute(
                select(ratings).where(ratings.c.title_key == title_key, ratings.c.review.is_not(None))
                .order_by(ratings.c.updated_at.desc()).limit(limit)).mappings()]

    def user_ratings(self, user_id: str) -> list[dict]:
        with self.e.connect() as c:
            return [dict(r) for r in c.execute(select(ratings).where(ratings.c.user_id == user_id)).mappings()]

    def set_owner_flag(self, user_id: str, title_key: str, flag: bool) -> None:
        with self.e.begin() as c:
            c.execute(update(ratings).where(ratings.c.user_id == user_id, ratings.c.title_key == title_key)
                      .values(is_owner=flag))

    # follows
    def follow(self, user_id, t, ref) -> bool:
        with self.e.begin() as c:
            if c.execute(select(follows).where(follows.c.user_id == user_id, follows.c.target_type == t,
                                               follows.c.target_ref == ref)).first():
                return False
            c.execute(insert(follows).values(user_id=user_id, target_type=t, target_ref=ref, created_at=now()))
            return True

    def unfollow(self, user_id, t, ref) -> None:
        with self.e.begin() as c:
            c.execute(delete(follows).where(follows.c.user_id == user_id, follows.c.target_type == t,
                                            follows.c.target_ref == ref))

    def user_follows(self, user_id) -> list[dict]:
        with self.e.connect() as c:
            return [dict(r) for r in c.execute(select(follows).where(follows.c.user_id == user_id)
                                               .order_by(follows.c.created_at.desc())).mappings()]

    def followers_before(self, title_key: str, at: datetime) -> list[dict]:
        with self.e.connect() as c:
            return [dict(r) for r in c.execute(select(follows).where(
                follows.c.target_type == "title", follows.c.target_ref == title_key, follows.c.created_at < at)).mappings()]

    def follower_count(self, t: str, ref: str) -> int:
        with self.e.connect() as c:
            return c.execute(select(func.count()).select_from(follows).where(
                follows.c.target_type == t, follows.c.target_ref == ref)).scalar_one()

    # lists
    def create_list(self, user_id, name, public) -> dict:
        row = {"id": new_id(), "user_id": user_id, "name": name, "public": public, "created_at": now()}
        with self.e.begin() as c:
            c.execute(insert(lists).values(**row))
        return row

    def get_list(self, list_id) -> dict | None:
        with self.e.connect() as c:
            r = c.execute(select(lists).where(lists.c.id == list_id)).mappings().first()
            if not r:
                return None
            items = [dict(i) for i in c.execute(select(list_items).where(list_items.c.list_id == list_id)
                                                .order_by(list_items.c.pos)).mappings()]
        return {**dict(r), "items": items}

    def user_lists(self, user_id, public_only: bool) -> list[dict]:
        q = select(lists).where(lists.c.user_id == user_id)
        if public_only:
            q = q.where(lists.c.public.is_(True))
        with self.e.connect() as c:
            return [dict(r) for r in c.execute(q.order_by(lists.c.created_at.desc())).mappings()]

    def add_item(self, list_id, title_key, note) -> bool:
        with self.e.begin() as c:
            if c.execute(select(list_items).where(list_items.c.list_id == list_id,
                                                  list_items.c.title_key == title_key)).first():
                return False
            pos = c.execute(select(func.coalesce(func.max(list_items.c.pos), 0)).where(
                list_items.c.list_id == list_id)).scalar_one() + 1
            c.execute(insert(list_items).values(list_id=list_id, title_key=title_key, note=note, pos=pos))
            return True

    def remove_item(self, list_id, title_key) -> None:
        with self.e.begin() as c:
            c.execute(delete(list_items).where(list_items.c.list_id == list_id, list_items.c.title_key == title_key))

    # wishlist
    def wish(self, user_id, title_key, medium) -> bool:
        with self.e.begin() as c:
            if c.execute(select(wishlist).where(wishlist.c.user_id == user_id, wishlist.c.title_key == title_key,
                                                wishlist.c.medium == medium)).first():
                return False
            c.execute(insert(wishlist).values(user_id=user_id, title_key=title_key, medium=medium, created_at=now()))
            return True

    def wishlist_board(self, medium: str, since: datetime, limit: int) -> list[dict]:
        recent = func.sum(func.cast(wishlist.c.created_at >= since, Integer)).label("recent")
        q = (select(wishlist.c.title_key, func.count().label("total"), recent)
             .where(wishlist.c.medium == medium).group_by(wishlist.c.title_key)
             .order_by(func.count().desc()).limit(limit))
        with self.e.connect() as c:
            return [dict(r) for r in c.execute(q).mappings()]

    def wishlist_totals(self, title_key: str) -> dict[str, int]:
        with self.e.connect() as c:
            return {m: n for m, n in c.execute(select(wishlist.c.medium, func.count()).where(
                wishlist.c.title_key == title_key).group_by(wishlist.c.medium))}

    # scout
    def add_scout(self, user_id, title_key, followed_at, rising_at, points) -> bool:
        with self.e.begin() as c:
            if c.execute(select(scout_events).where(scout_events.c.user_id == user_id,
                                                    scout_events.c.title_key == title_key)).first():
                return False
            c.execute(insert(scout_events).values(user_id=user_id, title_key=title_key, followed_at=followed_at,
                                                  rising_at=rising_at, points=points))
            return True

    def scout_calls(self, user_id) -> list[dict]:
        with self.e.connect() as c:
            return [dict(r) for r in c.execute(select(scout_events).where(scout_events.c.user_id == user_id)
                                               .order_by(scout_events.c.points.desc())).mappings()]

    def scout_leaders(self, limit) -> list[dict]:
        with self.e.connect() as c:
            return [dict(r) for r in c.execute(
                select(scout_events.c.user_id, func.sum(scout_events.c.points).label("points"),
                       func.count().label("calls")).group_by(scout_events.c.user_id)
                .order_by(func.sum(scout_events.c.points).desc()).limit(limit)).mappings()]
