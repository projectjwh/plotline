"""Comprehensive star-schema warehouse (``data/warehouse.duckdb``).

Restructures the medallion output into a proper dimensional model so each
scraping session ingests into conformed dims + day-grain facts + analytic
layers. Built **additively**: it reads Silver (the per-session record),
``data/silver/episodes``, the scored ``plotline.duckdb`` layer, and the Gold
enrichments — and does NOT touch the live ``plotline.duckdb`` the explorer uses.

Model
  Dimensions   dim_platform · dim_date · dim_author · dim_publisher ·
               dim_title · dim_episode
  Facts        fact_title_daily (title × day × session)  ← core session ingest
               fact_episode (episode grain)
               fact_platform_daily (platform × day)
               fact_score (title analytic layer: plotscore, est_usd, ranks)
  Bridges      bridge_title_author · bridge_title_publisher
  Relationships rel_contract   ← schema-only; loads data/manual/contracts.csv if present
               fact_impression ← schema-only; no public source
  Analytics    agg_title_period · agg_genre_daily · agg_platform_period
               dim_title_verification (cross-source: AniList/Wikipedia)
  Views        v_title_current · v_leaderboard · v_platform_summary
  Meta         warehouse_meta (build stamp + grain/availability notes)

DATA-AVAILABILITY HONESTY: per-episode views/subscriptions, impressions, and
contract terms are NOT exposed by any platform we scrape. Those columns exist in
the schema but are NULL/empty until a licensed feed or manual entry supplies
them (contracts via data/manual/contracts.csv).

Run:  python -m src.db.star_schema
"""
from __future__ import annotations

import datetime
import glob
import os
import sys

import duckdb
import polars as pl

from src.models.genre_map import normalize_genre

sys.stdout.reconfigure(encoding="utf-8")

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
SILVER = os.path.join(_ROOT, "data", "silver", "comics")
EPISODES = os.path.join(_ROOT, "data", "silver", "episodes", "episodes.parquet")
GOLD = os.path.join(_ROOT, "data", "gold")
PLOTLINE_DB = os.path.join(_ROOT, "data", "plotline.duckdb")
OUT_DB = os.path.join(_ROOT, "data", "warehouse.duckdb")
MANUAL = os.path.join(_ROOT, "data", "manual", "contracts.csv")

PLAT_NAMES = {"webtoon_global": "Webtoon", "tapas_io": "Tapas", "globalcomix": "GlobalComix",
              "wattpad": "Wattpad", "mangaplus": "Manga Plus", "webcomics_app": "WebComics",
              "ridibooks": "Ridibooks", "webnovel": "Webnovel", "royalroad": "RoyalRoad",
              "lezhin": "Lezhin", "inkitt": "Inkitt", "joara": "Joara", "munpia": "Munpia"}


def _contracts_template() -> None:
    """Write an empty manual-entry template so deal data can be loaded later."""
    d = os.path.dirname(MANUAL)
    os.makedirs(d, exist_ok=True)
    if not os.path.exists(MANUAL):
        with open(MANUAL, "w", encoding="utf-8") as f:
            f.write("# Manual contract/licensing entries (no public source exists for this).\n"
                    "# Fill rows and re-run `python -m src.db.star_schema` to load into rel_contract.\n"
                    "title_id,title,publisher,platform,contract_date,contract_size_usd,term_months,territory,rights,notes\n")


