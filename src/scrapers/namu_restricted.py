"""Index titles we can't scrape directly, from namu wiki category pages.

Some platforms block automated access (munpia serves an apology page; toomics is
login-gated). We can still surface the *existence* of their titles by reading a
namu-wiki category listing, and mark each in the profile as inaccessible — like
a classified file — instead of pretending we have data. We deliberately go no
deeper than the title (no episode/metric scraping).

Output: ``data/gold/restricted_titles.parquet`` — one row per indexed title with
``restricted=True``, the reason, the namu-wiki reference url, and a fetch stamp.

Run:  python -m src.scrapers.namu_restricted
"""
from __future__ import annotations

import os
import re
import time
from datetime import datetime, timezone
from urllib.parse import unquote, quote

import polars as pl
import requests

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
GOLD = os.path.join(_ROOT, "data", "gold")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

# (source, reason, category-page url). en.namu.wiki gives English-ish titles.
SOURCES = [
    ("munpia", "Munpia blocks automated access (serves an apology page); title "
               "indexed via namu wiki — platform metrics are inaccessible.",
     "https://en.namu.wiki/w/" + quote("분류:문피아/작품")),
]

# namespaced links (분류:/나무위키:/파일:/틀: …) and platform/site names are not works.
_DENY = re.compile(r"(namu|wiki|category|분류|나무위키|파일|틀|kakao|naver|munpia|문피아|"
                   r"series|시리즈|페이지|ridibooks|리디|template|main page|대문)", re.I)
_ANCHOR = re.compile(r"<a[^>]+href=[\"']/w/([^\"'?#]+)[\"'][^>]*?title=[\"']([^\"']+)[\"']", re.I)


def _fetch(url: str) -> str | None:
    for attempt in range(3):
        try:
            r = requests.get(url, timeout=25, headers={"User-Agent": UA, "Accept-Language": "en,ko;q=0.9"})
            if r.status_code == 200 and len(r.text) > 20000:
                return r.text
        except requests.RequestException:
            pass
        time.sleep(2 ** attempt)
    return None


def _extract_works(html: str) -> list[tuple[str, str]]:
    """(slug, title) for anchors that look like member works, de-duplicated."""
    out, seen = [], set()
    for slug, title in _ANCHOR.findall(html):
        dslug = unquote(slug)
        title = title.strip()
        if ":" in dslug or "/" in dslug:      # namespaced (분류:, 나무위키:) — not a work
            continue
        if _DENY.search(dslug) or _DENY.search(title):
            continue
        if len(title) < 2 or title.lower() in seen:
            continue
        seen.add(title.lower())
        out.append((dslug, title))
    return out


def run() -> dict:
    rows = []
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for source, reason, url in SOURCES:
        html = _fetch(url)
        if not html:
            print(f"  {source}: category page unreachable ({url})")
            continue
        works = _extract_works(html)
        print(f"  {source}: indexed {len(works)} titles from namu wiki")
        for slug, title in works:
            rows.append({
                "comic_id": f"{source}:namu:{slug}",
                "source": source, "title": title,
                "restricted": True, "restricted_reason": reason,
                "ref_url": "https://en.namu.wiki/w/" + quote(slug),
                "fetched_at": now,
            })
    if rows:
        os.makedirs(GOLD, exist_ok=True)
        pl.DataFrame(rows).write_parquet(os.path.join(GOLD, "restricted_titles.parquet"))
        print(f"\nWrote {len(rows)} restricted titles -> data/gold/restricted_titles.parquet")
    else:
        print("No restricted titles indexed.")
    return {"count": len(rows)}


if __name__ == "__main__":
    run()
