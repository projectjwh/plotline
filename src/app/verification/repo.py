from __future__ import annotations

import json

from sqlalchemy import Column, DateTime, ForeignKey, String, Table, Text, insert, select, update
from sqlalchemy.engine import Engine

from src.app.core.db import metadata, new_id, now

claims = Table(
    "claims", metadata,
    Column("id", String(32), primary_key=True),
    Column("user_id", String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("claim_type", String(20), nullable=False),     # author | publisher | title | investor_entity
    Column("entity_ref", String(255), nullable=False),    # comic_id | author name | publisher name | firm name
    Column("entity_name", String(255), nullable=False),
    Column("role", String(120)),
    Column("status", String(10), nullable=False),         # pending | approved | rejected | revoked
    Column("doc_keys", Text, nullable=False),             # JSON list of storage keys
    Column("reviewer_id", String(32)),
    Column("review_note", String(1000)),
    Column("created_at", DateTime, nullable=False),
    Column("reviewed_at", DateTime),
)


def _decode(r) -> dict:
    d = dict(r)
    d["doc_keys"] = json.loads(d["doc_keys"])
    return d


class ClaimRepo:
    def __init__(self, engine: Engine):
        self.e = engine

    def create(self, **row) -> dict:
        row = {"id": new_id(), "status": "pending", "created_at": now(), **row, "doc_keys": json.dumps(row["doc_keys"])}
        with self.e.begin() as c:
            c.execute(insert(claims).values(**row))
        return _decode(row)

    def get(self, claim_id: str) -> dict | None:
        with self.e.connect() as c:
            r = c.execute(select(claims).where(claims.c.id == claim_id)).mappings().first()
        return _decode(r) if r else None

    def for_user(self, user_id: str, status: str | None = None) -> list[dict]:
        q = select(claims).where(claims.c.user_id == user_id)
        if status:
            q = q.where(claims.c.status == status)
        with self.e.connect() as c:
            return [_decode(r) for r in c.execute(q.order_by(claims.c.created_at.desc())).mappings()]

    def by_status(self, status: str) -> list[dict]:
        with self.e.connect() as c:
            return [_decode(r) for r in c.execute(select(claims).where(claims.c.status == status)
                                                  .order_by(claims.c.created_at)).mappings()]

    def pending_duplicate(self, user_id, claim_type, entity_ref) -> bool:
        with self.e.connect() as c:
            return c.execute(select(claims.c.id).where(claims.c.user_id == user_id, claims.c.claim_type == claim_type,
                                                       claims.c.entity_ref == entity_ref,
                                                       claims.c.status.in_(["pending", "approved"]))).first() is not None

    def set_status(self, claim_id: str, status: str, reviewer_id: str, note: str | None) -> None:
        with self.e.begin() as c:
            c.execute(update(claims).where(claims.c.id == claim_id)
                      .values(status=status, reviewer_id=reviewer_id, review_note=note, reviewed_at=now()))