def build() -> None:
    sv_files = glob.glob(os.path.join(SILVER, "**", "*.parquet"), recursive=True)
    if not sv_files:
        print("No Silver data — build the pipeline first.")
        return
    print("Loading Silver…")
    sv = (pl.scan_parquet(sv_files, hive_partitioning=False).collect()
            .with_columns(pl.col("scraped_at").dt.date().alias("date")))

    # --- title × day grain (one row per comic_id per day = the session record) ---
    daily = (sv.group_by(["comic_id", "date"]).agg([
        pl.col("source").first(), pl.col("platform_native_id").first(),
        pl.col("views").max(), pl.col("subscribers").max(), pl.col("likes").max(),
        pl.col("comments").max(), pl.col("rating").max(), pl.col("rank").min(),
        pl.col("primary_metric").max(), pl.col("metric_type").first(),
    ]))

    # --- first/last seen per title ---
    seen = sv.group_by("comic_id").agg(
        pl.col("date").min().alias("first_seen"), pl.col("date").max().alias("last_seen"),
        pl.col("date").n_unique().alias("n_days"))

    con = duckdb.connect(OUT_DB)
    con.execute("PRAGMA disable_progress_bar")
    for t in ("_daily", "_seen", "_titledim", "_episodes", "_verified", "_units", "_epk", "_art", "_restricted"):
        con.execute(f"DROP VIEW IF EXISTS {t}")

    # title dimension basis = the scored one-row-per-title layer from plotline.duckdb
    con.execute(f"ATTACH '{PLOTLINE_DB}' AS pl (READ_ONLY)")
    ft = con.execute("SELECT * FROM pl.fact_title").pl()
    con.execute("DETACH pl")
    genres = [normalize_genre(g) for g in ft["genre"].to_list()]
    ft = ft.with_columns([
        pl.Series("genre_en", [g[0] for g in genres]),
        pl.Series("genre_parent", [g[1] for g in genres]),
    ]).join(seen, on="comic_id", how="left")

    # optional restricted-titles flag
    restricted_ids = set()
    rp = os.path.join(GOLD, "restricted_titles.parquet")
    if os.path.exists(rp):
        restricted_ids = set(pl.read_parquet(rp)["comic_id"].to_list())
    ft = ft.with_columns(pl.col("comic_id").is_in(list(restricted_ids)).alias("is_restricted"))

    ep = pl.read_parquet(EPISODES) if os.path.exists(EPISODES) else pl.DataFrame(
        schema={"comic_id": pl.Utf8, "episode_no": pl.Int32, "episode_title": pl.Utf8,
                "upload_date": pl.Utf8, "likes": pl.Int64, "views": pl.Int64, "comments": pl.Int64})
    def _gold(name):
        p = os.path.join(GOLD, f"{name}.parquet")
        return pl.read_parquet(p) if os.path.exists(p) else None
    vf, units, epk, art = (_gold("verified_profile"), _gold("unit_title"),
                           _gold("episode_kpis"), _gold("art_style"))

    con.register("_daily", daily.to_arrow())
    con.register("_titledim", ft.to_arrow())
    con.register("_episodes", ep.to_arrow())
    if vf is not None:
        con.register("_verified", vf.to_arrow())
    if epk is not None:
        con.register("_epk", epk.to_arrow())

    print("Building dimensional model…")
    plat_rows = ", ".join(f"('{k}','{v}')" for k, v in PLAT_NAMES.items())

    con.execute("BEGIN")
    # ---- DIMENSIONS ---------------------------------------------------------
    con.execute(f"""CREATE OR REPLACE TABLE dim_platform AS
        WITH names(platform_key, platform_name) AS (VALUES {plat_rows}),
        stats AS (SELECT source AS platform_key, count(*) n_titles FROM _titledim GROUP BY 1)
        SELECT COALESCE(n.platform_key, s.platform_key) platform_key,
               COALESCE(n.platform_name, s.platform_key) platform_name, COALESCE(s.n_titles,0) n_titles
        FROM names n FULL OUTER JOIN stats s USING (platform_key)""")

    con.execute("""CREATE OR REPLACE TABLE dim_date AS
        SELECT date, year(date) yr, month(date) mo, week(date) wk,
               dayofweek(date) dow, strftime(date,'%Y-%m') ym
        FROM (SELECT DISTINCT date FROM _daily) ORDER BY date""")

    con.execute("""CREATE OR REPLACE TABLE dim_author AS
        SELECT row_number() OVER (ORDER BY author) author_key, author AS author_name
        FROM (SELECT DISTINCT author FROM _titledim WHERE author IS NOT NULL AND author<>'')""")

    con.execute("""CREATE OR REPLACE TABLE dim_publisher AS
        SELECT row_number() OVER (ORDER BY publisher) publisher_key, publisher AS publisher_name
        FROM (SELECT DISTINCT publisher FROM _titledim WHERE publisher IS NOT NULL AND publisher<>'')""")

    con.execute("""CREATE OR REPLACE TABLE dim_title AS
        SELECT comic_id AS title_key, source AS platform_key, title, content_type,
               genre AS genre_raw, genre_en, genre_parent, publisher, cover AS cover_url,
               status, synopsis, first_seen, last_seen, n_days, is_restricted
        FROM _titledim""")

    con.execute("""CREATE OR REPLACE TABLE dim_episode AS
        SELECT row_number() OVER (ORDER BY comic_id, episode_no) episode_key,
               comic_id AS title_key, episode_no, episode_title, upload_date
        FROM _episodes WHERE episode_no IS NOT NULL""")

    # ---- FACTS --------------------------------------------------------------
    con.execute("""CREATE OR REPLACE TABLE fact_title_daily AS
        SELECT comic_id AS title_key, date, source AS platform_key,
               views, subscribers, likes, comments, rating, rank,
               primary_metric, metric_type
        FROM _daily""")

    # per-episode: only likes are exposed by platforms; views/subs/impressions unavailable
    con.execute("""CREATE OR REPLACE TABLE fact_episode AS
        SELECT e.episode_key, e.title_key, e.episode_no,
               ep.likes, CAST(NULL AS BIGINT) AS views, CAST(NULL AS BIGINT) AS subscriptions,
               CAST(NULL AS BIGINT) AS comments, CAST(NULL AS BIGINT) AS impressions
        FROM dim_episode e
        JOIN _episodes ep ON ep.comic_id=e.title_key AND ep.episode_no=e.episode_no""")

    con.execute("""CREATE OR REPLACE TABLE fact_platform_daily AS
        SELECT platform_key, date, count(*) n_titles,
               sum(views) total_views, sum(subscribers) total_subscribers,
               sum(likes) total_likes, round(avg(rating),3) avg_rating
        FROM fact_title_daily GROUP BY 1,2""")

    con.execute("""CREATE OR REPLACE TABLE fact_score AS
        SELECT comic_id AS title_key, plotscore, reach_pct, momentum_pct, engagement_pct,
               monetization_pct, quality_pct, est_usd AS est_monthly_usd,
               best_rank, latest_rank, momentum, like_through
        FROM _titledim""")

    # ---- BRIDGES ------------------------------------------------------------
    con.execute("""CREATE OR REPLACE TABLE bridge_title_author AS
        SELECT t.comic_id AS title_key, a.author_key, 'creator' AS role
        FROM _titledim t JOIN dim_author a ON a.author_name=t.author
        WHERE t.author IS NOT NULL AND t.author<>''""")

    con.execute("""CREATE OR REPLACE TABLE bridge_title_publisher AS
        SELECT t.comic_id AS title_key, p.publisher_key
        FROM _titledim t JOIN dim_publisher p ON p.publisher_name=t.publisher
        WHERE t.publisher IS NOT NULL AND t.publisher<>''""")

    # ---- RELATIONSHIPS: schema-only (no public source) ----------------------
    con.execute("""CREATE OR REPLACE TABLE rel_contract (
        contract_id BIGINT, title_key VARCHAR, publisher_key BIGINT, platform_key VARCHAR,
        contract_date DATE, contract_size_usd DOUBLE, term_months INTEGER,
        territory VARCHAR, rights VARCHAR, notes VARCHAR, source VARCHAR)""")
    con.execute("""CREATE OR REPLACE TABLE fact_impression (
        title_key VARCHAR, date DATE, impressions BIGINT, source VARCHAR)""")

    # ---- ANALYTIC LAYERS ----------------------------------------------------
    con.execute("""CREATE OR REPLACE TABLE agg_title_period AS
        WITH p AS (
          SELECT title_key, 'all' period, count(*) n_obs, round(avg(views)) avg_views,
                 max(views) max_views, round(avg(rank),1) avg_rank, min(rank) best_rank
          FROM fact_title_daily GROUP BY 1
          UNION ALL
          SELECT title_key, '30d', count(*), round(avg(views)), max(views), round(avg(rank),1), min(rank)
          FROM fact_title_daily WHERE date >= (SELECT max(date) FROM fact_title_daily) - INTERVAL 30 DAY GROUP BY 1
          UNION ALL
          SELECT title_key, '7d', count(*), round(avg(views)), max(views), round(avg(rank),1), min(rank)
          FROM fact_title_daily WHERE date >= (SELECT max(date) FROM fact_title_daily) - INTERVAL 7 DAY GROUP BY 1)
        SELECT * FROM p""")

    con.execute("""CREATE OR REPLACE TABLE agg_genre_daily AS
        SELECT t.genre_parent, f.date, count(*) n_titles, sum(f.views) total_views,
               round(avg(s.plotscore),1) avg_plotscore
        FROM fact_title_daily f JOIN dim_title t ON t.title_key=f.title_key
        LEFT JOIN fact_score s ON s.title_key=f.title_key
        WHERE t.genre_parent IS NOT NULL GROUP BY 1,2""")

    con.execute("""CREATE OR REPLACE TABLE agg_platform_period AS
        SELECT platform_key, count(DISTINCT date) n_days, round(avg(n_titles)) avg_titles,
               max(total_views) peak_total_views
        FROM fact_platform_daily GROUP BY 1""")

    if vf is not None:
        con.execute("""CREATE OR REPLACE TABLE dim_title_verification AS
            SELECT comic_id AS title_key, anilist_url, wikipedia_url,
                   author_conf, genre_conf, ext_score, ext_popularity, last_verified
            FROM _verified""")

    # ---- SEMANTIC VIEWS -----------------------------------------------------
    con.execute("""CREATE OR REPLACE VIEW v_title_current AS
        SELECT t.*, p.platform_name, s.plotscore, s.est_monthly_usd, s.best_rank, s.latest_rank,
               ap.avg_views AS avg_views_all
        FROM dim_title t
        LEFT JOIN dim_platform p ON p.platform_key=t.platform_key
        LEFT JOIN fact_score s ON s.title_key=t.title_key
        LEFT JOIN agg_title_period ap ON ap.title_key=t.title_key AND ap.period='all'""")
    con.execute("""CREATE OR REPLACE VIEW v_leaderboard AS
        SELECT title_key, title, platform_name, genre_parent, plotscore, est_monthly_usd, best_rank
        FROM v_title_current WHERE plotscore IS NOT NULL ORDER BY plotscore DESC""")
    con.execute("""CREATE OR REPLACE VIEW v_platform_summary AS
        SELECT p.platform_name, p.n_titles, ap.n_days, ap.avg_titles, ap.peak_total_views
        FROM dim_platform p LEFT JOIN agg_platform_period ap USING (platform_key)
        ORDER BY p.n_titles DESC""")

    con.execute("COMMIT")

    # ---- optional manual contracts load ------------------------------------
    _contracts_template()
    try:
        c = pl.read_csv(MANUAL, comment_prefix="#")
        c = c.filter(pl.col("title_id").is_not_null())
        if c.height:
            con.register("_contracts", c.to_arrow())
            con.execute("""INSERT INTO rel_contract
                SELECT row_number() OVER () , title_id, NULL, platform, TRY_CAST(contract_date AS DATE),
                       TRY_CAST(contract_size_usd AS DOUBLE), TRY_CAST(term_months AS INTEGER),
                       territory, rights, notes, 'manual' FROM _contracts""")
            print(f"  loaded {c.height} manual contract rows")
    except Exception:  # noqa: BLE001 — empty/missing CSV is fine
        pass

    # ---- meta + summary -----------------------------------------------------
    con.execute("CREATE OR REPLACE TABLE warehouse_meta (key VARCHAR, value VARCHAR)")
    con.execute(f"""INSERT INTO warehouse_meta VALUES
        ('built_at','{datetime.datetime.now().isoformat(timespec='seconds')}'),
        ('silver_partitions','{len(sv_files)}'),
        ('grain','fact_title_daily = title x day x scrape session'),
        ('unavailable','per-episode views/subs, impressions, contract terms have no public source (schema-only)')""")

    tables = [r[0] for r in con.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_type='BASE TABLE' ORDER BY table_name").fetchall()]
    print(f"\nstar schema → {os.path.relpath(OUT_DB, _ROOT)}")
    for t in tables:
        n = con.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0]
        note = ""
        if t in ("rel_contract", "fact_impression") and n == 0:
            note = "  ← schema-only (no public source)"
        print(f"  {t:24} {n:>8,} rows{note}")
    views = [r[0] for r in con.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_type='VIEW' ORDER BY table_name").fetchall()]
    print("  views:", ", ".join(views))
    con.close()


if __name__ == "__main__":
    build()
