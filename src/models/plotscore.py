"""PlotScore — the composite rank that headlines Plotline.

A transparent 0–100 score (the Crunchbase-Rank analog) blending the signals we
have into one sortable number per title. Unlike Crunchbase Rank it is fully
open: five percentile-normalized components with published weights, so a buyer
can see *why* a title scores where it does.

    PlotScore = 100 × Σ  wᵢ · percentile(componentᵢ)

    reach 0.30 · momentum 0.25 · engagement 0.20 · monetization 0.15 · quality 0.10

Percentiles are taken across the whole universe, so the score is relative — a
title's rank among its peers, not an absolute. Components a title lacks fall to
a low percentile (we reward what we can measure). Weights live in ``WEIGHTS``
and are meant to be tuned per customer segment.

Run:  python -m src.models.plotscore
"""
from __future__ import annotations

import glob
import os
import sys
from datetime import datetime

import polars as pl

from src.models.earnings import estimate_row

sys.stdout.reconfigure(encoding="utf-8")

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
SILVER = os.path.join(_ROOT, "data", "silver", "comics")
GOLD = os.path.join(_ROOT, "data", "gold")

WEIGHTS = {"reach": 0.30, "momentum": 0.25, "engagement": 0.20,
           "monetization": 0.15, "quality": 0.10}
COMPONENTS = list(WEIGHTS)


def _universe() -> pl.DataFrame | None:
    files = glob.glob(os.path.join(SILVER, "**", "*.parquet"), recursive=True)
    if not files:
        return None
    df = pl.scan_parquet(files, hive_partitioning=False).drop("tags").collect().sort("scraped_at")
    # One row per title: latest attributes + peak metrics + rank history for momentum.
    return df.group_by("comic_id").agg([
        pl.col("source").last(), pl.col("title").last(),
        # attributes: keep the latest *non-null* value — a fresh detail-page
        # observation often lacks author/genre that the listing row carried, so
        # a plain .last() would blank them out (different date = separate row).
        pl.col("genre").drop_nulls().last().alias("genre"),
        pl.col("author").drop_nulls().last().alias("author"),
        pl.col("content_type").last(),
        pl.col("views").max(), pl.col("subscribers").max(), pl.col("likes").max(),
        pl.col("rating").max(),
        # rank lives only on listing rows; detail-page observations carry
        # rank=null. Drop nulls before first/last so an enrichment crawl's
        # rank-less detail row can't null-poison latest_rank (which otherwise
        # decorrelates rank from views entirely) — same guard as genre/author.
        pl.col("rank").min().alias("best_rank"),
        pl.col("rank").drop_nulls().last().alias("latest_rank"),
        pl.col("rank").drop_nulls().first().alias("first_rank"),
        pl.col("rank").drop_nulls().len().alias("n_rank_obs"),
        pl.len().alias("n_obs"),
    ])


def _raw_components(u: pl.DataFrame) -> pl.DataFrame:
    subs0 = pl.col("subscribers").fill_null(0)
    return u.with_columns([
        # reach: measured audience, falling back to a rank-based proxy
        pl.when(pl.col("views") > 0).then(pl.col("views").cast(pl.Float64))
          .when(subs0 > 0).then(subs0 * 8.0)
          .when(pl.col("likes") > 0).then(pl.col("likes") * 12.0)
          .when(pl.col("best_rank").is_not_null()).then(50000.0 / pl.col("best_rank"))
          .otherwise(0.0).alias("reach_raw"),
        # engagement intensity: like-through, else rating
        pl.when((pl.col("views") > 0) & (pl.col("likes") > 0))
          .then((pl.col("likes") / pl.col("views")).clip(0, 1))
          .when((pl.col("rating") > 0) & (pl.col("rating") <= 10)).then(pl.col("rating") / 10.0)
          .otherwise(0.0).alias("engagement_raw"),
        # momentum: rank improvement across observations (needs ≥2 *ranked*
        # observations — n_obs counts rank-less detail rows too and would fire
        # spuriously, yielding a 0 delta that looks like real stagnation).
        pl.when(pl.col("n_rank_obs") > 1)
          .then((pl.col("first_rank") - pl.col("latest_rank")).cast(pl.Float64))
          .otherwise(0.0).alias("momentum_raw"),
        # quality: sane rating only (some platforms mis-scale)
        pl.when((pl.col("rating") > 0) & (pl.col("rating") <= 10))
          .then(pl.col("rating")).otherwise(0.0).alias("quality_raw"),
    ])


def score_universe() -> pl.DataFrame | None:
    u = _universe()
    if u is None:
        return None
    u = _raw_components(u)
    # monetization via the earnings model
    u = u.with_columns(
        pl.struct(["source", "views", "subscribers", "likes"]).map_elements(
            lambda r: float(estimate_row(r["source"], r["views"], r["subscribers"], r["likes"])["est_monthly_usd"]),
            return_dtype=pl.Float64,
        ).alias("monetization_raw")
    )
    # No component may be null, or it poisons the weighted sum.
    u = u.with_columns([pl.col(f"{c}_raw").fill_null(0.0) for c in COMPONENTS])
    n = u.height
    # percentile-normalize each component and blend
    pct = [(pl.col(f"{c}_raw").rank(method="average") / n).alias(f"{c}_pct") for c in COMPONENTS]
    u = u.with_columns(pct)
    plot = sum(WEIGHTS[c] * pl.col(f"{c}_pct") for c in COMPONENTS) * 100
    return u.with_columns(plot.round(1).alias("plotscore")).sort("plotscore", descending=True)


def run() -> None:
    u = score_universe()
    if u is None:
        print("No Silver data found.")
        return
    os.makedirs(GOLD, exist_ok=True)
    out = os.path.join(GOLD, f"plotscore_{int(datetime.now().timestamp())}.csv")
    u.write_csv(out)
    print(f"PlotScore computed for {u.height} titles. Saved -> {out}")
    print(f"Weights: {WEIGHTS}\n\nTop 15 by PlotScore:")
    top = u.head(15).select([
        "title", "source", "plotscore",
        pl.col("reach_pct").round(2), pl.col("momentum_pct").round(2),
        pl.col("engagement_pct").round(2), pl.col("views")])
    with pl.Config(fmt_str_lengths=32, tbl_rows=15):
        print(top)


if __name__ == "__main__":
    run()
