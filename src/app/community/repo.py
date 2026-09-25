from __future__ import annotations

from datetime import datetime

from sqlalchemy import (Boolean, Column, DateTime, ForeignKey, Integer, PrimaryKeyConstraint, String, Table, Text,
                        UniqueConstraint, and_, func, insert, or_, select, update)
from sqlalchemy.engine import Engine

from src.app.core.db import metadata, new_id, now

galleries = Table(
    "galleries", metadata,
    Column("id", String(32), primary_key=True),
    Column("kind", String(10), nullable=False),           # title | genre | free
    Column("ref", String(255), nullable=False),           # comic_id | genre parent | slug
    Column("name", String(255), nullable=False),
    Column("created_at", DateTime, nullable=False),
    UniqueConstraint("kind", "ref"),
)

_author_cols = lambda: [  # noqa: E731 — shared by posts and comments
    Column("user_id", String(32), ForeignKey("users.id", ondelete="SET NULL")),
    Column("anon_nick", String(40)),
    Column("anon_pw_hash", String(255)),
    Column("ip_prefix", String(20), nullable=False),
    Column("ip_hash", String(64), nullable=False, index=True),
    Column("voter_key", String(80), nullable=False, index=True),
]

posts = Table(
    "posts", metadata,
    Column("id", String(32), primary_key=True),
    Column("gallery_id", String(32), ForeignKey("galleries.id"), nullable=False, index=True),
    *_author_cols(),
    Column("title", String(200), nullable=False),
    Column("body", Text, nullable=False),
    Column("up", Integer, nullable=False, default=0),
    Column("down", Integer, nullable=False, default=0),
    Column("views", Integer, nullable=False, default=0),
    Column("is_concept", Boolean, nullable=False, default=False),
    Column("is_notice", Boolean, nullable=False, default=False),
    Column("created_at", DateTime, nullable=False, index=True),
    Column("edited_at", DateTime),
    Column("deleted_at", DateTime),
)

comments = Table(
    "comments", metadata,
    Column("id", String(32), primary_key=True),
    Column("post_id", String(32), ForeignKey("posts.id"), nullable=False, index=True),
    Column("parent_id", String(32), ForeignKey("comments.id")),
    *_author_cols(),
    Column("body", Text, nullable=False),
    Column("up", Integer, nullable=False, default=0),
    Column("down", Integer, nullable=False, default=0),
    Column("created_at", DateTime, nullable=False, index=True),
    Column("deleted_at", DateTime),
)

votes = Table(
    "votes", metadata,
    Column("target_type", String(10), nullable=False),
    Column("target_id", String(32), nullable=False),
    Column("voter_key", String(80), nullable=False),
    Column("value", Integer, nullable=False),
    Column("created_at", DateTime, nullable=False),
    PrimaryKeyConstraint("target_type", "target_id", "voter_key"),
)

reports = Table(
    "reports", metadata,
    Column("id", String(32), primary_key=True),
    Column("target_type", String(10), nullable=False),
    Column("target_id", String(32), nullable=False),
    Column("reporter_key", String(80), nullable=False),
    Column("reason", String(500), nullable=False),
    Column("status", String(10), nullable=False, default="open"),   # open | actioned | dismissed
    Column("resolved_by", String(32)),
    Column("created_at", DateTime, nullable=False),
    Column("resolved_at", DateTime),
    UniqueConstraint("target_type", "target_id", "reporter_key"),
)

bans = Table(
    "bans", metadata,
    Column("key", String(80), primary_key=True),          # voter_key: u:<id> | ip:<hash>
    Column("until", DateTime),                            # null = permanent
    Column("reason", String(500)),
    Column("created_by", String(32)),
    Column("created_at", DateTime, nullable=False),
)

