"""Market service: titles, indices, movers, breadth, listings, treemap, genres and publishers.

It reads through ``Warehouse`` only, and caches computed frames per warehouse version
(the file's mtime), so a daily rebuild invalidates the cache automatically.
"""
from __future__ import annotations

import math
import re
import threading
from datetime import date, datetime

import polars as pl

from src.app.core.errors import Invalid, NotFound
from src.app.market import indices as ix
from src.app.market import readiness as rd
from src.app.market.warehouse import Warehouse
from src.models.earnings import HIGH_MULT, LOW_MULT
from src.models.genre_map import normalize_genre

TITLE_COLS = ["comic_id", "source", "platform", "title", "genre", "author", "publisher", "content_type",
              "views", "subscribers", "likes", "comments", "rating", "best_rank", "latest_rank",
              "reach_pct", "momentum_pct", "engagement_pct", "monetization_pct", "quality_pct",
              "plotscore", "est_usd", "momentum", "like_through", "subs_per_view",
              "cover", "synopsis", "status", "tags"]
SORTS = {"plotscore", "views", "views_change_pct", "rank_change", "readiness", "est_usd", "latest_rank"}


def _jsonable(v):
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return v


def rows(df: pl.DataFrame) -> list[dict]:
    return [{k: _jsonable(v) for k, v in r.items()} for r in df.iter_rows(named=True)]


