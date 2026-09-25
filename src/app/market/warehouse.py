"""Read-only adapter over the analytics warehouse (``data/plotline.duckdb``, built by
``src/db/warehouse.py``). This is the only code that talks to DuckDB, so another store
could replace it later.
"""
from __future__ import annotations

import logging
import os
import tempfile
import threading
import urllib.request

import duckdb
import polars as pl

from src.app.core.errors import Unavailable

log = logging.getLogger("plotline.app")


def ensure_warehouse(path: str, url: str | None) -> bool:
    """Make the warehouse file exist before the app reads it (ported from src/api/warehouse_loader.py).

    A local file (baked image, volume, dev build) wins. Otherwise the published artifact is
    downloaded from ``url`` to a temporary file and swapped in atomically. Returns whether a
    file is present afterwards; a failed download is logged and ``/ready`` reports it.
    """
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return True
    if not url:
        log.warning("warehouse: no file at %s and PLOTLINE_WAREHOUSE_URL is unset", path)
        return False
    if not url.startswith("https://"):
        raise RuntimeError("PLOTLINE_WAREHOUSE_URL must be https")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = tempfile.NamedTemporaryFile(delete=False, dir=os.path.dirname(path) or ".", suffix=".part").name
    try:
        urllib.request.urlretrieve(url, tmp)  # noqa: S310 — operator-set https URL
        os.replace(tmp, path)
        log.info("warehouse: downloaded %.1f MB", os.path.getsize(path) / 1e6)
        return True
    except Exception:
        log.exception("warehouse: download failed")
        if os.path.exists(tmp):
            os.remove(tmp)
        return False


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

    def ready(self) -> bool:
        try:
            return "fact_title" in self.tables()
        except Exception:
            return False

    def tables(self) -> set[str]:
        return {r[0] for r in self._cursor().execute(
            "SELECT table_name FROM information_schema.tables").fetchall()}

    def columns(self, table: str) -> set[str]:
        return {r[0] for r in self._cursor().execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = ?", [table]).fetchall()}

    def frame(self, sql: str, params: list | None = None) -> pl.DataFrame:
        return self._cursor().execute(sql, params or []).pl()
