from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Table, func, insert, select, update
from sqlalchemy.engine import Engine

from src.app.core.db import metadata, new_id, now

users = Table(
    "users", metadata,
    Column("id", String(32), primary_key=True),
    Column("email", String(320), nullable=False, unique=True),
    Column("handle", String(40), nullable=False, unique=True),
    Column("password_hash", String(255), nullable=False),
    Column("is_admin", Boolean, nullable=False, default=False),
    Column("email_verified_at", DateTime),                       # null = unverified
    Column("token_version", Integer, nullable=False, default=0),  # bumped on password reset
    Column("locale", String(5), nullable=False, default="en"),   # en | ko
    Column("created_at", DateTime, nullable=False),
)

# Login/sign-up attempts for throttling. Stored in the DB, not memory, because
# API machines scale to zero and restart.
auth_attempts = Table(
    "auth_attempts", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("key", String(120), nullable=False, index=True),   # "email:<addr>" | "ip:<hash>"
    Column("kind", String(12), nullable=False),               # login | signup | forgot
    Column("ok", Boolean, nullable=False),
    Column("at", DateTime, nullable=False, index=True),
)


def _one(c, stmt):
    r = c.execute(stmt).mappings().first()
    return dict(r) if r else None


class UserRepo:
    def __init__(self, engine: Engine):
        self.e = engine

    def create(self, email: str, handle: str, password_hash: str, is_admin: bool, locale: str = "en") -> dict:
        row = {"id": new_id(), "email": email, "handle": handle, "password_hash": password_hash,
               "is_admin": is_admin, "email_verified_at": None, "token_version": 0, "locale": locale,
               "created_at": now()}
        with self.e.begin() as c:
            c.execute(insert(users).values(**row))
        return row

    def by_email(self, email: str) -> dict | None:
        with self.e.connect() as c:
            return _one(c, select(users).where(users.c.email == email))

    def by_handle(self, handle: str) -> dict | None:
        with self.e.connect() as c:
            return _one(c, select(users).where(users.c.handle == handle))

    def by_id(self, user_id: str) -> dict | None:
        with self.e.connect() as c:
            return _one(c, select(users).where(users.c.id == user_id))

    def patch(self, user_id: str, **values) -> None:
        with self.e.begin() as c:
            c.execute(update(users).where(users.c.id == user_id).values(**values))

    def set_admin(self, user_id: str, is_admin: bool) -> None:
        self.patch(user_id, is_admin=is_admin)

    def set_password(self, user_id: str, password_hash: str) -> None:
        with self.e.begin() as c:
            c.execute(update(users).where(users.c.id == user_id)
                      .values(password_hash=password_hash, token_version=users.c.token_version + 1))

    # throttling
    def record_attempt(self, keys: list[str], kind: str, ok: bool) -> None:
        t = now()
        with self.e.begin() as c:
            c.execute(insert(auth_attempts), [{"key": k, "kind": kind, "ok": ok, "at": t} for k in keys])

    def failures_since(self, key: str, kind: str, since: datetime) -> int:
        with self.e.connect() as c:
            return c.execute(select(func.count()).select_from(auth_attempts).where(
                auth_attempts.c.key == key, auth_attempts.c.kind == kind,
                auth_attempts.c.ok.is_(False), auth_attempts.c.at >= since)).scalar_one()