gallery_mods = Table(
    "gallery_mods", metadata,
    Column("gallery_id", String(32), ForeignKey("galleries.id"), nullable=False),
    Column("user_id", String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    PrimaryKeyConstraint("gallery_id", "user_id"),
)


def _one(c, stmt):
    r = c.execute(stmt).mappings().first()
    return dict(r) if r else None


class CommunityRepo:
    def __init__(self, engine: Engine):
        self.e = engine

    # galleries
    def gallery(self, gallery_id: str):
        with self.e.connect() as c:
            return _one(c, select(galleries).where(galleries.c.id == gallery_id))

    def gallery_by_ref(self, kind: str, ref: str):
        with self.e.connect() as c:
            return _one(c, select(galleries).where(galleries.c.kind == kind, galleries.c.ref == ref))

    def create_gallery(self, kind: str, ref: str, name: str) -> dict:
        row = {"id": new_id(), "kind": kind, "ref": ref, "name": name, "created_at": now()}
        with self.e.begin() as c:
            c.execute(insert(galleries).values(**row))
        return row

    def list_galleries(self, kind: str | None, limit: int) -> list[dict]:
        q = (select(galleries, func.count(posts.c.id).label("posts"))
             .select_from(galleries.outerjoin(posts, and_(posts.c.gallery_id == galleries.c.id, posts.c.deleted_at.is_(None))))
             .group_by(*galleries.c).order_by(func.count(posts.c.id).desc()).limit(limit))
        if kind:
            q = q.where(galleries.c.kind == kind)
        with self.e.connect() as c:
            return [dict(r) for r in c.execute(q).mappings()]

    def is_mod(self, gallery_id: str, user_id: str) -> bool:
        with self.e.connect() as c:
            return c.execute(select(gallery_mods).where(gallery_mods.c.gallery_id == gallery_id,
                                                        gallery_mods.c.user_id == user_id)).first() is not None

    def add_mod(self, gallery_id: str, user_id: str) -> None:
        with self.e.begin() as c:
            if not c.execute(select(gallery_mods).where(gallery_mods.c.gallery_id == gallery_id,
                                                        gallery_mods.c.user_id == user_id)).first():
                c.execute(insert(gallery_mods).values(gallery_id=gallery_id, user_id=user_id))

    # posts & comments
    def insert(self, table: Table, row: dict) -> dict:
        row = {"id": new_id(), "created_at": now(), **row}
        with self.e.begin() as c:
            c.execute(insert(table).values(**row))
        return row

    def get(self, table: Table, id_: str):
        with self.e.connect() as c:
            return _one(c, select(table).where(table.c.id == id_))

    def patch(self, table: Table, id_: str, **values) -> None:
        with self.e.begin() as c:
            c.execute(update(table).where(table.c.id == id_).values(**values))

    def incr_views(self, post_id: str) -> None:
        with self.e.begin() as c:
            c.execute(update(posts).where(posts.c.id == post_id).values(views=posts.c.views + 1))

    def list_posts(self, gallery_id: str, *, concept_only: bool, notices_only: bool, limit: int, offset: int):
        cc = (select(func.count(comments.c.id)).where(comments.c.post_id == posts.c.id, comments.c.deleted_at.is_(None))
              .scalar_subquery().label("comment_count"))
        q = (select(posts, cc).where(posts.c.gallery_id == gallery_id, posts.c.deleted_at.is_(None))
             .order_by(posts.c.is_notice.desc(), posts.c.created_at.desc()).limit(limit).offset(offset))
        if concept_only:
            q = q.where(posts.c.is_concept.is_(True))
        if notices_only:
            q = q.where(posts.c.is_notice.is_(True))
        with self.e.connect() as c:
            return [dict(r) for r in c.execute(q).mappings()]

    def list_comments(self, post_id: str):
        with self.e.connect() as c:
            return [dict(r) for r in c.execute(select(comments).where(comments.c.post_id == post_id)
                                               .order_by(comments.c.created_at)).mappings()]

    def count_recent(self, table: Table, key: str, since: datetime) -> int:
        with self.e.connect() as c:
            return c.execute(select(func.count()).select_from(table)
                             .where(table.c.voter_key == key, table.c.created_at >= since)).scalar_one()

    # votes
    def add_vote(self, target_type: str, target_id: str, key: str, value: int) -> bool:
        """Insert the vote and bump the counter in one transaction. False if this voter already voted."""
        table = posts if target_type == "post" else comments
        col = table.c.up if value > 0 else table.c.down
        with self.e.begin() as c:
            if c.execute(select(votes).where(votes.c.target_type == target_type, votes.c.target_id == target_id,
                                             votes.c.voter_key == key)).first():
                return False
            c.execute(insert(votes).values(target_type=target_type, target_id=target_id, voter_key=key,
                                           value=value, created_at=now()))
            c.execute(update(table).where(table.c.id == target_id).values({col.name: col + 1}))
        return True

    # reports & bans
    def add_report(self, target_type: str, target_id: str, key: str, reason: str) -> bool:
        with self.e.begin() as c:
            if c.execute(select(reports.c.id).where(reports.c.target_type == target_type, reports.c.target_id == target_id,
                                                    reports.c.reporter_key == key)).first():
                return False
            c.execute(insert(reports).values(id=new_id(), target_type=target_type, target_id=target_id,
                                             reporter_key=key, reason=reason, status="open", created_at=now()))
        return True

    def report_queue(self, status: str) -> list[dict]:
        q = (select(reports.c.target_type, reports.c.target_id, func.count().label("reports"),
                    func.min(reports.c.created_at).label("first_at"))
             .where(reports.c.status == status).group_by(reports.c.target_type, reports.c.target_id)
             .order_by(func.count().desc()))
        with self.e.connect() as c:
            return [dict(r) for r in c.execute(q).mappings()]

    def resolve_reports(self, target_type: str, target_id: str, status: str, by: str) -> None:
        with self.e.begin() as c:
            c.execute(update(reports).where(reports.c.target_type == target_type, reports.c.target_id == target_id,
                                            reports.c.status == "open")
                      .values(status=status, resolved_by=by, resolved_at=now()))

    def ban(self, key: str, until, reason: str, by: str) -> None:
        with self.e.begin() as c:
            if c.execute(select(bans.c.key).where(bans.c.key == key)).first():
                c.execute(update(bans).where(bans.c.key == key).values(until=until, reason=reason, created_by=by))
            else:
                c.execute(insert(bans).values(key=key, until=until, reason=reason, created_by=by, created_at=now()))

    def is_banned(self, keys: list[str], at: datetime) -> bool:
        with self.e.connect() as c:
            return c.execute(select(bans.c.key).where(bans.c.key.in_(keys),
                                                      or_(bans.c.until.is_(None), bans.c.until > at))).first() is not None

    def activity_by_gallery(self, since: datetime) -> dict[str, int]:
        """posts + comments per gallery since ``since`` (the market's "volume")."""
        with self.e.connect() as c:
            p = c.execute(select(posts.c.gallery_id, func.count()).where(posts.c.created_at >= since,
                          posts.c.deleted_at.is_(None)).group_by(posts.c.gallery_id)).all()
            cm = c.execute(select(posts.c.gallery_id, func.count()).select_from(comments.join(posts, comments.c.post_id == posts.c.id))
                           .where(comments.c.created_at >= since, comments.c.deleted_at.is_(None))
                           .group_by(posts.c.gallery_id)).all()
        out: dict[str, int] = {}
        for gid, n in list(p) + list(cm):
            out[gid] = out.get(gid, 0) + n
        return out

    def galleries_by_ids(self, ids) -> dict[str, dict]:
        if not ids:
            return {}
        with self.e.connect() as c:
            return {r["id"]: dict(r) for r in c.execute(select(galleries).where(galleries.c.id.in_(list(ids)))).mappings()}
