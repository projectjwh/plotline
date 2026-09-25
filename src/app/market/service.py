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
