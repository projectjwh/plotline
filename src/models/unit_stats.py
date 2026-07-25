"""Content-structure statistics at every level.

Rolls the unit data (episodes / chapters / volumes) into statistics at the
levels the user asked for:

  unit      per-episode / per-chapter rows (fact_episode)
  title     content structure per IP — unit type & count, per-unit engagement,
            engagement decay across the series, chapters-per-volume for novels
  book      volume-level structure for novels (chapters per volume)
  segment   rollups by content_type · genre · platform (avg units, engagement)

Output → data/gold/unit_*.{parquet,csv}. Run: python -m src.models.unit_stats
"""
from __future__ import annotations

import glob
import os
import sys

import polars as pl

from src.models.episode_analytics import _episodes

sys.stdout.reconfigure(encoding="utf-8")
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
SILVER = os.path.join(_ROOT, "data", "silver", "comics")
GOLD = os.path.join(_ROOT, "data", "gold")


def _titles() -> pl.DataFrame:
    df = (pl.scan_parquet(glob.glob(os.path.join(SILVER, "**", "*.parquet"), recursive=True), hive_partitioning=False)
            .sort("scraped_at").group_by("comic_id")
            .agg([pl.col("source").last(), pl.col("title").last(), pl.col("genre").last(),
                  pl.col("author").last(), pl.col("content_type").last(),
                  pl.col("episode_count").max(), pl.col("chapter_count").max(),
                  pl.col("volume_count").max(), pl.col("views").max(), pl.col("likes").max()])
            .collect())
    # applicable unit per content type
    return df.with_columns([
        pl.coalesce("episode_count", "chapter_count", "volume_count").alias("units"),
        pl.when(pl.col("episode_count").is_not_null()).then(pl.lit("episode"))
          .when(pl.col("chapter_count").is_not_null()).then(pl.lit("chapter"))
          .when(pl.col("volume_count").is_not_null()).then(pl.lit("volume"))
          .otherwise(None).alias("unit_type"),
        pl.when((pl.col("chapter_count") > 0) & (pl.col("volume_count") > 0))
          .then((pl.col("chapter_count") / pl.col("volume_count")).round(1))
          .otherwise(None).alias("chapters_per_volume"),
    ])


def _episode_stats(ep: pl.DataFrame) -> pl.DataFrame:
    """Unit-level → title-level engagement, incl. engagement decay across the series."""
    rows = []
    for cid, sub in ep.filter(pl.col("episode_no").is_not_null()).group_by("comic_id"):
        s = sub.sort("episode_no")
        likes = s["likes"].to_list()
        n = len(likes)
        early = sum(likes[:n // 2]) / max(1, n // 2) if n >= 2 else likes[0]
        late = sum(likes[n // 2:]) / max(1, n - n // 2) if n >= 2 else likes[0]
        decay = round((early - late) / early * 100, 1) if early > 0 else None
        rows.append({"comic_id": cid[0] if isinstance(cid, tuple) else cid,
                     "ep_tracked": n,
                     "avg_ep_likes": round(s["likes"].mean()),
                     "median_ep_likes": int(s["likes"].median()),
                     "top_ep_likes": int(s["likes"].max()),
                     "engagement_decay_pct": decay})
    return pl.DataFrame(rows) if rows else pl.DataFrame({"comic_id": []})


def run() -> None:
    t = _titles()
    ep = _episodes()
    if ep is not None and not ep.is_empty():
        es = _episode_stats(ep)
        if not es.is_empty():
            t = t.join(es, on="comic_id", how="left")
    os.makedirs(GOLD, exist_ok=True)
    t.write_parquet(os.path.join(GOLD, "unit_title.parquet"))

    have = t.filter(pl.col("units").is_not_null())
    by_type = (have.group_by("content_type", "unit_type").agg(
        pl.len().alias("titles"), pl.col("units").mean().round(1).alias("avg_units"),
        pl.col("units").median().alias("median_units"), pl.col("units").max().alias("max_units"),
        pl.col("units").sum().alias("total_units")).sort("titles", descending=True))
    by_genre = (have.filter(pl.col("genre").is_not_null()).group_by("genre").agg(
        pl.len().alias("titles"), pl.col("units").mean().round(1).alias("avg_units"),
        pl.col("units").median().alias("median_units")).sort("avg_units", descending=True))
    by_plat = (have.group_by("source").agg(
        pl.len().alias("titles"), pl.col("unit_type").first(),
        pl.col("units").mean().round(1).alias("avg_units"),
        pl.col("units").max().alias("max_units"),
        pl.col("units").sum().alias("total_units")).sort("total_units", descending=True))
    for name, df in [("unit_by_type", by_type), ("unit_by_genre", by_genre), ("unit_by_platform", by_plat)]:
        df.write_csv(os.path.join(GOLD, f"{name}.csv"))

    print(f"Unit statistics — {have.height} titles with unit structure "
          f"({t['units'].sum():,.0f} total units)\n")
    print("BY CONTENT TYPE / UNIT:")
    print(by_type)
    print("\nBY PLATFORM:")
    print(by_plat)
    print("\nLongest series (top by units):")
    with pl.Config(fmt_str_lengths=30, tbl_rows=6):
        print(have.sort("units", descending=True).select(["title", "source", "unit_type", "units"]).head(6))
    dv = have.filter(pl.col("chapters_per_volume").is_not_null())
    if not dv.is_empty():
        print(f"\nNovels with volume structure: {dv.height} · avg {dv['chapters_per_volume'].mean():.1f} chapters/volume")


if __name__ == "__main__":
    run()
