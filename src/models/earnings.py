"""Estimated per-title revenue — a MODEL, not a scraped figure.

No platform publishes creator earnings, so this cannot be scraped from anywhere.
Instead we estimate monthly revenue the way SocialBlade estimates YouTube income:
engagement metrics x transparent, per-platform monetization assumptions, reported
as a wide low/mid/high band. Treat every number here as an order-of-magnitude
estimate, not a fact. All assumptions live in ``PARAMS`` and are meant to be tuned.

Model (per title, per month):

    revenue ≈ ad/unlock component  +  subscription component
            = (total_views * monthly_view_frac / 1000) * rpm
            + subscribers * sub_pay_rate * sub_arpu

- ``total_views`` is cumulative, so ``monthly_view_frac`` converts it to an
  approximate *monthly* active-read volume.
- ``rpm`` = revenue per 1,000 monthly reads (ads + per-episode unlocks blended).
- ``sub_pay_rate`` = share of subscribers who pay in a month; ``sub_arpu`` = their
  average monthly spend (USD).

Run:  python -m src.models.earnings
"""
from __future__ import annotations

import glob
import os
import sys
from datetime import datetime

import polars as pl

sys.stdout.reconfigure(encoding="utf-8")

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
SILVER = os.path.join(_ROOT, "data", "silver", "comics")
GOLD = os.path.join(_ROOT, "data", "gold")

# Per-platform monetization assumptions (documented defaults — tune freely).
#   rpm               USD per 1,000 monthly reads (ads + unlocks blended)
#   monthly_view_frac cumulative views -> monthly active reads
#   sub_pay_rate      fraction of subscribers paying per month
#   sub_arpu          monthly USD spend of a paying subscriber
PARAMS: dict[str, dict] = {
    "webtoon_global": dict(rpm=0.60, monthly_view_frac=0.030, sub_pay_rate=0.020, sub_arpu=1.80),
    "tapas_io":       dict(rpm=0.45, monthly_view_frac=0.040, sub_pay_rate=0.030, sub_arpu=2.20),
    "mangaplus":      dict(rpm=0.35, monthly_view_frac=0.120, sub_pay_rate=0.000, sub_arpu=0.00),
    "wattpad":        dict(rpm=0.15, monthly_view_frac=0.050, sub_pay_rate=0.000, sub_arpu=0.00),
    "webcomics_app":  dict(rpm=0.00, monthly_view_frac=0.000, sub_pay_rate=0.050, sub_arpu=3.00),
    "globalcomix":    dict(rpm=0.00, monthly_view_frac=0.000, sub_pay_rate=0.040, sub_arpu=4.00),
}
DEFAULT = dict(rpm=0.30, monthly_view_frac=0.030, sub_pay_rate=0.020, sub_arpu=1.50)

# Uncertainty band applied to the point estimate.
LOW_MULT, HIGH_MULT = 0.4, 2.5


def estimate_row(source: str, views: int, subscribers: int, likes: int) -> dict:
    """Return {mid, low, high, ad_rev, sub_rev} monthly USD for one title."""
    p = PARAMS.get(source, DEFAULT)
    views = views or 0
    subs = subscribers or 0
    ad_rev = (views * p["monthly_view_frac"] / 1000.0) * p["rpm"]
    sub_rev = subs * p["sub_pay_rate"] * p["sub_arpu"]
    mid = ad_rev + sub_rev
    return {
        "ad_rev": round(ad_rev, 2), "sub_rev": round(sub_rev, 2),
        "est_monthly_usd": round(mid, 2),
        "est_low_usd": round(mid * LOW_MULT, 2),
        "est_high_usd": round(mid * HIGH_MULT, 2),
    }


def _load_latest_silver() -> pl.DataFrame | None:
    files = glob.glob(os.path.join(SILVER, "**", "*.parquet"), recursive=True)
    if not files:
        return None
    df = pl.scan_parquet(files, hive_partitioning=False).drop("tags").collect()
    # Latest observation per title (metrics are cumulative, so take the max date).
    return (df.sort("scraped_at")
              .group_by("comic_id")
              .agg([pl.col(c).last() for c in
                    ["source", "title", "genre", "views", "subscribers", "likes"]]))


def run() -> None:
    df = _load_latest_silver()
    if df is None:
        print("No Silver data found.")
        return
    # Only titles with at least one monetizable signal.
    df = df.filter((pl.col("views") > 0) | (pl.col("subscribers") > 0))
    if df.is_empty():
        print("No titles carry an absolute engagement metric yet — run the "
              "detail-enrichment crawl first.")
        return

    est = df.with_columns([
        pl.struct(["source", "views", "subscribers", "likes"]).map_elements(
            lambda r: estimate_row(r["source"], r["views"], r["subscribers"], r["likes"]),
            return_dtype=pl.Struct([
                pl.Field("ad_rev", pl.Float64), pl.Field("sub_rev", pl.Float64),
                pl.Field("est_monthly_usd", pl.Float64),
                pl.Field("est_low_usd", pl.Float64), pl.Field("est_high_usd", pl.Float64)]),
        ).alias("e")
    ]).unnest("e").sort("est_monthly_usd", descending=True)

    os.makedirs(GOLD, exist_ok=True)
    out = os.path.join(GOLD, f"earnings_estimates_{int(datetime.now().timestamp())}.csv")
    est.write_csv(out)

    tot = est["est_monthly_usd"].sum()
    print(f"Estimated monthly revenue for {len(est)} titles with metrics "
          f"(⚠ MODELED estimate, wide error bars). Saved -> {out}")
    print(f"Aggregate est. monthly revenue across covered titles: "
          f"${tot:,.0f}  (range ${tot*LOW_MULT:,.0f}–${tot*HIGH_MULT:,.0f})\n")
    print("Top 15 by estimated monthly revenue:")
    top = est.head(15).select([
        "source", "title", "views", "subscribers",
        "est_low_usd", "est_monthly_usd", "est_high_usd"])
    with pl.Config(fmt_str_lengths=34, tbl_rows=15):
        print(top)


if __name__ == "__main__":
    run()
