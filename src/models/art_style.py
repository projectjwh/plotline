"""Painting-style analysis — the visual/art-style layer.

Reads the downloaded cover thumbnails (``data/covers/``) and extracts, per title:
a dominant colour palette, brightness, saturation, colourfulness, contrast, and
warmth. Titles are then clustered into interpretable **style groups** (e.g.
"Dark & moody", "Bright & pastel", "Vivid & saturated"). This lets the product
analyse art style by genre, platform, author, and correlate style with
performance — a dimension no competitor structures.

Run:  python -m src.models.art_style
"""
from __future__ import annotations

import glob
import os
import sys

import numpy as np
import polars as pl
from PIL import Image
from sklearn.cluster import KMeans

from src.scrapers.cover_crawler import COVERS, safe_id

sys.stdout.reconfigure(encoding="utf-8")
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
GOLD = os.path.join(_ROOT, "data", "gold")
N_STYLES = 5


def _hex(c):
    return "#%02x%02x%02x" % (int(c[0]), int(c[1]), int(c[2]))


def features(path: str) -> dict | None:
    try:
        im = Image.open(path).convert("RGB").resize((72, 96))
    except Exception:
        return None
    px = np.asarray(im, dtype=float).reshape(-1, 3)
    # dominant palette (5 colours by cluster size)
    km = KMeans(n_clusters=5, n_init=4, random_state=0).fit(px)
    counts = np.bincount(km.labels_, minlength=5)
    order = np.argsort(-counts)
    palette = [_hex(km.cluster_centers_[i]) for i in order]
    R, G, B = px[:, 0], px[:, 1], px[:, 2]
    gray = 0.299 * R + 0.587 * G + 0.114 * B
    mx, mn = px.max(1), px.min(1)
    sat = np.where(mx > 0, (mx - mn) / mx, 0)
    rg, yb = R - G, 0.5 * (R + G) - B
    colorfulness = float(np.sqrt(rg.std() ** 2 + yb.std() ** 2) + 0.3 * np.sqrt(rg.mean() ** 2 + yb.mean() ** 2))
    return {
        "palette": palette,
        "brightness": round(float(gray.mean()) / 255, 3),
        "saturation": round(float(sat.mean()), 3),
        "colorfulness": round(colorfulness / 255, 3),
        "contrast": round(float(gray.std()) / 128, 3),
        "warmth": round(float((R.mean() - B.mean())) / 255, 3),
    }


def _name_cluster(c: dict) -> str:
    b, s, cf = c["brightness"], c["saturation"], c["colorfulness"]
    if b < 0.35:
        return "Dark & moody"
    if s > 0.55 and cf > 0.4:
        return "Vivid & saturated"
    if b > 0.68 and s < 0.4:
        return "Bright & pastel"
    if s < 0.3 and cf < 0.3:
        return "Muted / monochrome"
    return "Warm & soft" if c["warmth"] > 0.05 else "Cool & clean"


def run() -> None:
    paths = glob.glob(os.path.join(COVERS, "*.jpg"))
    if not paths:
        print("No covers found — run 'python -m src.scrapers.cover_crawler' first.")
        return
    rows = []
    for p in paths:
        f = features(p)
        if f:
            f["comic_id"] = os.path.splitext(os.path.basename(p))[0]  # safe_id form
            rows.append(f)
    print(f"Analysed {len(rows)} covers.")
    if not rows:
        return
    df = pl.DataFrame(rows)
    feat = df.select(["brightness", "saturation", "colorfulness", "contrast", "warmth"]).to_numpy()
    k = min(N_STYLES, len(rows))
    km = KMeans(n_clusters=k, n_init=6, random_state=0).fit(feat)
    df = df.with_columns(pl.Series("style_cluster", km.labels_))
    # name each cluster from its centroid
    names = {}
    for ci in range(k):
        cen = feat[km.labels_ == ci].mean(0)
        names[ci] = _name_cluster(dict(zip(["brightness", "saturation", "colorfulness", "contrast", "warmth"], cen)))
    df = df.with_columns(pl.col("style_cluster").replace_strict(names, default="Mixed").alias("style_name"))

    # map safe_id back to real comic_id via Silver
    sv = (pl.scan_parquet(glob.glob(os.path.join(_ROOT, "data", "silver", "comics", "**", "*.parquet"), recursive=True),
                          hive_partitioning=False).select("comic_id", "genre", "source").unique("comic_id").collect())
    sv = sv.with_columns(pl.col("comic_id").map_elements(safe_id, return_dtype=pl.Utf8).alias("_sid"))
    out = df.join(sv, left_on="comic_id", right_on="_sid", how="left").rename({"comic_id_right": "real_id"})

    os.makedirs(GOLD, exist_ok=True)
    out.write_parquet(os.path.join(GOLD, "art_style.parquet"))
    print("\nStyle group distribution:")
    print(out.group_by("style_name").len().sort("len", descending=True))
    print("\nAvg brightness / saturation by genre (top genres):")
    g = (out.filter(pl.col("genre").is_not_null())
            .group_by("genre").agg(pl.col("brightness").mean().round(2),
                                   pl.col("saturation").mean().round(2),
                                   pl.col("colorfulness").mean().round(2), pl.len())
            .filter(pl.col("len") >= 3).sort("saturation", descending=True))
    print(g)


if __name__ == "__main__":
    run()
