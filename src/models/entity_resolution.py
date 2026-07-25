"""Entity resolution (L1) — unify platform-siloed titles into canonical IP.

The same story can appear as an EN Webtoon, its Korean original, a Ridibooks
novel, and a Tapas mirror. Keyed by ``{platform}:{id}`` those are four rows;
to an investor they are one IP with one cross-platform reach. This module
normalizes titles into a canonical key, clusters variants into a canonical IP
entity, and rolls metrics up to the IP — the backbone every downstream signal
needs. Authors are resolved the same way.

Deterministic + free (no fuzzy-match service): normalize aggressively, cluster
on the normalized key, keep the longest real title as canonical.

Run:  python -m src.models.entity_resolution
"""
from __future__ import annotations

import os
import re
import sys
from datetime import datetime

import polars as pl

from src.models.plotscore import score_universe

sys.stdout.reconfigure(encoding="utf-8")
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
GOLD = os.path.join(_ROOT, "data", "gold")

_BRACKET = re.compile(r"\(.*?\)|\[.*?\]|\{.*?\}")
_VOL = re.compile(r"\b(season|vol|volume|part|book|chapter|ch|s)\s*\.?\s*\d+\b", re.IGNORECASE)
_STOP = re.compile(r"\b(the|a|an|official|uncensored|complete|completed|webtoon|comic|novel)\b", re.IGNORECASE)
_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)


def normalize_title(t: str) -> str:
    """Aggressively normalize a title into a clustering key."""
    if not t:
        return ""
    t = t.lower()
    t = _BRACKET.sub(" ", t)
    t = _VOL.sub(" ", t)
    t = _PUNCT.sub(" ", t)
    t = _STOP.sub(" ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def normalize_author(a: str | None) -> str:
    if not a:
        return ""
    a = a.lower().split("/")[0].split(",")[0]        # first credited creator
    return re.sub(r"[^\w\s]", "", a).strip()


def resolve() -> tuple[pl.DataFrame, pl.DataFrame] | tuple[None, None]:
    u = score_universe()
    if u is None:
        return None, None
    u = u.with_columns([
        pl.col("title").map_elements(normalize_title, return_dtype=pl.Utf8).alias("_ipkey"),
        pl.col("author").map_elements(normalize_author, return_dtype=pl.Utf8).alias("_akey"),
    ])
    # A title-less or too-short key is its own IP (never merge on empty/1-char keys).
    u = u.with_columns(
        pl.when(pl.col("_ipkey").str.len_chars() >= 2)
          .then(pl.col("_ipkey"))
          .otherwise(pl.col("comic_id")).alias("_ipkey")
    )

    # Canonical IP entities — roll metrics up across platform variants.
    ip = u.group_by("_ipkey").agg([
        pl.col("title").sort_by(pl.col("title").str.len_chars()).last().alias("canonical_title"),
        pl.col("source").n_unique().alias("n_platforms"),
        pl.col("source").unique().alias("platforms"),
        pl.len().alias("n_variants"),
        pl.col("views").sum().alias("ip_views"),
        pl.col("subscribers").sum().alias("ip_subscribers"),
        pl.col("likes").sum().alias("ip_likes"),
        pl.col("plotscore").max().alias("ip_plotscore"),
        pl.col("genre").drop_nulls().first().alias("genre"),
        pl.col("author").drop_nulls().first().alias("author"),
        pl.col("content_type").first().alias("content_type"),
    ]).with_columns(
        ("ip:" + pl.col("_ipkey").hash().cast(pl.Utf8).str.slice(0, 12)).alias("ip_id")
    ).sort("ip_plotscore", descending=True)

    # Author entities.
    au = u.filter(pl.col("_akey").str.len_chars() >= 2).group_by("_akey").agg([
        pl.col("author").first().alias("author"),
        pl.col("comic_id").n_unique().alias("n_titles"),
        pl.col("source").n_unique().alias("n_platforms"),
        pl.col("views").sum().alias("total_views"),
        pl.col("plotscore").max().alias("best_plotscore"),
        pl.col("plotscore").mean().round(1).alias("avg_plotscore"),
    ]).sort("n_titles", descending=True)

    return ip, au


def run() -> None:
    ip, au = resolve()
    if ip is None:
        print("No Silver data found.")
        return
    os.makedirs(GOLD, exist_ok=True)
    ip.drop("platforms").write_parquet(os.path.join(GOLD, "entities_ip.parquet"))
    au.write_parquet(os.path.join(GOLD, "entities_author.parquet"))

    multi = ip.filter(pl.col("n_platforms") > 1)
    dupes = ip.filter(pl.col("n_variants") > 1)
    print(f"Resolved {ip.height} canonical IP entities from {ip['n_variants'].sum()} platform rows.")
    print(f"  {dupes.height} IPs have >1 variant (merged duplicates)")
    print(f"  {multi.height} IPs span >1 platform (true cross-platform reach)\n")
    print(f"Resolved {au.height} author entities.\n")
    if dupes.height:
        print("Example merged IPs (variants → one entity):")
        for r in dupes.head(6).select(["canonical_title", "n_variants", "n_platforms", "ip_views"]).iter_rows(named=True):
            print(f"   {r['canonical_title'][:40]:40} variants={r['n_variants']} platforms={r['n_platforms']} reach={r['ip_views']:,}")
    print("\nTop authors by catalog:")
    for r in au.head(6).select(["author", "n_titles", "best_plotscore"]).iter_rows(named=True):
        print(f"   {str(r['author'])[:28]:28} titles={r['n_titles']} best_score={r['best_plotscore']}")


if __name__ == "__main__":
    run()
