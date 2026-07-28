"""Build the Plotline explorer artifact from the warehouse — repeatable.

Regenerates the single-file explorer (data + fonts injected into the template)
deterministically from ``data/plotline.duckdb`` + the gold layers + downloaded
covers. This replaces the throwaway inline export: run it after any pipeline
refresh and the frontend reflects the latest crawl.

  data  ← fact_title (signals) · fact_title_daily (rank time series) ·
          fact_content_structure (units) · episode_kpis + episodes (per-ep) ·
          art_style (palette) · cover_map (base64 thumbnails)
  html  ← explorer_assets/template.html with /*__FONTS__*/ + /*__DATA__*/ filled

Run:  python -m src.reports.build_explorer [--covers 300] [--out <path.html>]
Output: <out> (default scratchpad) and the sibling explorer_data.json.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os

import duckdb
import polars as pl

from src.scrapers.cover_crawler import build_cover_map
from src.models.genre_map import normalize_genre

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
DB = os.path.join(_ROOT, "data", "plotline.duckdb")
GOLD = os.path.join(_ROOT, "data", "gold")
EPISODES = os.path.join(_ROOT, "data", "silver", "episodes", "episodes.parquet")
ASSETS = os.path.join(os.path.dirname(__file__), "explorer_assets")

PLAT_ORDER = ["webtoon_global", "tapas_io", "webcomics_app", "globalcomix",
              "webnovel", "ridibooks", "mangaplus", "wattpad", "royalroad"]
PLAT_NAMES = {"webtoon_global": "Webtoon", "tapas_io": "Tapas", "globalcomix": "GlobalComix",
              "wattpad": "Wattpad", "mangaplus": "Manga Plus", "webcomics_app": "WebComics",
              "ridibooks": "Ridibooks", "webnovel": "Webnovel", "royalroad": "RoyalRoad"}


def _r(x, n=0):
    """Round to int (n=0) / n dp, tolerating None."""
    if x is None:
        return None
    return round(float(x), n) if n else round(float(x))


def build_data(max_covers: int = 300) -> dict:
    con = duckdb.connect(DB, read_only=True)
    ft = con.execute("SELECT * FROM fact_title").pl()
    daily = con.execute(
        "SELECT comic_id, CAST(date AS VARCHAR) date, rank, views, likes FROM fact_title_daily").pl()
    # warehouse catalog: live table inventory (name + row count) for the Data catalog tab
    cat_tables = []
    for (tn,) in con.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_type='BASE TABLE' ORDER BY table_name").fetchall():
        try:
            rn = con.execute(f'SELECT count(*) FROM "{tn}"').fetchone()[0]
        except Exception:  # noqa: BLE001
            rn = None
        cat_tables.append({"table": tn, "rows": rn})
    con.close()
    # unit_title carries source (the warehouse fact drops it), so read it directly.
    cs = pl.read_parquet(os.path.join(GOLD, "unit_title.parquet"))

    # source index
    srcs = [s for s in dict.fromkeys(PLAT_ORDER) if s in set(ft["source"])]
    for s in ft["source"].unique().to_list():
        if s not in srcs:
            srcs.append(s)
    sidx = {s: i for i, s in enumerate(srcs)}

    # date axis + per-title rank observations
    dates = sorted(daily["date"].unique().to_list())
    didx = {d: i for i, d in enumerate(dates)}
    obs: dict[str, list] = {}
    ovs: dict[str, list] = {}   # per-date views series (W4 — real growth over time)
    for row in daily.sort("date").iter_rows(named=True):
        obs.setdefault(row["comic_id"], []).append(
            [didx[row["date"]], int(row["rank"]) if row["rank"] is not None else None])
        if row["views"]:
            ovs.setdefault(row["comic_id"], []).append([didx[row["date"]], int(row["views"])])

    # episode kpis + per-episode series
    epk = {}
    ekp = os.path.join(GOLD, "episode_kpis.parquet")
    if os.path.exists(ekp):
        epk = {r["comic_id"]: r for r in pl.read_parquet(ekp).iter_rows(named=True)}
    epseries: dict[str, list] = {}
    if os.path.exists(EPISODES):
        e = pl.read_parquet(EPISODES).filter(pl.col("episode_no").is_not_null())
        for (cid,), sub in e.group_by(["comic_id"]):
            s = sub.sort("episode_no")
            epseries[cid] = [[int(n), int(l or 0)] for n, l in
                             zip(s["episode_no"].to_list(), s["likes"].to_list())]

    # art style (palette + style name)
    art = {}
    ap = os.path.join(GOLD, "art_style.parquet")
    if os.path.exists(ap):
        art = {r["real_id"]: r for r in pl.read_parquet(ap).iter_rows(named=True)}

    csmap = {r["comic_id"]: r for r in cs.iter_rows(named=True)}
    # cross-source verification layer (AniList + Wikipedia) — per-field value,
    # confidence + provenance + last_verified. Absent until verify_sources runs.
    vmap = {}
    vpath = os.path.join(GOLD, "verified_profile.parquet")
    if os.path.exists(vpath):
        vmap = {r["comic_id"]: r for r in pl.read_parquet(vpath).iter_rows(named=True)}
    covers = build_cover_map(max_covers)
    print(f"  covers embedded: {len(covers)} · palettes: {len(art)} · "
          f"episode-series: {len(epseries)}")

    comics = []
    for r in ft.iter_rows(named=True):
        cid = r["comic_id"]
        c = {
            "t": r["title"], "s": sidx[r["source"]], "g": r["genre"], "a": r["author"],
            "ct": 0 if r["content_type"] == "comic" else 1,
            "br": r["best_rank"], "lr": r["latest_rank"],
            "v": int(r["views"] or 0), "sub": int(r["subscribers"]) if r["subscribers"] else None,
            "lk": int(r["likes"] or 0), "rt": _r(r["rating"], 1),
            "cm": int(r["comments"]) if r["comments"] else 0, "pb": r["publisher"] or "",
            "lt": _r((r["like_through"] or 0) * 100, 1),
            "er": _r(r["est_usd"]), "ps": _r(r["plotscore"], 1),
            "o": obs.get(cid, []),
        }
        ov = ovs.get(cid)
        if ov and len({d for d, _ in ov}) >= 2:   # need ≥2 distinct dates for a growth line
            c["ov"] = ov
        if r.get("synopsis"):
            c["syn"] = r["synopsis"][:600]
        if r.get("status"):
            c["stt"] = r["status"]
        if r.get("tags"):
            tg = [t for t in r["tags"] if t][:14]
            if tg:
                c["tg"] = tg
        if r["plotscore"] is not None:
            c["psb"] = [_r((r[k] or 0) * 100) for k in
                        ("reach_pct", "momentum_pct", "engagement_pct",
                         "monetization_pct", "quality_pct")]
        if cid in covers:
            c["cv"] = covers[cid]
        # episode block
        ek = epk.get(cid)
        if ek:
            c["epn"] = int(ek["episodes"]) if ek.get("episodes") else None
            c["epl"] = _r(ek.get("avg_ep_likes"))
            c["epw"] = _r(ek.get("episodes_per_week"), 2)
        if cid in epseries and len(epseries[cid]) > 1:
            c["eps"] = epseries[cid]
        # content structure
        cst = csmap.get(cid)
        if cst and cst.get("units") is not None:
            c["un"] = int(cst["units"])
            c["ut"] = cst["unit_type"]
            if cst.get("chapters_per_volume") is not None:
                c["cpv"] = _r(cst["chapters_per_volume"], 1)
            if cst.get("engagement_decay_pct") is not None:
                c["dec"] = _r(cst["engagement_decay_pct"], 1)
        # painting style
        a = art.get(cid)
        if a and a.get("palette"):
            c["pal"] = list(a["palette"])[:6]
            c["st"] = a.get("style_name")
        # cross-source verification: attach provenance/confidence + fill gaps
        v = vmap.get(cid)
        if v:
            vf = {"lv": (v.get("last_verified") or "")[:10],
                  "sc": v.get("ext_score"), "pop": v.get("ext_popularity"),
                  "fav": v.get("ext_favourites"),
                  "al": v.get("anilist_url"), "wk": v.get("wikipedia_url"),
                  "ms": v.get("match_score")}
            if v.get("author"):
                vf["au"] = {"v": v["author"], "c": v.get("author_conf"), "s": list(v.get("author_sources") or [])}
            if v.get("genre"):
                vf["ge"] = {"v": v["genre"], "c": v.get("genre_conf"), "s": list(v.get("genre_sources") or [])}
            if v.get("synopsis"):
                vf["sy"] = {"v": v["synopsis"][:600], "c": v.get("synopsis_conf"), "s": list(v.get("synopsis_sources") or [])}
            if v.get("style_tags"):
                vf["stg"] = list(v["style_tags"])[:8]
            c["vf"] = vf
            # fill only-missing official fields from reliable external values
            # (never overwrite a scraped value; keep the official as source of truth)
            if not c.get("a") and v.get("author") and v.get("author_conf") in ("verified", "single_source"):
                c["a"] = v["author"]
            if not c.get("g") and v.get("genre") and v.get("genre_conf") in ("verified", "single_source"):
                c["g"] = v["genre"]
            if not c.get("syn") and v.get("synopsis"):
                c["syn"] = v["synopsis"][:600]
        # canonical genre: translate Korean/abbreviations -> English subgenre +
        # a parent "larger genre" bucket (for the hierarchy graph & filters).
        gen_en, gpar = normalize_genre(c.get("g"))
        c["g"] = gen_en
        if gpar:
            c["gp"] = gpar
        comics.append(c)

    # content-structure rollup (market-level unit stats)
    have = cs.filter(pl.col("units").is_not_null())
    by_plat = (have.group_by("source").agg(
        pl.col("unit_type").first(), pl.col("units").mean().round(0).alias("avg"),
        pl.col("units").max().alias("mx"), pl.len().alias("n")).sort("avg", descending=True))
    by_type = (have.group_by("content_type", "unit_type").agg(
        pl.col("units").mean().round(0).alias("avg"), pl.col("units").median().alias("med"),
        pl.col("units").sum().alias("tot"), pl.len().alias("n")).sort("n", descending=True))
    ust = {
        "byPlat": [[PLAT_NAMES.get(r["source"], r["source"]), r["unit_type"], int(r["avg"]),
                    int(r["mx"]), int(r["n"])] for r in by_plat.iter_rows(named=True)],
        "byType": [[("Web novel" if r["content_type"] == "novel" else "Web comic"),
                    r["unit_type"], int(r["avg"]), int(r["med"]), int(r["tot"]), int(r["n"])]
                   for r in by_type.iter_rows(named=True)],
        "titles": have.height, "total": int(have["units"].sum() or 0),
    }
    # restricted / inaccessible titles: indexed from namu wiki, flagged like a
    # classified file — existence only, no metrics (the platform blocks scraping).
    rt_path = os.path.join(GOLD, "restricted_titles.parquet")
    if os.path.exists(rt_path):
        for r in pl.read_parquet(rt_path).iter_rows(named=True):
            s = r["source"]
            if s not in sidx:
                srcs.append(s)
                sidx[s] = len(srcs) - 1
            comics.append({
                "t": r["title"], "s": sidx[s], "g": None, "a": None, "ct": 1,
                "br": None, "lr": None, "v": 0, "lk": 0, "cm": 0, "pb": "",
                "ps": None, "o": [], "rx": 1, "rxr": r.get("restricted_reason"),
                "rxu": r.get("ref_url"), "rxv": (r.get("fetched_at") or "")[:10],
            })

    # genre hierarchy: parent "larger genre" -> {subgenre: count} for the graph
    from collections import defaultdict
    _tree = defaultdict(lambda: defaultdict(int))
    for c in comics:
        if c.get("gp") and c.get("g"):
            _tree[c["gp"]][c["g"]] += 1
    genre_tree = {p: dict(sorted(sub.items(), key=lambda kv: -kv[1]))
                  for p, sub in sorted(_tree.items(), key=lambda kv: -sum(kv[1].values()))}

    catalog = {"tables": cat_tables, "built": datetime.date.today().isoformat(),
               "silver_files": None,
               "verified_built": datetime.date.today().isoformat() if vmap else None,
               "verified_count": len(vmap)}
    return {"srcs": srcs, "dates": dates, "comics": comics, "UST": ust,
            "catalog": catalog, "genre_tree": genre_tree}


def build(out_html: str, max_covers: int = 300, mode: str = "embedded",
          data_url: str | None = None) -> None:
    print(f"Building explorer ({mode}) from warehouse...")
    data = build_data(max_covers)
    data_json = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    out_dir = os.path.dirname(out_html) or "."
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "explorer_data.json"), "w", encoding="utf-8") as f:
        f.write(data_json)

    tpl = open(os.path.join(ASSETS, "template.html"), encoding="utf-8").read()
    fonts = open(os.path.join(ASSETS, "fonts.css"), encoding="utf-8").read()
    # embedded = a self-contained snapshot; api = a small shell that fetches the
    # published explorer_data.json at runtime (for a Vercel-hosted live front-end).
    if mode == "api":
        if not data_url:
            raise SystemExit("--mode api requires --data-url (URL of the published explorer_data.json)")
        boot = ("fetch(%s).then(function(r){return r.json();}).then(boot)"
                ".catch(function(e){document.body.innerHTML="
                "'<p style=\"padding:48px;font:15px system-ui\">Couldn\\u2019t load data \\u2014 '+e+'</p>';});"
                % json.dumps(data_url))
    else:
        boot = "boot(%s);" % data_json
    html = tpl.replace("/*__FONTS__*/", fonts, 1).replace("/*__BOOT__*/", boot, 1)
    with open(out_html, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  titles: {len(data['comics'])} · sources: {len(data['srcs'])} · "
          f"dates: {len(data['dates'])} · unit-structured: {data['UST']['titles']}")
    print(f"Explorer built → {out_html} ({len(html):,} bytes)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Build the Plotline explorer artifact.")
    ap.add_argument("--covers", type=int, default=300, help="max embedded cover thumbnails")
    ap.add_argument("--out", default=os.path.join(_ROOT, "reports", "leesearch_explorer.html"),
                    help="output HTML path")
    ap.add_argument("--mode", choices=["embedded", "api"], default="embedded",
                    help="embedded = self-contained snapshot; api = fetches published data at runtime")
    ap.add_argument("--data-url", help="URL of the published explorer_data.json (required for --mode api)")
    args = ap.parse_args()
    build(args.out, args.covers, mode=args.mode, data_url=args.data_url)
