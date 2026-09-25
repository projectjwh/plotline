"""Read-only adapter over the analytics warehouse (``data/plotline.duckdb``, built by
``src/db/warehouse.py``). This is the only code that talks to DuckDB, so another store
could replace it later.
"""
from __future__ import annotations

import os
import threading

import duckdb
import polars as pl

from src.app.core.errors import Unavailable


class Warehouse:
    def __init__(self, path: str):
        self.path = path
        self._con = None
        self._mtime = None
        self._lock = threading.Lock()

    def version(self) -> float:
        try:
            return os.path.getmtime(self.path)
        except OSError:
            raise Unavailable("analytics warehouse not built yet (run python -m src.db.warehouse)") from None

    def _cursor(self):
        with self._lock:
            v = self.version()
            if self._con is None or v != self._mtime:  # reopen after a daily rebuild
                if self._con is not None:
                    self._con.close()
                self._con = duckdb.connect(self.path, read_only=True)
                self._mtime = v
            return self._con.cursor()

    def tables(self) -> set[str]:
        return {r[0] for r in self._cursor().execute(
            "SELECT table_name FROM information_schema.tables").fetchall()}

    def columns(self, table: str) -> set[str]:
        return {r[0] for r in self._cursor().execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = ?", [table]).fetchall()}

    def frame(self, sql: str, params: list | None = None) -> pl.DataFrame:
        return self._cursor().execute(sql, params or []).pl()
