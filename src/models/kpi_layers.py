"""Multi-layer KPI engine — analyse the market at every level.

Produces an extensive KPI set for each analytical layer the product exposes:
title/IP, author, publisher, platform, genre, readership (engagement), revenue,
and painting-style. Each layer is written to ``data/gold/kpi_<layer>.parquet``
and a compact catalog to ``data/gold/kpi_catalog.json``.

Run:  python -m src.models.kpi_layers
"""
from __future__ import annotations

import glob
import json
import os
import sys

import polars as pl

from src.models.advanced_metrics import herfindahl_hirschman_index as hhi
from src.models.trends_engine import _scored

sys.stdout.reconfigure(encoding="utf-8")
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
GOLD = os.path.join(_ROOT, "data", "gold")
SILVER = os.path.join(_ROOT, "data", "silver", "comics")


def _base() -> pl.DataFrame:
    u = _scored()  # plotscore, est_usd, momentum, views/subs/likes/rating, genre, source, author, content_type
    # attach comments + cover from Silver
    sv = (pl.scan_parquet(glob.glob(os.path.join(SILVER, "**", "*.parquet"), recursive=True), hive_partitioning=False)
            .sort("scraped_at").group_by("comic_id")
            .agg(pl.col("comments").max().alias("comments"),
                 pl.col("cover_url").drop_nulls().first().alias("cover"),
                 pl.col("publisher").drop_nulls().first().alias("publisher"),
                 # latest non-null synopsis, plus status + tags (populated by the W2 adapters)
                 pl.col("synopsis").drop_nulls().last().alias("synopsis"),
                 pl.col("status").drop_nulls().last().alias("status"),
                 pl.col("tags").drop_nulls().last().alias("tags"))
            .collect())
    u = u.join(sv, on="comic_id", how="left")
    return u.with_columns([
        pl.when(pl.col("views") > 0).then(pl.col("likes") / pl.col("views")).otherwise(None).alias("like_through"),
        pl.when(pl.col("views") > 0).then(pl.col("subscribers") / pl.col("views")).otherwise(None).alias("subs_per_view"),
    ])


def _genre(u):
    rows = []
    for g in [x for x in u["genre"].unique().to_list() if x]:
        s = u.filter(pl.col("genre") == g); v = s["views"].to_list()
        rows.append({"genre": g, "titles": s.height, "total_reach": int(s["views"].sum()),
                     "avg_plotscore": round(s["plotscore"].mean() or 0, 1), "top_plotscore": round(s["plotscore"].max() or 0, 1),
                     "avg_momentum": round(s["momentum"].mean() or 0, 1), "hhi": round(hhi(v)),
                     "market_type": "Concentrated" if hhi(v) > 2500 else "Moderate" if hhi(v) > 1500 else "Competitive",
                     "est_monthly_usd": round(s["est_usd"].sum()), "avg_rating": round(s["rating"].mean() or 0, 2),
                     "avg_like_through": round((s["like_through"].mean() or 0) * 100, 2),
                     "whitespace": round(int(s["views"].sum()) / max(s.height, 1)),
                     "novel_share": round(s["content_type"].eq("novel").sum() / s.height, 2)})
    return pl.DataFrame(rows).sort("total_reach", descending=True) if rows else pl.DataFrame()


def _platform(u):
    return u.group_by("source").agg(
        pl.len().alias("titles"), pl.col("views").sum().alias("total_reach"),
        pl.col("subscribers").sum().alias("total_subscribers"), pl.col("likes").sum().alias("total_likes"),
        pl.col("plotscore").mean().round(1).alias("avg_plotscore"), pl.col("est_usd").sum().round().alias("est_monthly_usd"),
        pl.col("rating").mean().fill_null(0).round(2).alias("avg_rating"),
        (pl.col("like_through").mean().fill_null(0) * 100).round(2).alias("avg_like_through_pct"),
        (pl.col("cover").is_not_null().mean() * 100).round(1).alias("cover_coverage_pct"),
        pl.col("content_type").eq("novel").mean().round(2).alias("novel_share"),
    ).sort("total_reach", descending=True)


