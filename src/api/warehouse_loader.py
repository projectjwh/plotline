"""Warehouse provisioning: make the DuckDB file available before the API opens it.

The heavy pipeline (crawl → pipeline → warehouse) runs offline and publishes
``plotline.duckdb`` to object storage. On boot the API uses a local file if one
is present (baked image / mounted volume), otherwise it downloads the published
artifact from ``PLOTLINE_WAREHOUSE_URL``. This keeps the read API tiny and lets
data refresh without rebuilding or redeploying the image.
"""
from __future__ import annotations

import logging
import os
import tempfile
import urllib.request

from src.api.config import cfg

log = logging.getLogger("plotline.api")


def ensure_warehouse() -> str:
    """Return a path to a readable warehouse file, downloading it if necessary."""
    path = cfg.WAREHOUSE_PATH
    if os.path.exists(path) and os.path.getsize(path) > 0:
        log.info("warehouse: using local file %s", path)
        return path
    if not cfg.WAREHOUSE_URL:
        raise FileNotFoundError(
            f"No warehouse at {path} and PLOTLINE_WAREHOUSE_URL is unset — "
            "run `python -m src.db.warehouse` or set the artifact URL.")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = tempfile.NamedTemporaryFile(delete=False, dir=os.path.dirname(path) or ".",
                                      suffix=".part").name
    log.info("warehouse: downloading %s", cfg.WAREHOUSE_URL)
    urllib.request.urlretrieve(cfg.WAREHOUSE_URL, tmp)  # noqa: S310 — trusted, operator-set URL
    os.replace(tmp, path)  # atomic swap so the API never opens a half-written file
    log.info("warehouse: downloaded %.1f MB → %s", os.path.getsize(path) / 1e6, path)
    return path