def index_code(name: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", name.upper())[:10] or "OTHER"


class MarketService:
    def __init__(self, warehouse: Warehouse, cfg: dict, readiness_cfg: dict):
        self.wh, self.cfg, self.rcfg = warehouse, cfg, readiness_cfg
        self._cache: dict = {}
        self._ver = None
        self._lock = threading.RLock()  # builders call other cached getters

    # ---------- cached frames ----------
    def _cached(self, key, build):
        with self._lock:
            v = self.wh.version()
            if v != self._ver:
                self._cache, self._ver = {}, v
            if key not in self._cache:
                self._cache[key] = build()
            return self._cache[key]

    def daily(self) -> pl.DataFrame:
        def build():
            cols = self.wh.columns("fact_title_daily")
            sel = ["comic_id", "date", "views", "rank"] + (["scraped_at"] if "scraped_at" in cols else [])
            return self.wh.frame(f"SELECT {', '.join(sel)} FROM fact_title_daily WHERE date IS NOT NULL")
        return self._cached("daily", build)

    def universe(self) -> pl.DataFrame:
        return self._cached("universe", self._build_universe)

    def _build_universe(self) -> pl.DataFrame:
        have = self.wh.columns("fact_title")
        sel = [c for c in TITLE_COLS if c in have]
        u = self.wh.frame(f"SELECT {', '.join(sel)} FROM fact_title")
        for c in TITLE_COLS:  # keep a stable schema even on older warehouse builds
            if c not in u.columns:
                u = u.with_columns(pl.lit(None).alias(c))
        if "fact_content_structure" in self.wh.tables():
            units = self.wh.frame("SELECT comic_id, units FROM fact_content_structure")
            u = u.join(units, on="comic_id", how="left")
        else:
            u = u.with_columns(pl.lit(None, dtype=pl.Int64).alias("units"))
        g = [normalize_genre(x) for x in u["genre"].to_list()]
        u = u.with_columns(pl.Series("genre_en", [a for a, _ in g], dtype=pl.Utf8),
                           pl.Series("genre_parent", [b for _, b in g], dtype=pl.Utf8))
        mv, fs = ix.movers(self.daily()), ix.first_seen(self.daily())
        u = u.join(mv, on="comic_id", how="left").join(fs, on="comic_id", how="left")
        n = max(u.height, 1)
        u = u.with_columns((pl.col("views").fill_null(0).rank("average") / n).alias("_reach_p"))
        w, pri, dp = self.rcfg.get("weights"), self.rcfg.get("genre_priors", {}), self.rcfg.get("default_prior", 0.6)
        ready = [rd.score(rd.components(reach_pct=r["_reach_p"],
                                        like_through_pct=(r["like_through"] or 0) * 100 if r["like_through"] is not None else None,
                                        momentum=r["momentum"], status=r["status"], units=r["units"],
                                        genre=r["genre_en"] if r["genre_en"] in pri else r["genre_parent"],
                                        priors=pri, default_prior=dp), w)
                 for r in u.select("_reach_p", "like_through", "momentum", "status", "units", "genre_en", "genre_parent").iter_rows(named=True)]
        rising_min = self.cfg.get("rising_min_rank_change", 3)
        return u.with_columns(pl.Series("readiness", ready, dtype=pl.Int64),
                              (pl.col("rank_change").fill_null(0) >= rising_min).alias("rising"),
                              (pl.col("est_usd") * LOW_MULT).alias("est_usd_low"),
                              (pl.col("est_usd") * HIGH_MULT).alias("est_usd_high")).drop("_reach_p")

    # ---------- titles ----------
    def title(self, comic_id: str) -> dict:
        t = self.universe().filter(pl.col("comic_id") == comic_id)
        if t.is_empty():
            raise NotFound(f"title '{comic_id}' not found")
        return rows(t)[0]

    def title_exists(self, comic_id: str) -> bool:
        return not self.universe().filter(pl.col("comic_id") == comic_id).is_empty()

    def titles(self, *, genre=None, platform=None, status=None, content_type=None, author=None, publisher=None,
               min_readiness=None, q=None, sort="plotscore", desc=True, limit=50, offset=0) -> dict:
        if sort not in SORTS:
            raise Invalid(f"sort must be one of {sorted(SORTS)}")
        u = self.universe()
        for col, val in (("genre_parent", genre), ("platform", platform), ("content_type", content_type)):
            if val:
                u = u.filter(pl.col(col).str.to_lowercase() == val.lower())
        if status:
            u = u.filter(pl.col("status").str.to_lowercase() == status.lower())
        if author:
            u = u.filter(pl.col("author").str.to_lowercase() == author.lower())
        if publisher:
            u = u.filter(pl.col("publisher").str.to_lowercase() == publisher.lower())
        if min_readiness is not None:
            u = u.filter(pl.col("readiness") >= min_readiness)
        if q:
            u = u.filter(pl.col("title").str.to_lowercase().str.contains(q.lower(), literal=True)
                         | pl.col("author").fill_null("").str.to_lowercase().str.contains(q.lower(), literal=True))
        total = u.height
        u = u.sort(sort, descending=desc, nulls_last=True).slice(offset, limit)
        return {"total": total, "items": rows(u)}

    # ---------- market structure ----------
    def _members(self) -> list[tuple[str, str, set]]:
        u = self.universe()
        out = [("PLT-ALL", "All titles", set(u["comic_id"].to_list())),
               ("PLT-CMX", "Comics", set(u.filter(pl.col("content_type") != "novel")["comic_id"].to_list())),
               ("PLT-NOV", "Novels", set(u.filter(pl.col("content_type") == "novel")["comic_id"].to_list()))]
        mn = self.cfg.get("index_min_constituents", 3)
        for (g,), grp in u.filter(pl.col("genre_parent").is_not_null()).group_by(["genre_parent"]):
            if grp.height >= mn:
                out.append((index_code(g), g, set(grp["comic_id"].to_list())))
        return out

    def indices(self) -> list[dict]:
        def build():
            base, out = self.cfg.get("base_index", 1000), []
            for code, name, mem in self._members():
                s = ix.chain_index(self.daily(), mem, base)
                out.append({"code": code, "name": name, "constituents": len(mem), "series": s, **ix.index_summary(s)})
            return out
        return self._cached("indices", build)

    def index(self, code: str) -> dict:
        for i in self.indices():
            if i["code"] == code.upper():
                return i
        raise NotFound(f"index '{code}' not found")

    def movers(self, kind: str = "gainers", limit: int = 10) -> list[dict]:
        u = self.universe()
        spec = {"gainers": ("views_change_pct", True), "losers": ("views_change_pct", False),
                "rank_up": ("rank_change", True), "rank_down": ("rank_change", False)}
        if kind not in spec:
            raise Invalid(f"kind must be one of {sorted(spec)}")
        col, desc = spec[kind]
        u = u.filter(pl.col(col).is_not_null())
        u = u.filter(pl.col(col) > 0) if desc else u.filter(pl.col(col) < 0)
        return rows(u.sort(col, descending=desc).head(limit))

    def breadth(self) -> dict:
        u = self.universe()
        b = ix.breadth(u.select("rank_change", "comic_id"))
        return {**b, "rising": int(u["rising"].sum())}

    def listings(self, days: int | None = None) -> list[dict]:
        days = days or self.cfg.get("listing_window_days", 30)
        nl = ix.new_listings(self.daily(), days)
        if nl.is_empty():
            return []
        return rows(nl.join(self.universe().drop("first_seen"), on="comic_id", how="inner"))

    def treemap(self, group_by: str = "genre") -> list[dict]:
        col = {"genre": "genre_parent", "publisher": "publisher", "platform": "platform"}.get(group_by)
        if not col:
            raise Invalid("group_by must be genre, publisher or platform")
        u = self.universe().filter(pl.col(col).is_not_null())
        out = []
        for (k,), g in u.group_by([col]):
            out.append({"group": k, "views": int(g["views"].fill_null(0).sum()),
                        "titles": rows(g.select("comic_id", "title", "views", "plotscore", "views_change_pct", "rank_change")
                                        .sort("views", descending=True, nulls_last=True))})
        return sorted(out, key=lambda x: -x["views"])

    def _segment(self, col: str) -> list[dict]:
        u = self.universe().filter(pl.col(col).is_not_null())
        idx = {i["name"]: i for i in self.indices()} if col == "genre_parent" else {}
        out = []
        for (k,), g in u.group_by([col]):
            v = g["views"].fill_null(0)
            tot = float(v.sum())
            hhi = round(sum((x / tot * 100) ** 2 for x in v.to_list())) if tot else None
            rc = g["rank_change"].drop_nulls()
            lead = g.sort("plotscore", descending=True, nulls_last=True).row(0, named=True)
            out.append({"name": k, "titles": g.height, "total_views": int(tot),
                        "avg_plotscore": round(g["plotscore"].mean() or 0, 1),
                        "hhi": hhi, "market_type": None if hhi is None else
                        "Concentrated" if hhi > 2500 else "Moderate" if hhi > 1500 else "Competitive",
                        "advancing": int((rc > 0).sum()), "declining": int((rc < 0).sum()),
                        "leader": {"comic_id": lead["comic_id"], "title": lead["title"], "plotscore": lead["plotscore"]},
                        "index": {k2: idx[k][k2] for k2 in ("code", "value", "change_pct")} if k in idx else None})
        return sorted(out, key=lambda x: -x["total_views"])

    def genres(self) -> list[dict]:
        return self._segment("genre_parent")

    def publishers(self) -> list[dict]:
        return self._segment("publisher")

    def overview(self, limit: int = 8) -> dict:
        u = self.universe()
        idx = [{k: i[k] for k in ("code", "name", "constituents", "value", "change_pct")} |
               {"spark": [p["value"] for p in i["series"][-30:]]} for i in self.indices()]
        return {"as_of": _jsonable(self.daily()["date"].max()) if self.daily().height else None,
                "titles": u.height, "indices": idx, "breadth": self.breadth(),
                "gainers": self.movers("gainers", limit), "losers": self.movers("losers", limit),
                "rank_up": self.movers("rank_up", limit), "listings": self.listings()[:limit]}

    # ---------- feed events (D-033) ----------
    def as_of(self) -> date | None:
        """Latest crawl date in the warehouse."""
        d = self.daily()
        return d["date"].max() if d.height else None

    FEED_TITLE_COLS = ["comic_id", "title", "genre_parent", "author", "publisher", "platform", "cover",
                       "latest_rank", "rank_change", "rising", "views_change_pct", "first_seen"]

    def _title_brief(self, r: dict) -> dict:
        return {k: _jsonable(r.get(k)) for k in self.FEED_TITLE_COLS}

    def rank_moves(self, comic_ids: set[str]) -> list[dict]:
        """Latest day-over-day rank change for each followed title that moved."""
        if not comic_ids:
            return []
        u = self.universe().filter(pl.col("comic_id").is_in(list(comic_ids)) & pl.col("rank_change").is_not_null()
                                   & (pl.col("rank_change") != 0))
        return [{"at": _day(r["last_date"]), "title": self._title_brief(r)} for r in u.iter_rows(named=True)]

    def new_titles_by(self, authors: set[str], publishers: set[str], days: int) -> list[dict]:
        """Titles first listed within ``days`` whose author or publisher is followed (case-insensitive)."""
        a, p = {x.lower() for x in authors}, {x.lower() for x in publishers}
        out = []
        for r in self.listings(days):
            via = [{"type": col, "ref": r[col]} for col, followed in (("author", a), ("publisher", p))
                   if r.get(col) and r[col].lower() in followed]
            if via:
                out.append({"at": _day(r["first_seen"]), "via": via, "title": self._title_brief(r)})
        return out

    def episodes(self, comic_ids: set[str], since: date) -> list[dict]:
        """Episodes of followed titles released on or after ``since``.

        Uses ``fact_episode.upload_date`` when the warehouse build has it (the silver
        episodes table does; the star-schema variant does not). Otherwise returns [].
        """
        if not comic_ids or "fact_episode" not in self.wh.tables():
            return []
        cols = self.wh.columns("fact_episode")
        idc = "comic_id" if "comic_id" in cols else "title_key" if "title_key" in cols else None
        if not idc or "upload_date" not in cols or "episode_no" not in cols:
            return []
        extra = ", episode_title" if "episode_title" in cols else ", NULL AS episode_title"
        ids = sorted(comic_ids)
        df = self.wh.frame(f"SELECT {idc} AS comic_id, episode_no, CAST(upload_date AS VARCHAR) AS upload_date{extra} "
                           f"FROM fact_episode WHERE {idc} IN ({', '.join('?' * len(ids))})", ids)
        titles = {r["comic_id"]: r for r in self.universe().filter(pl.col("comic_id").is_in(ids)).iter_rows(named=True)}
        out = []
        for r in df.iter_rows(named=True):
            d = parse_upload_date(r["upload_date"])
            if d and d >= since and r["comic_id"] in titles:
                out.append({"at": _day(d), "episode_no": r["episode_no"], "episode_title": r["episode_title"],
                            "title": self._title_brief(titles[r["comic_id"]])})
        return out


def _day(d) -> str | None:
    if d is None:
        return None
    if isinstance(d, str):          # rows() already serialised it
        d = date.fromisoformat(d[:10])
    if isinstance(d, datetime):
        return d.replace(tzinfo=None).isoformat(timespec="seconds")
    return datetime(d.year, d.month, d.day).isoformat(timespec="seconds")


def parse_upload_date(s) -> date | None:
    """Platform date strings seen in silver episodes (same formats as src/models/episode_analytics._parse_date)."""
    if s is None:
        return None
    if isinstance(s, date):
        return s if not isinstance(s, datetime) else s.date()
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%Y-%m-%d", "%b. %d, %Y"):
        try:
            return datetime.strptime(str(s).strip(), fmt).date()
        except ValueError:
            continue
    return None
