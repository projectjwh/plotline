"""Trends engine (L4) — multi-dimensional signals over the resolved universe.

The old ``trend_detection`` ran one statistic on one dimension (views by genre).
This computes the signal *tables* the product and reports actually need — trends
and structure across genre, platform, and IP — from the scored + entity-resolved
universe. Output tables land in ``data/gold`` and are consumed by the investment
report.

Signals: reach, momentum, engagement, monetization, PlotScore, concentration
(HHI), and whitespace (demand ÷ supply) — sliced by dimension.

Run:  python -m src.models.trends_engine
"""
from __future__ import annotations

import glob
import os
import sys
from datetime import datetime

import polars as pl

from src.models.advanced_metrics import herfindahl_hirschman_index as hhi
from src.models.earnings import estimate_row
from src.models.entity_resolution import resolve
from src.models.plotscore import score_universe

sys.stdout.reconfigure(encoding="utf-8")
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
GOLD = os.path.join(_ROOT, "data", "gold")


def _scored() -> pl.DataFrame:
    u = score_universe()
    # per-title monetization + momentum (rank improvement across observations)
    return u.with_columns([
        pl.struct(["source", "views", "subscribers", "likes"]).map_elements(
            lambda r: float(estimate_row(r["source"], r["views"], r["subscribers"], r["likes"])["est_monthly_usd"]),
            return_dtype=pl.Float64).alias("est_usd"),
        pl.when(pl.col("n_obs") > 1)
          .then(pl.col("first_rank") - pl.col("latest_rank"))
          .otherwise(0).alias("momentum"),
    ])


def genre_trends(u: pl.DataFrame) -> pl.DataFrame:
    rows = []
    for g in [x for x in u["genre"].unique().to_list() if x]:
        sub = u.filter(pl.col("genre") == g)
        views = sub["views"].to_list()
        rows.append({
            "genre": g,
            "titles": sub.height,
            "total_reach": int(sub["views"].sum()),
            "avg_plotscore": round(sub["plotscore"].mean() or 0, 1),
            "top_plotscore": round(sub["plotscore"].max() or 0, 1),
            "avg_momentum": round(sub["momentum"].mean() or 0, 1),
            "est_monthly_usd": round(sub["est_usd"].sum()),
            "hhi": round(hhi(views), 0),
            "market_type": "Concentrated" if hhi(views) > 2500 else "Moderate" if hhi(views) > 1500 else "Competitive",
            # whitespace: demand (reach) per unit of supply (titles) — high = underserved
            "whitespace": round(int(sub["views"].sum()) / max(sub.height, 1)),
        })
    return pl.DataFrame(rows).sort("total_reach", descending=True) if rows else pl.DataFrame()


def platform_trends(u: pl.DataFrame) -> pl.DataFrame:
    return (u.group_by("source").agg([
        pl.len().alias("titles"),
        pl.col("views").sum().alias("total_reach"),
        pl.col("subscribers").sum().alias("total_subscribers"),
        pl.col("plotscore").mean().round(1).alias("avg_plotscore"),
        pl.col("est_usd").sum().round().alias("est_monthly_usd"),
        pl.col("content_type").first().alias("content_type"),
    ]).sort("total_reach", descending=True))


def top_ip(limit=25) -> pl.DataFrame:
    ip, _ = resolve()
    return ip.head(limit).select([
        "canonical_title", "n_platforms", "n_variants", "ip_views",
        "ip_subscribers", "ip_plotscore", "genre", "author", "content_type"])


def momentum_leaders(u: pl.DataFrame, limit=20) -> pl.DataFrame:
    return (u.filter(pl.col("momentum") > 0)
             .sort("momentum", descending=True).head(limit)
             .select(["title", "source", "genre", "momentum", "first_rank", "latest_rank", "plotscore"]))


def run() -> None:
    u = _scored()
    if u is None:
        print("No Silver data found.")
        return
    os.makedirs(GOLD, exist_ok=True)
    gt, pt, ti, ml = genre_trends(u), platform_trends(u), top_ip(), momentum_leaders(u)
    ts = int(datetime.now().timestamp())
    gt.write_csv(os.path.join(GOLD, f"trends_genre_{ts}.csv"))
    pt.write_csv(os.path.join(GOLD, f"trends_platform_{ts}.csv"))
    ti.write_csv(os.path.join(GOLD, f"trends_top_ip_{ts}.csv"))

    print(f"Trends engine — signals across {u.height} titles.\n")
    print("GENRE LANDSCAPE (reach · score · concentration · whitespace):")
    with pl.Config(tbl_rows=8, fmt_str_lengths=16):
        print(gt.head(8))
    print("\nWHITESPACE — highest demand-per-title (underserved):")
    for r in gt.sort("whitespace", descending=True).head(5).select(["genre", "titles", "whitespace", "avg_plotscore"]).iter_rows(named=True):
        print(f"   {r['genre'][:16]:16} titles={r['titles']:>4} demand/title={r['whitespace']:>12,} score={r['avg_plotscore']}")
    print("\nMOMENTUM LEADERS (biggest rank gains):")
    for r in ml.head(6).iter_rows(named=True):
        print(f"   +{r['momentum']:>3}  {r['title'][:32]:32} [{r['source'][:10]:10}] #{r['first_rank']}→#{r['latest_rank']}")


if __name__ == "__main__":
    run()
