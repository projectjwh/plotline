"""Episode-level analytics — the granular per-episode / per-week / per-author view.

Turns the per-episode rows (``data/silver/episodes/``) into the fine-grained
numbers: per-episode likes, release cadence (episodes/week), engagement trend
across a series, and per-author rollups. Output → ``data/gold/episode_kpis.*``.

Run:  python -m src.models.episode_analytics
"""
from __future__ import annotations

import glob
import os
import sys
from datetime import datetime

import polars as pl

sys.stdout.reconfigure(encoding="utf-8")
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
EPISODES = os.path.join(_ROOT, "data", "silver", "episodes", "episodes.parquet")
SILVER = os.path.join(_ROOT, "data", "silver", "comics")
GOLD = os.path.join(_ROOT, "data", "gold")


def _parse_date(s):
    if not s:
        return None
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%Y-%m-%d", "%b. %d, %Y"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _episodes() -> pl.DataFrame | None:
    if not os.path.exists(EPISODES):
        return None
    return pl.read_parquet(EPISODES).with_columns(
        pl.col("upload_date").map_elements(_parse_date, return_dtype=pl.Date).alias("date"))


def per_title(ep: pl.DataFrame) -> pl.DataFrame:
    per = ep.group_by("comic_id").agg([
        pl.col("episode_no").max().alias("episodes"),
        pl.len().alias("episodes_sampled"),
        pl.col("likes").mean().round().alias("avg_ep_likes"),
        pl.col("likes").median().alias("median_ep_likes"),
        pl.col("likes").max().alias("top_ep_likes"),
        pl.col("date").min().alias("first_seen"),
        pl.col("date").max().alias("last_seen"),
    ]).with_columns(
        (pl.col("last_seen") - pl.col("first_seen")).dt.total_days().alias("span_days"))
    return per.with_columns(
        pl.when((pl.col("span_days") > 0) & (pl.col("episodes_sampled") > 1))
          .then((pl.col("episodes_sampled") - 1) / (pl.col("span_days") / 7.0))
          .otherwise(None).round(2).alias("episodes_per_week"))


def per_author(ep: pl.DataFrame) -> pl.DataFrame:
    a = (pl.scan_parquet(glob.glob(os.path.join(SILVER, "**", "*.parquet"), recursive=True), hive_partitioning=False)
           .select("comic_id", "author").unique("comic_id").collect())
    j = ep.join(a, on="comic_id", how="left").filter(pl.col("author").is_not_null())
    return j.group_by("author").agg([
        pl.col("comic_id").n_unique().alias("titles"),
        pl.len().alias("episodes_tracked"),
        pl.col("likes").mean().round().alias("avg_ep_likes"),
        pl.col("likes").sum().alias("total_ep_likes"),
    ]).sort("total_ep_likes", descending=True)


def series_map(ep: pl.DataFrame, limit=200) -> dict:
    """Per-title episode series [[episode_no, likes], ...] for the top titles, for the UI."""
    top = (ep.filter(pl.col("episode_no").is_not_null())
             .group_by("comic_id").agg(pl.col("likes").sum().alias("_s"))
             .sort("_s", descending=True).head(limit)["comic_id"].to_list())
    out = {}
    for cid in top:
        rows = (ep.filter((pl.col("comic_id") == cid) & pl.col("episode_no").is_not_null())
                  .sort("episode_no").select("episode_no", "likes").rows())
        out[cid] = [[int(n), int(k)] for n, k in rows]
    return out


def run() -> None:
    ep = _episodes()
    if ep is None or ep.is_empty():
        print("No episode data — run the detail crawl (episode lists live on detail pages).")
        return
    os.makedirs(GOLD, exist_ok=True)
    pt, pa = per_title(ep), per_author(ep)
    pt.write_parquet(os.path.join(GOLD, "episode_kpis.parquet"))
    pa.write_csv(os.path.join(GOLD, "episode_author_kpis.csv"))
    weekly = (ep.filter(pl.col("date").is_not_null())
                .with_columns(pl.col("date").dt.truncate("1w").alias("week"))
                .group_by("week").agg(pl.len().alias("releases"), pl.col("likes").mean().round().alias("avg_likes"))
                .sort("week"))
    weekly.write_csv(os.path.join(GOLD, "episode_weekly.csv"))

    print(f"Episode analytics: {ep.height} episode rows · {ep['comic_id'].n_unique()} titles\n")
    print("Per-title (top by avg episode likes):")
    with pl.Config(tbl_rows=6, fmt_str_lengths=30):
        print(pt.sort("avg_ep_likes", descending=True)
                .select(["comic_id", "episodes", "avg_ep_likes", "top_ep_likes", "episodes_per_week"]).head(6))
    print("\nPer-author (top by total episode likes):")
    with pl.Config(tbl_rows=6, fmt_str_lengths=24):
        print(pa.head(6))
    print("\nRecent weekly release cadence:")
    print(weekly.tail(5))


if __name__ == "__main__":
    run()
