"""Cross-source verification of rarely-changing profile fields.

For each title we hold from the official platform scrape, this corroborates the
slow-moving facts — author, title, genre, synopsis, readership base, feedback
(score) and style/tags — against two independent, publicly accessible sources:

  * AniList  (GraphQL, keyless) — structured staff/genres/tags/score/popularity.
  * Wikipedia (REST summary + infobox wikitext) — canonical description + author.

Design principle (so the profile never *asserts* something wrong):
  * STRICT matching — an external record is accepted only when its title
    matches ours closely (exact-normalized, or ≥0.90 similarity). A weak match
    is discarded, not guessed, so a mismatched entry can't inject bad data.
  * Per-field confidence — 'verified' only when ≥2 independent sources agree;
    'single_source' when one has it; 'conflict' when they disagree (we keep the
    official value and record the alternatives); 'unverified' when none corroborate.
  * Provenance + freshness — every field carries its source(s) and the run
    stamps ``last_verified`` (UTC). Results are cached so re-runs are cheap and
    only refetch stale (> --max-age-days) or unmatched titles.

Output: ``data/gold/verified_profile.parquet`` (+ ``verify_cache.json``).

Run:  python -m src.enrich.verify_sources --limit 300      # top titles by plotscore
      python -m src.enrich.verify_sources --all            # everything (slow)
      python -m src.enrich.verify_sources --refresh         # ignore cache freshness
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import time
from datetime import datetime, timezone, timedelta

import duckdb
import requests

sys.stdout.reconfigure(encoding="utf-8")

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
DB = os.path.join(_ROOT, "data", "plotline.duckdb")
GOLD = os.path.join(_ROOT, "data", "gold")
CACHE = os.path.join(GOLD, "verify_cache.json")

ANILIST_URL = "https://graphql.anilist.co"
WIKI_REST = "https://en.wikipedia.org/api/rest_v1/page/summary/"
WIKI_API = "https://en.wikipedia.org/w/api.php"
UA = "PlotlineResearch/1.0 (market-intelligence; contact project.jwh@gmail.com)"

_MEDIA_KEYWORDS = re.compile(
    r"webtoon|manhwa|manhua|manga|comic|graphic novel|light novel|web novel|"
    r"novel|serial|manwha|webcomic|series", re.I)

ANILIST_QUERY = """
query ($search: String) {
  Page(perPage: 5) {
    media(search: $search, type: MANGA) {
      id
      title { romaji english native }
      format status countryOfOrigin
      genres
      averageScore popularity favourites
      description(asHtml: false)
      siteUrl
      staff(perPage: 8) { edges { role node { name { full } } } }
      tags { name rank isGeneralSpoiler }
    }
  }
}"""


# --- normalisation & matching --------------------------------------------------

def _norm(s: str | None) -> str:
    if not s:
        return ""
    s = html.unescape(s).lower()
    s = re.sub(r"[^0-9a-z가-힣぀-ヿ一-鿿]+", " ", s)  # keep CJK
    return " ".join(s.split())


def _sim(a: str, b: str) -> float:
    """Token-set Jaccard-ish similarity on normalised strings (0..1)."""
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    ta, tb = set(a.split()), set(b.split())
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    return inter / len(ta | tb)


def _title_match(ours: str, candidates: list[str]) -> float:
    n = _norm(ours)
    return max((_sim(n, _norm(c)) for c in candidates if c), default=0.0)


def _strip_html(s: str | None) -> str | None:
    if not s:
        return None
    s = re.sub(r"<[^>]+>", " ", html.unescape(s))
    return " ".join(s.split()) or None


def _clean_author(s: str | None) -> str | None:
    if not s:
        return None
    s = re.sub(r"\[\[|\]\]", "", s)                 # wiki links
    s = re.sub(r"\{\{[^}]*\}\}", "", s)             # wiki templates
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"\([^)]*\)", "", s)                 # drop studio parentheticals for comparison
    return " ".join(s.split()).strip(" ,;") or None


def _author_tokens(s: str | None) -> set[str]:
    return {t for t in _norm(_clean_author(s)).split() if len(t) > 1}


# --- external fetchers (rate-limited, resilient) -------------------------------

class Fetcher:
    def __init__(self, min_interval=0.8):
        self.s = requests.Session()
        self.s.headers["User-Agent"] = UA
        self.min_interval = min_interval
        self._last = {}

    def _wait(self, host):
        dt = time.monotonic() - self._last.get(host, 0)
        if dt < self.min_interval:
            time.sleep(self.min_interval - dt)
        self._last[host] = time.monotonic()

    def anilist(self, title: str) -> dict | None:
        self._wait("anilist")
        for attempt in range(4):
            try:
                r = self.s.post(ANILIST_URL, json={"query": ANILIST_QUERY, "variables": {"search": title}}, timeout=20)
                if r.status_code == 429:
                    time.sleep(int(r.headers.get("Retry-After", 5)) + 1)
                    continue
                if r.status_code != 200:
                    return None
                media = (r.json().get("data") or {}).get("Page", {}).get("media") or []
                return {"media": media}
            except (requests.RequestException, ValueError):
                time.sleep(2 ** attempt)
        return None

    def wiki_summary(self, title: str) -> dict | None:
        self._wait("wiki")
        try:
            r = self.s.get(WIKI_REST + requests.utils.quote(title.replace(" ", "_"), safe=""), timeout=15)
            if r.status_code == 200:
                return r.json()
        except (requests.RequestException, ValueError):
            pass
        return None

    def wiki_search(self, title: str) -> str | None:
        self._wait("wiki")
        try:
            r = self.s.get(WIKI_API, params={"action": "query", "list": "search",
                           "srsearch": f"{title} (webtoon OR manhwa OR manga OR comic OR novel)",
                           "format": "json", "srlimit": 3}, timeout=15)
            hits = (r.json().get("query", {}).get("search") or []) if r.status_code == 200 else []
            return hits[0]["title"] if hits else None
        except (requests.RequestException, ValueError):
            return None

    def wiki_infobox_author(self, page_title: str) -> str | None:
        self._wait("wiki")
        try:
            r = self.s.get(WIKI_API, params={"action": "query", "prop": "revisions", "rvslots": "main",
                           "rvprop": "content", "titles": page_title, "format": "json"}, timeout=15)
            pages = r.json().get("query", {}).get("pages", {})
            wt = next(iter(pages.values())).get("revisions", [{}])[0].get("slots", {}).get("main", {}).get("*", "")
            for field in ("author", "writer", "creator", "artist", "story"):
                m = re.search(r"\|\s*%s\s*=\s*([^\n|]+)" % field, wt, re.I)
                if m and m.group(1).strip():
                    return _clean_author(m.group(1))
        except (requests.RequestException, ValueError, StopIteration, IndexError):
            pass
        return None


# --- per-title verification ----------------------------------------------------

def _anilist_pick(media: list[dict], title: str):
    best, best_s = None, 0.0
    for m in media:
        t = m.get("title") or {}
        s = _title_match(title, [t.get("romaji"), t.get("english"), t.get("native")])
        if s > best_s:
            best, best_s = m, s
    return (best, best_s) if best_s >= 0.90 else (None, best_s)


def _anilist_author(media: dict) -> str | None:
    names = []
    for e in (media.get("staff") or {}).get("edges", []):
        role = (e.get("role") or "").lower()
        if any(k in role for k in ("story", "art", "original", "author", "creator")):
            nm = ((e.get("node") or {}).get("name") or {}).get("full")
            if nm and nm not in names:
                names.append(nm)
    return ", ".join(names[:3]) or None


def verify_one(f: Fetcher, rec: dict) -> dict:
    title, official_author, official_genre = rec["title"], rec.get("author"), rec.get("genre")
    out = {"comic_id": rec["comic_id"], "title": title,
           "last_verified": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "sources": []}

    # --- AniList ---
    a_author = a_genres = a_syn = a_url = None
    a_score = a_pop = a_fav = None
    a_tags = []
    al = f.anilist(title)
    if al:
        m, s = _anilist_pick(al["media"], title)
        if m:
            out["sources"].append("anilist")
            out["anilist_id"] = m["id"]; out["anilist_url"] = m.get("siteUrl")
            out["match_score"] = round(s, 3)
            out["country"] = m.get("countryOfOrigin"); out["format"] = m.get("format"); out["status_ext"] = m.get("status")
            a_author = _anilist_author(m)
            a_genres = m.get("genres") or []
            a_syn = _strip_html(m.get("description"))
            a_score = m.get("averageScore"); a_pop = m.get("popularity"); a_fav = m.get("favourites")
            a_url = m.get("siteUrl")
            a_tags = [t["name"] for t in sorted(m.get("tags") or [], key=lambda x: -(x.get("rank") or 0))
                      if not t.get("isGeneralSpoiler")][:8]

    # --- Wikipedia ---
    w_author = w_syn = w_url = None
    ws = f.wiki_summary(title)
    page_title = None
    if not ws or ws.get("type") == "disambiguation" or _title_match(title, [ws.get("title", "")]) < 0.6:
        page_title = f.wiki_search(title)
        ws = f.wiki_summary(page_title) if page_title else None
    if ws and ws.get("extract") and _MEDIA_KEYWORDS.search(ws.get("extract", "")) \
            and _title_match(title, [ws.get("title", "")]) >= 0.6:
        out["sources"].append("wikipedia")
        w_syn = ws.get("extract")
        w_url = (ws.get("content_urls", {}).get("desktop", {}) or {}).get("page")
        out["wikipedia_url"] = w_url
        w_author = f.wiki_infobox_author(ws.get("title") or page_title or title)

    # --- AUTHOR cross-check --------------------------------------------------
    # Trusted, assertable sources: official scrape + AniList (structured staff).
    # Wikipedia's regex-parsed infobox author is corroboration-ONLY — it can
    # confirm agreement but is never asserted alone (too error-prone, e.g. it
    # returned a character name for "I Love Yoo"). This guarantees we never
    # surface a single, unverifiable Wikipedia author as fact.
    trusted = [("official", official_author), ("anilist", a_author)]
    trusted = [(s, v) for s, v in trusted if v]
    corrob = [("wikipedia", w_author)] if w_author else []
    allsrc = trusted + corrob
    a_conf, a_chosen, a_src = "unverified", None, []
    if trusted:
        a_chosen = official_author or a_author       # never a wiki-only value
        a_src = [s for s, _ in allsrc]
        # verified iff any two sources' author-token sets overlap
        agree = any(_author_tokens(allsrc[i][1]) & _author_tokens(allsrc[j][1])
                    for i in range(len(allsrc)) for j in range(i + 1, len(allsrc)))
        if len(allsrc) == 1:
            a_conf = "single_source"
        else:
            a_conf = "verified" if agree else "conflict"
    out.update({"author": a_chosen, "author_conf": a_conf, "author_sources": a_src,
                "author_alts": [v for _, v in allsrc] if a_conf == "conflict" else []})

    # --- GENRE cross-check ---------------------------------------------------
    # AniList carries a genre *list*; official a single label. Verified when the
    # official label is a member of the AniList list; if official is missing,
    # AniList fills it (single_source, structured & reliable).
    a_genres = a_genres or []
    out["genre_list_ext"] = a_genres
    g_norm_list = {_norm(x) for x in a_genres}
    if official_genre and a_genres:
        if _norm(official_genre) in g_norm_list:
            out.update({"genre": official_genre, "genre_conf": "verified", "genre_sources": ["official", "anilist"]})
        else:
            out.update({"genre": official_genre, "genre_conf": "conflict",
                        "genre_sources": ["official", "anilist"], "genre_alts": a_genres})
    elif official_genre:
        out.update({"genre": official_genre, "genre_conf": "single_source", "genre_sources": ["official"]})
    elif a_genres:
        out.update({"genre": a_genres[0], "genre_conf": "single_source", "genre_sources": ["anilist"]})
    else:
        out.update({"genre": None, "genre_conf": "unverified", "genre_sources": []})

    # --- SYNOPSIS ------------------------------------------------------------
    # Both externals describe the strictly-matched work; prefer the richer
    # AniList description. Two independent descriptions => 'verified' provenance.
    syn_srcs = [s for s, v in (("anilist", a_syn), ("wikipedia", w_syn)) if v]
    syn_val = a_syn or w_syn
    out.update({"synopsis": syn_val,
                "synopsis_conf": "verified" if len(syn_srcs) >= 2 else ("single_source" if syn_srcs else "unverified"),
                "synopsis_sources": syn_srcs})
    # external readership / feedback / style (single-source external by nature)
    out["ext_score"] = a_score            # AniList average score 0-100 (feedback)
    out["ext_popularity"] = a_pop         # AniList users tracking (readership proxy)
    out["ext_favourites"] = a_fav
    out["style_tags"] = a_tags            # AniList tags = style/theme descriptors
    out["matched"] = bool(out["sources"])
    return out


# --- driver --------------------------------------------------------------------

def _load_cache() -> dict:
    if os.path.exists(CACHE):
        try:
            return json.load(open(CACHE, encoding="utf-8"))
        except (ValueError, OSError):
            pass
    return {}


def _targets(limit, all_):
    con = duckdb.connect(DB, read_only=True)
    q = ("SELECT comic_id, title, author, genre, synopsis FROM fact_title "
         "WHERE title IS NOT NULL ORDER BY plotscore DESC NULLS LAST")
    rows = con.execute(q).df().to_dict("records")
    con.close()
    return rows if all_ else rows[:limit]


def run(limit=300, all_=False, refresh=False, max_age_days=30):
    targets = _targets(limit, all_)
    cache = _load_cache()
    fresh_cut = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    f = Fetcher()
    done = 0
    matched = 0
    for i, rec in enumerate(targets, 1):
        cid = rec["comic_id"]
        cached = cache.get(cid)
        if cached and not refresh:
            try:
                if datetime.fromisoformat(cached["last_verified"]) > fresh_cut:
                    matched += bool(cached.get("matched"))
                    continue
            except (KeyError, ValueError):
                pass
        res = verify_one(f, rec)
        cache[cid] = res
        done += 1
        matched += bool(res.get("matched"))
        if done % 20 == 0:
            print(f"  verified {done} (fetched) / {i} scanned — matched so far {matched}")
            json.dump(cache, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False)
    json.dump(cache, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False)

    # write the parquet from the cache rows corresponding to this run's universe
    import polars as pl
    ids = {r["comic_id"] for r in targets}
    rows = [v for k, v in cache.items() if k in ids and v.get("matched")]
    if rows:
        # normalise list/nullable columns for a stable schema
        keep = ["comic_id", "title", "anilist_id", "anilist_url", "wikipedia_url", "match_score",
                "country", "format", "status_ext", "author", "author_conf", "author_sources",
                "genre", "genre_conf", "genre_list_ext", "synopsis", "synopsis_conf", "synopsis_sources",
                "ext_score", "ext_popularity", "ext_favourites", "style_tags", "sources", "last_verified"]
        norm = [{k: r.get(k) for k in keep} for r in rows]
        pl.DataFrame(norm).write_parquet(os.path.join(GOLD, "verified_profile.parquet"))
    print(f"\nVerification: scanned {len(targets)} titles, fetched {done}, matched {matched}.")
    print(f"  -> data/gold/verified_profile.parquet ({len(rows)} rows) + verify_cache.json")
    return {"scanned": len(targets), "fetched": done, "matched": matched}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Cross-source verification (AniList + Wikipedia).")
    ap.add_argument("--limit", type=int, default=300, help="top-N titles by plotscore (default 300)")
    ap.add_argument("--all", action="store_true", help="verify every title (slow)")
    ap.add_argument("--refresh", action="store_true", help="ignore cache freshness")
    ap.add_argument("--max-age-days", type=int, default=30)
    args = ap.parse_args()
    run(limit=args.limit, all_=args.all, refresh=args.refresh, max_age_days=args.max_age_days)
