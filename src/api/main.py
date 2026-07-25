"""Plotline API — the query layer over the warehouse (premium data feed).

Serves the DuckDB warehouse (``data/plotline.duckdb``) as a JSON API: discovery,
title profiles, leaderboard, trends, and the per-layer KPI endpoints. The full
data feed is gated behind an API key (the premium tier).

Run:  uvicorn src.api.main:app --reload
Docs: http://localhost:8000/docs
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal

import duckdb
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from src.api import auth, billing
from src.api.config import cfg
from src.api.ratelimit import install as install_ratelimit
from src.api.warehouse_loader import ensure_warehouse

logging.basicConfig(level=logging.INFO,
                    format='{"lvl":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}')
log = logging.getLogger("plotline.api")

app = FastAPI(title="Plotline API", version="1.0",
              description="Story-IP market intelligence — titles, trends, KPIs, and the premium data feed.")
app.add_middleware(CORSMiddleware, allow_origins=cfg.CORS_ORIGINS, allow_methods=["GET"],
                   allow_headers=["*"])
install_ratelimit(app)

app.include_router(billing.router)

DB = ensure_warehouse()
_con = duckdb.connect(DB, read_only=True)
auth.init_schema()  # no-op unless DATABASE_URL is set
log.info("Plotline API ready (env=%s, warehouse=%s, billing=%s)", cfg.ENV, DB, cfg.BILLING_ENABLED)


def _clean(v):
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return v


def q(sql: str, params: list | None = None) -> list[dict]:
    cur = _con.cursor()
    cur.execute(sql, params or [])
    cols = [d[0] for d in cur.description]
    return [{c: _clean(v) for c, v in zip(cols, row)} for row in cur.fetchall()]


def require_key(x_api_key: str = Header(None, description="Premium API key")):
    if not auth.valid_key(x_api_key):
        raise HTTPException(401, "Invalid or missing API key (premium endpoint).")
    return x_api_key


@app.get("/health", summary="Liveness — process is up", include_in_schema=False)
def health():
    return {"status": "ok"}


@app.get("/ready", summary="Readiness — warehouse is queryable", include_in_schema=False)
def ready():
    try:
        _con.cursor().execute("SELECT 1").fetchone()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(503, f"warehouse not ready: {e}")
    return {"status": "ready"}


@app.get("/", summary="Service + market summary")
def root():
    return {"service": "Plotline API", "version": "1.0", "market": q("SELECT * FROM v_market")[0]}


@app.get("/titles", summary="Filterable, ranked title list")
def titles(source: str | None = None, genre: str | None = None, min_score: float = 0,
           sort: str = Query("plotscore", pattern="^(plotscore|reach|revenue)$"),
           limit: int = Query(50, le=500), offset: int = 0):
    where, params = ["(plotscore>=? OR plotscore IS NULL)"], [min_score]
    if source:
        where.append("platform=?"); params.append(source)
    if genre:
        where.append("genre=?"); params.append(genre)
    col = {"plotscore": "plotscore", "reach": "views", "revenue": "est_usd"}[sort]
    return q(f"""SELECT comic_id,title,platform,genre,author,plotscore,views AS reach,
                 est_usd AS est_monthly_usd,best_rank,rating,cover
                 FROM fact_title WHERE {' AND '.join(where)}
                 ORDER BY {col} DESC NULLS LAST LIMIT ? OFFSET ?""", params + [limit, offset])


@app.get("/title/{comic_id:path}", summary="Full title profile")
def title(comic_id: str):
    r = q("SELECT * FROM v_title WHERE comic_id=?", [comic_id])
    if not r:
        raise HTTPException(404, "Title not found.")
    return r[0]


@app.get("/leaderboard", summary="Top titles by PlotScore")
def leaderboard(limit: int = Query(25, le=200)):
    return q("SELECT * FROM v_leaderboard LIMIT ?", [limit])


@app.get("/trends", summary="Rising / falling movers by rank change")
def trends(limit: int = Query(15, le=100)):
    daily = q("""WITH r AS (SELECT comic_id, first(rank ORDER BY date) f, last(rank ORDER BY date) l,
                 count(*) n FROM fact_title_daily WHERE rank IS NOT NULL GROUP BY comic_id HAVING n>1)
                 SELECT t.title, t.platform, t.genre, (r.f-r.l) AS rank_delta
                 FROM r JOIN fact_title t USING(comic_id)""")
    rising = sorted([d for d in daily if d["rank_delta"] > 0], key=lambda x: -x["rank_delta"])[:limit]
    falling = sorted([d for d in daily if d["rank_delta"] < 0], key=lambda x: x["rank_delta"])[:limit]
    return {"rising": rising, "falling": falling}


@app.get("/genres", summary="Genre KPI layer")
def genres():
    return q("SELECT * FROM dim_genre ORDER BY total_reach DESC")


@app.get("/platforms", summary="Platform KPI layer")
def platforms():
    return q("SELECT * FROM dim_platform ORDER BY total_reach DESC")


@app.get("/authors", summary="Author KPI layer")
def authors(limit: int = Query(50, le=500)):
    return q("SELECT * FROM dim_author ORDER BY titles DESC, total_reach DESC LIMIT ?", [limit])


@app.get("/search", summary="Search titles")
def search(query: str, limit: int = Query(20, le=100)):
    return q("""SELECT comic_id,title,platform,genre,plotscore,cover FROM fact_title
                WHERE title ILIKE ? ORDER BY plotscore DESC NULLS LAST LIMIT ?""",
             ["%" + query + "%", limit])


@app.get("/feed/titles", summary="PREMIUM — full data feed (requires API key)")
def feed(_key: str = Depends(require_key), limit: int = Query(1000, le=5000), offset: int = 0):
    return q("SELECT * FROM fact_title ORDER BY plotscore DESC NULLS LAST LIMIT ? OFFSET ?",
             [limit, offset])