def _author(u):
    return u.filter(pl.col("author").is_not_null()).group_by("author").agg(
        pl.len().alias("titles"), pl.col("source").n_unique().alias("platforms"),
        pl.col("views").sum().alias("total_reach"), pl.col("plotscore").max().round(1).alias("best_plotscore"),
        pl.col("plotscore").mean().round(1).alias("avg_plotscore"), pl.col("est_usd").sum().round().alias("est_monthly_usd"),
    ).sort(["titles", "total_reach"], descending=True)


def _publisher(u):
    p = u.filter(pl.col("publisher").is_not_null())
    if p.is_empty():
        return pl.DataFrame()
    return p.group_by("publisher").agg(
        pl.len().alias("titles"), pl.col("views").sum().alias("total_reach"),
        pl.col("plotscore").mean().round(1).alias("avg_plotscore"), pl.col("est_usd").sum().round().alias("est_monthly_usd"),
    ).sort("total_reach", descending=True)


def run() -> None:
    u = _base()
    if u is None or u.is_empty():
        print("No data."); return
    os.makedirs(GOLD, exist_ok=True)
    layers = {"genre": _genre(u), "platform": _platform(u), "author": _author(u), "publisher": _publisher(u)}
    for name, df in layers.items():
        if not df.is_empty():
            df.write_csv(os.path.join(GOLD, f"kpi_{name}.csv"))

    # readership (engagement) + revenue rollups
    withm = u.filter((pl.col("views") > 0) | (pl.col("subscribers") > 0))
    catalog = {
        "universe": {"titles": u.height, "with_metrics": withm.height,
                     "coverage_pct": round(withm.height / u.height * 100, 1),
                     "authors": u.filter(pl.col("author").is_not_null())["author"].n_unique(),
                     "publishers": u.filter(pl.col("publisher").is_not_null())["publisher"].n_unique(),
                     "genres": u.filter(pl.col("genre").is_not_null())["genre"].n_unique(),
                     "with_cover": int(u.filter(pl.col("cover").is_not_null()).height)},
        "readership": {"total_reach": int(u["views"].sum()), "total_subscribers": int(u["subscribers"].sum()),
                       "total_likes": int(u["likes"].sum()), "total_comments": int(u["comments"].fill_null(0).sum()),
                       "avg_like_through_pct": round((u["like_through"].mean() or 0) * 100, 2),
                       "avg_rating": round(u["rating"].mean() or 0, 2)},
        "revenue": {"est_monthly_usd": round(u["est_usd"].sum()), "est_annual_usd": round(u["est_usd"].sum() * 12),
                    "hhi": round(hhi(u.filter(pl.col("est_usd") > 0)["est_usd"].to_list()))},
    }
    json.dump(catalog, open(os.path.join(GOLD, "kpi_catalog.json"), "w", encoding="utf-8"), indent=2)

    print(f"KPI layers computed. Catalog + {len([d for d in layers.values() if not d.is_empty()])} layer tables -> data/gold/\n")
    print("UNIVERSE:", catalog["universe"])
    print("READERSHIP:", catalog["readership"])
    print("REVENUE:", catalog["revenue"])
    print("\nGENRE layer (top 6):")
    with pl.Config(tbl_rows=6, fmt_str_lengths=14):
        print(layers["genre"].select(["genre", "titles", "total_reach", "avg_plotscore", "hhi", "avg_like_through", "est_monthly_usd"]).head(6))
    print("\nPLATFORM layer:")
    with pl.Config(tbl_rows=8):
        print(layers["platform"].select(["source", "titles", "total_reach", "avg_plotscore", "avg_like_through_pct", "cover_coverage_pct", "est_monthly_usd"]))


if __name__ == "__main__":
    run()
