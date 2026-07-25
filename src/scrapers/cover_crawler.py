"""Cover-art collector.

Downloads the real cover image for each title (URL captured in Silver), stores a
normalized thumbnail in ``data/covers/``, and can emit a base64 map for embedding
in the explorer. These covers also feed the painting-style analysis
(``src/models/art_style.py``).

Run:
  python -m src.scrapers.cover_crawler --limit 120     # top titles by PlotScore
  python -m src.scrapers.cover_crawler --all
"""
from __future__ import annotations

import argparse
import base64
import glob
import io
import json
import os
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import polars as pl
import requests
from PIL import Image

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
SILVER = os.path.join(_ROOT, "data", "silver", "comics")
COVERS = os.path.join(_ROOT, "data", "covers")
THUMB_W = 150  # stored thumbnail width (keeps aspect)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"


def safe_id(cid: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in cid)


def _load_targets(limit=None, only_missing=True) -> list[dict]:
    files = glob.glob(os.path.join(SILVER, "**", "*.parquet"), recursive=True)
    if not files:
        return []
    df = pl.scan_parquet(files, hive_partitioning=False).drop("tags").collect()
    from src.models.plotscore import score_universe
    u = score_universe()  # comic_id + plotscore + attrs
    covers = (df.sort("scraped_at").group_by("comic_id")
                .agg(pl.col("cover_url").drop_nulls().first().alias("cover")))
    u = u.join(covers, on="comic_id", how="left").filter(pl.col("cover").is_not_null())
    u = u.sort("plotscore", descending=True, nulls_last=True)
    tgts = u.select(["comic_id", "title", "source", "cover"]).to_dicts()
    if only_missing:
        tgts = [t for t in tgts if not os.path.exists(os.path.join(COVERS, safe_id(t["comic_id"]) + ".jpg"))]
    return tgts[:limit] if limit else tgts


def _fetch_thumb(url: str) -> bytes | None:
    for attempt in range(3):
        try:
            r = requests.get(url, timeout=15, headers={"User-Agent": UA, "Referer": url})
            if r.status_code == 200 and len(r.content) > 800:
                im = Image.open(io.BytesIO(r.content)).convert("RGB")
                w, h = im.size
                im = im.resize((THUMB_W, max(1, round(h * THUMB_W / w))))
                buf = io.BytesIO(); im.save(buf, "JPEG", quality=78)
                return buf.getvalue()
            if r.status_code in (429, 503):
                time.sleep(2 ** attempt); continue
            return None
        except Exception:
            time.sleep(1 + attempt)
    return None


def run(limit=None, only_missing=True, concurrency=6) -> dict:
    tgts = _load_targets(limit, only_missing)
    if not tgts:
        print("No cover targets (need Silver titles with cover_url).")
        return {"ok": 0, "fail": 0}
    os.makedirs(COVERS, exist_ok=True)
    print(f"Downloading {len(tgts)} covers (concurrency={concurrency})...")
    stats = {"ok": 0, "fail": 0}

    def work(t):
        data = _fetch_thumb(t["cover"])
        if data:
            with open(os.path.join(COVERS, safe_id(t["comic_id"]) + ".jpg"), "wb") as f:
                f.write(data)
            return True
        return False

    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        futs = [ex.submit(work, t) for t in tgts]
        for n, fut in enumerate(as_completed(futs), 1):
            stats["ok" if fut.result() else "fail"] += 1
            if n % 40 == 0 or n == len(tgts):
                print(f"  {n}/{len(tgts)}  ok={stats['ok']} fail={stats['fail']}")
    print(f"Done. {stats['ok']} covers in {COVERS}")
    return stats


def build_cover_map(max_covers=140) -> dict:
    """Return {comic_id: 'data:image/jpeg;base64,...'} for the top downloaded covers,
    for embedding in the explorer artifact (production loads cover_url directly)."""
    from src.models.plotscore import score_universe
    u = score_universe().sort("plotscore", descending=True, nulls_last=True)
    out = {}
    for cid in u["comic_id"].to_list():
        p = os.path.join(COVERS, safe_id(cid) + ".jpg")
        if os.path.exists(p):
            try:  # re-encode small for a lean embed (covers render ≤152px; keep the file lean)
                im = Image.open(p).convert("RGB")
                w, h = im.size
                tw = 74
                im = im.resize((tw, max(1, round(h * tw / w))))
                buf = io.BytesIO(); im.save(buf, "JPEG", quality=60, optimize=True)
                out[cid] = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
            except Exception:
                continue
            if len(out) >= max_covers:
                break
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=120)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--concurrency", type=int, default=6)
    a = ap.parse_args()
    run(limit=None if a.all else a.limit, only_missing=not a.refresh, concurrency=a.concurrency)
