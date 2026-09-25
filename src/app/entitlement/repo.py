"""Plan grants. Billing stays off, so admins grant plans; a Stripe webhook can write the same rows later."""
from __future__ import annotations

from sqlalchemy import Column, DateTime, ForeignKey, PrimaryKeyConstraint, String, Table, delete, insert, select, update
from sqlalchemy.engine import Engine

from src.app.core.db import metadata, now

grants = Table(
    "plan_grants", metadata,
    Column("user_id", String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("plan", String(20), nullable=False),          # author | publisher | investor
    Column("status", String(12), nullable=False),        # active | canceled | waitlist
    Column("source", String(12), nullable=False),        # admin | stripe
    Column("granted_by", String(32)),
    Column("created_at", DateTime, nullable=False),
    PrimaryKeyConstraint("user_id", "plan"),
)


class GrantRepo:
    def __init__(self, engine: Engine):
        self.e = engine

    def upsert(self, user_id: str, plan: str, status: str, source: str, granted_by: str | None) -> None:
        with self.e.begin() as c:
            exists = c.execute(select(grants.c.plan).where(grants.c.user_id == user_id, grants.c.plan == plan)).first()
            if exists:
                c.execute(update(grants).where(grants.c.user_id == user_id, grants.c.plan == plan)
                          .values(status=status, source=source, granted_by=granted_by))
            else:
                c.execute(insert(grants).values(user_id=user_id, plan=plan, status=status, source=source,
                                                granted_by=granted_by, created_at=now()))

    def active_plans(self, user_id: str) -> set[str]:
        with self.e.connect() as c:
            rows = c.execute(select(grants.c.plan).where(grants.c.user_id == user_id, grants.c.status == "active"))
            return {r[0] for r in rows}

    def remove(self, user_id: str, plan: str) -> None:
        with self.e.begin() as c:
            c.execute(delete(grants).where(grants.c.user_id == user_id, grants.c.plan == plan))
