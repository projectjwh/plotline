"""Market-structure KPIs computed from the daily title series (pure functions, Polars).

Definitions (documented in docs/product/product-spec.md §4.0):

* Reach index: a chain-linked index of total views, rebased to ``base``. Each day's
  change uses only titles observed on both days, so titles joining or leaving the
  crawl do not jump the index (the same idea as a divisor adjustment in equity
  indices). Views are cumulative counts, so this index measures **growth in reach**.
* Movers: change between each title's last two observations, in views (%) and
  rank (positive = rank improved).
* Breadth: advancing / declining / unchanged by rank change.
* New listings: titles whose first observation falls in the last ``days`` days.
"""
from __future__ import annotations

from datetime import timedelta

import polars as pl


def latest_per_day(daily: pl.DataFrame) -> pl.DataFrame:
    """Deduplicate on (comic_id, date), keeping the latest snapshot (project convention)."""
    sort_cols = ["comic_id", "date"] + (["scraped_at"] if "scraped_at" in daily.columns else [])
    return (daily.sort(sort_cols)
                 .group_by(["comic_id", "date"], maintain_order=True)
                 .agg(pl.col("views").drop_nulls().last(), pl.col("rank").drop_nulls().last()))


def chain_index(daily: pl.DataFrame, members: set[str] | None = None, base: float = 1000.0) -> list[dict]:
    d = latest_per_day(daily)
    if members is not None:
        d = d.filter(pl.col("comic_id").is_in(list(members)))
    if d.is_empty():
        return []
    dates = sorted(d["date"].unique().to_list())
    pos = {dt: i for i, dt in enumerate(dates)}
    d = d.with_columns(pl.col("date").replace_strict(pos, return_dtype=pl.Int64).alias("i"))
    prev = d.select("comic_id", (pl.col("i") + 1).alias("i"), pl.col("views").alias("pv"))
    pairs = (d.join(prev, on=["comic_id", "i"])
              .filter(pl.col("views").is_not_null() & pl.col("pv").is_not_null() & (pl.col("pv") > 0)))
    step = pairs.group_by("i").agg((pl.col("views").sum() / pl.col("pv").sum()).alias("r"), pl.len().alias("n"))
    ratio = {r["i"]: (r["r"], r["n"]) for r in step.iter_rows(named=True)}
    counts = {r["i"]: r["n"] for r in d.group_by("i").agg(pl.len().alias("n")).iter_rows(named=True)}
    out, v = [], base
    for i, dt in enumerate(dates):
        if i in ratio:
            v *= ratio[i][0]
        out.append({"date": dt.isoformat() if hasattr(dt, "isoformat") else str(dt),
                    "value": round(v, 2), "constituents": counts.get(i, 0)})
    return out


def index_summary(series: list[dict]) -> dict:
    if not series:
        return {"value": None, "change_pct": None, "points": 0}
    last = series[-1]["value"]
    prev = series[-2]["value"] if len(series) > 1 else None
    return {"value": last, "change_pct": round((last - prev) / prev * 100, 3) if prev else None,
            "points": len(series), "as_of": series[-1]["date"]}


def movers(daily: pl.DataFrame) -> pl.DataFrame:
    """One row per title: last two observations → views_change_pct, rank_change."""
    d = latest_per_day(daily).sort(["comic_id", "date"])
    last2 = d.group_by("comic_id", maintain_order=True).tail(2)
    agg = last2.group_by("comic_id").agg(
        pl.len().alias("n"),
        pl.col("views").first().alias("v0"), pl.col("views").last().alias("v1"),
        pl.col("rank").first().alias("r0"), pl.col("rank").last().alias("r1"),
        pl.col("date").last().alias("last_date"))
    return agg.with_columns(
        pl.when((pl.col("n") == 2) & (pl.col("v0") > 0) & pl.col("v1").is_not_null())
          .then(((pl.col("v1") - pl.col("v0")) / pl.col("v0") * 100).round(3)).otherwise(None).alias("views_change_pct"),
        pl.when((pl.col("n") == 2) & pl.col("r0").is_not_null() & pl.col("r1").is_not_null())
          .then(pl.col("r0") - pl.col("r1")).otherwise(None).alias("rank_change"),
    ).select("comic_id", "views_change_pct", "rank_change", "last_date")


def breadth(mv: pl.DataFrame) -> dict:
    rc = mv["rank_change"].drop_nulls()
    return {"advancing": int((rc > 0).sum()), "declining": int((rc < 0).sum()),
            "unchanged": int((rc == 0).sum()), "untracked": int(mv.height - rc.len())}


def first_seen(daily: pl.DataFrame) -> pl.DataFrame:
    return daily.group_by("comic_id").agg(pl.col("date").min().alias("first_seen"))


def new_listings(daily: pl.DataFrame, days: int) -> pl.DataFrame:
    fs = first_seen(daily)
    if fs.is_empty():
        return fs
    max_date = daily["date"].max()
    start = daily["date"].min()
    cutoff = max_date - timedelta(days=days)
    # a title first seen on the very first crawl date is not "new"; the crawl just started
    return (fs.filter((pl.col("first_seen") > cutoff) & (pl.col("first_seen") > start))
              .with_columns((pl.lit(max_date) - pl.col("first_seen")).dt.total_days().alias("listed_days_ago"))
              .sort("first_seen", descending=True))
