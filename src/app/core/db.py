"""App-state database: SQLAlchemy Core, SQLite for dev/tests and Postgres for prod.

Each module declares its tables on the shared ``metadata`` in its own ``repo.py``.
Only that repo reads or writes those tables.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import MetaData, create_engine, event
from sqlalchemy.engine import Engine

metadata = MetaData()


def now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def new_id() -> str:
    return uuid.uuid4().hex


def make_engine(url: str) -> Engine:
    if url.startswith("sqlite"):
        path = url.split("///", 1)[-1]
        if path and path != ":memory:":
            import os
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        eng = create_engine(url, connect_args={"check_same_thread": False}, future=True)

        @event.listens_for(eng, "connect")
        def _fk(dbapi_con, _):  # enforce FKs on SQLite
            dbapi_con.execute("PRAGMA foreign_keys=ON")
        return eng
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return create_engine(url, pool_pre_ping=True, future=True)


def create_all(engine: Engine) -> None:
    # import every repo so its tables register on `metadata`
    from src.app.community import repo as _c  # noqa: F401
    from src.app.entitlement import repo as _e  # noqa: F401
    from src.app.fan import repo as _f  # noqa: F401
    from src.app.identity import repo as _i  # noqa: F401
    from src.app.verification import repo as _v  # noqa: F401
    metadata.create_all(engine)
