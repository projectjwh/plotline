from __future__ import annotations

from sqlalchemy import Boolean, Column, DateTime, String, Table, insert, select, update
from sqlalchemy.engine import Engine

from src.app.core.db import metadata, new_id, now

users = Table(
    "users", metadata,
    Column("id", String(32), primary_key=True),
    Column("email", String(320), nullable=False, unique=True),
    Column("handle", String(40), nullable=False, unique=True),
    Column("password_hash", String(255), nullable=False),
    Column("is_admin", Boolean, nullable=False, default=False),
    Column("created_at", DateTime, nullable=False),
)


class UserRepo:
    def __init__(self, engine: Engine):
        self.e = engine

    def create(self, email: str, handle: str, password_hash: str, is_admin: bool) -> dict:
        row = {"id": new_id(), "email": email, "handle": handle, "password_hash": password_hash,
               "is_admin": is_admin, "created_at": now()}
        with self.e.begin() as c:
            c.execute(insert(users).values(**row))
        return row

    def by_email(self, email: str) -> dict | None:
        with self.e.connect() as c:
            r = c.execute(select(users).where(users.c.email == email)).mappings().first()
        return dict(r) if r else None

    def by_handle(self, handle: str) -> dict | None:
        with self.e.connect() as c:
            r = c.execute(select(users).where(users.c.handle == handle)).mappings().first()
        return dict(r) if r else None

    def by_id(self, user_id: str) -> dict | None:
        with self.e.connect() as c:
            r = c.execute(select(users).where(users.c.id == user_id)).mappings().first()
        return dict(r) if r else None

    def set_admin(self, user_id: str, is_admin: bool) -> None:
        with self.e.begin() as c:
            c.execute(update(users).where(users.c.id == user_id).values(is_admin=is_admin))
