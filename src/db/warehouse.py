"""Plotline data warehouse builder.

Constructs a single, queryable DuckDB warehouse (``data/plotline.duckdb``) from
the medallion pipeline outputs — the database the product / API is served from.
It rebuilds cleanly on every run from the live computed layers, so it always
reflects the latest crawl.

Structure:
  dimensions   dim_platform · dim_genre · dim_author · dim_publisher
  facts        fact_title (current snapshot per title, all signals)
               fact_title_daily (title × crawl-date time series)
  layers       art_style · entities_ip · entities_author
  semantic     v_title (title + art style) · v_leaderboard · v_market

Run:  python -m src.db.warehouse
"""
from __future__ import annotations

import glob
import os
import sys

import duckdb
import polars as pl

from src.models.entity_resolution import resolve
from src.models.kpi_layers import _author, _base, _genre, _platform, _publisher

sys.stdout.reconfigure(encoding="utf-8")
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
SILVER = os.path.join(_ROOT, "data", "silver", "comics")
GOLD = os.path.join(_ROOT, "data", "gold")
DB = os.path.join(_ROOT, "data", "plotline.duckdb")

PLAT_NAMES = {"webtoon_global": "Webtoon", "tapas_io": "Tapas", "globalcomix": "GlobalComix",
              "wattpad": "Wattpad", "mangaplus": "Manga Plus", "webcomics_app": "WebComics",
              "ridibooks": "Ridibooks", "webnovel": "Webnovel"}


def _reg(con, name: str, df: pl.DataFrame):
    con.register(name, df.to_arrow())


def build() -> None:
    print("Computing analytical layers...")
    base = _base().with_columns(
        pl.col("source").replace_strict(PLAT_NAMES, default=pl.col("source")).alias("platform")
    )
    ip, au = resolve()
    genre_kpi, plat_kpi = _genre(base), _platform(base)
    author_kpi, pub_kpi = _author(base), _publisher(base)
    silver = (pl.scan_parquet(glob.glob(os.path.join(SILVER, "**", "*.parquet"), recursive=True),
                              hive_partitioning=False)
                .select("comic_id", "source", "title", "scraped_at", "rank",
                        "views", "likes", "subscribers", "comments").collect()
                .with_columns(pl.col("scraped_at").dt.date().alias("date")))
    art_path = os.path.join(GOLD, "art_style.parquet")
    art = pl.read_parquet(art_path) if os.path.exists(art_path) else None
    ep_path = os.path.join(_ROOT, "data", "silver", "episodes", "episodes.parquet")
    episodes = pl.read_parquet(ep_path).drop("source_file") if os.path.exists(ep_path) else None
    epkpi_path = os.path.join(GOLD, "episode_kpis.parquet")
    epkpi = pl.read_parquet(epkpi_path) if os.path.exists(epkpi_path) else None
    unit_path = os.path.join(GOLD, "unit_title.parquet")
    units = pl.read_parquet(unit_path) if os.path.exists(unit_path) else None

    if os.path.exists(DB):
        os.remove(DB)
    con = duckdb.connect(DB)

    print("Loading warehouse tables...")
    _reg(con, "_base", base); _reg(con, "_silver", silver)
    _reg(con, "_ip", ip.drop("platforms")); _reg(con, "_au", au)
    _reg(con, "_gk", genre_kpi); _reg(con, "_pk", plat_kpi)
    _reg(con, "_ak", author_kpi)
    if not pub_kpi.is_empty():
        _reg(con, "_pubk", pub_kpi)

    # facts
    con.execute("CREATE TABLE fact_title AS SELECT * FROM _base")
    con.execute("CREATE TABLE fact_title_daily AS SELECT * FROM _silver")
    # dimensions (attributes + measures per entity)
    con.execute("CREATE TABLE dim_platform AS SELECT * FROM _pk")
    con.execute("CREATE TABLE dim_genre AS SELECT * FROM _gk")
    con.execute("CREATE TABLE dim_author AS SELECT * FROM _ak")
    if not pub_kpi.is_empty():
        con.execute("CREATE TABLE dim_publisher AS SELECT * FROM _pubk")
    # entity + style layers
    con.execute("CREATE TABLE entities_ip AS SELECT * FROM _ip")
    con.execute("CREATE TABLE entities_author AS SELECT * FROM _au")
    if art is not None:
        _reg(con, "_art", art.select("real_id", "style_name", "brightness", "saturation", "colorfulness", "warmth"))
        con.execute("CREATE TABLE art_style AS SELECT * FROM _art")
    else:
        con.execute("CREATE TABLE art_style(real_id VARCHAR, style_name VARCHAR)")
    if episodes is not None:
        _reg(con, "_ep", episodes)
        con.execute("CREATE TABLE fact_episode AS SELECT * FROM _ep")
    if epkpi is not None:
        _reg(con, "_epk", epkpi)
        con.execute("CREATE TABLE kpi_episode AS SELECT * FROM _epk")
    if units is not None:
        _reg(con, "_units", units.select(
            "comic_id", "content_type", "unit_type", "units", "chapters_per_volume",
            *[c for c in ("ep_tracked", "avg_ep_likes", "median_ep_likes",
                          "top_ep_likes", "engagement_decay_pct") if c in units.columns]))
        con.execute("CREATE TABLE fact_content_structure AS SELECT * FROM _units")

    # indexes
    for t, c in [("fact_title", "comic_id"), ("fact_title_daily", "comic_id"),
                 ("fact_title_daily", "date")]:
        con.execute(f"CREATE INDEX idx_{t}_{c} ON {t}({c})")

    # semantic views
    con.execute("""CREATE VIEW v_title AS
        SELECT t.*, a.style_name, a.brightness AS cover_brightness, a.saturation AS cover_saturation
        FROM fact_title t LEFT JOIN art_style a ON t.comic_id = a.real_id""")
    con.execute("""CREATE VIEW v_leaderboard AS
        SELECT comic_id, title, platform, genre, author, plotscore, views AS reach,
               subscribers, est_usd AS est_monthly_usd, best_rank
        FROM fact_title WHERE plotscore IS NOT NULL ORDER BY plotscore DESC""")
    if units is not None:
        con.execute("""CREATE VIEW v_content_structure AS
            SELECT t.comic_id, t.title, t.platform, t.genre, t.author,
                   c.content_type, c.unit_type, c.units, c.chapters_per_volume,
                   c.ep_tracked, c.avg_ep_likes, c.top_ep_likes, c.engagement_decay_pct,
                   t.plotscore, t.views
            FROM fact_title t JOIN fact_content_structure c ON t.comic_id = c.comic_id
            ORDER BY c.units DESC""")
    con.execute("""CREATE VIEW v_market AS SELECT
        count(*) AS titles,
        count(*) FILTER (WHERE views>0 OR subscribers>0) AS with_metrics,
        count(DISTINCT author) AS authors,
        count(DISTINCT genre) AS genres,
        sum(views) AS total_reach, sum(est_usd) AS est_monthly_usd,
        round(avg(like_through)*100,2) AS avg_like_through_pct
        FROM fact_title""")

    tables = [r[0] for r in con.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_type='BASE TABLE' ORDER BY 1").fetchall()]
    print(f"\nWarehouse built → {DB}")
    print(f"Tables ({len(tables)}):")
    for t in tables:
        n = con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        print(f"   {t:22} {n:>7,} rows")
    print("Views: v_title, v_leaderboard, v_market")
    m = con.execute("SELECT * FROM v_market").pl()
    print("\nMarket summary:", m.to_dicts()[0])
    con.close()


if __name__ == "__main__":
    build()
