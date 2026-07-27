"""Requests-based listing fetcher for server-rendered platforms.

``scraper_core`` uses Playwright, but several sites are fetched more reliably
(or *only*) with plain ``requests``: RoyalRoad is fully server-rendered yet
fails under the Playwright path, while other listings never hydrate their data
into the DOM snapshot. This fetches a platform's configured listing URL(s) over
a hardened requests path and lands them in Bronze as ``daily_schedule_*.html``,
where the normal adapter/parser picks them up.

It reports, per source, whether the fetched HTML is usable (``ok``) or a
blocked/empty shell (``too_small`` / ``block_marker`` / an SPA with no server
data) — so it doubles as a feasibility probe for the dark platforms.

Run:
  python -m src.scrapers.listing_fetch --source royalroad
  python -m src.scrapers.listing_fetch --all          # every configured target
  python -m src.scrapers.listing_fetch --dark         # only the no-adapter set
"""
from __future__ import annotations

import argparse
import os
import random
import time
from datetime import datetime

import requests
import yaml

from src.scrapers.adapters.base import detect_block

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
BRONZE = os.path.join(_ROOT, "data", "bronze")
CONFIG = yaml.safe_load(open(os.path.join(_ROOT, "config.yaml"), encoding="utf-8"))

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
# Sources whose listings are known to render server-side (requests-friendly).
# bilibilicomics dropped: domain dead (ERR_NAME_NOT_RESOLVED) as of 2026-07-25.
DARK = ["royalroad", "lezhin", "manta", "tappytoon", "toomics", "munpia",
        "joara", "inkitt", "pocket_comics"]

# Paginated server-rendered lists: (url_template, n_pages). Each page is a full
# listing snapshot the adapter parses, so this deepens catalog coverage.
PAGED = {
    "royalroad": ("https://www.royalroad.com/fictions/active-popular?page={}", 15),
}


def _fetch(url: str, retries: int = 3) -> tuple[str | None, str]:
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, timeout=25, headers={
                "User-Agent": UA,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            })
            if r.status_code == 200:
                reason = detect_block(r.text)
                return (None, reason) if reason else (r.text, "ok")
            if r.status_code in (429, 500, 502, 503):
                time.sleep((2 ** attempt) + random.uniform(0, 1))
                continue
            return None, f"http_{r.status_code}"
        except requests.RequestException as e:
            if attempt == retries:
                return None, f"error:{type(e).__name__}"
            time.sleep((2 ** attempt) + random.uniform(0, 1))
    return None, "max_retries"


def _save(source: str, html: str) -> str:
    day = datetime.now().strftime("%Y-%m-%d")
    out_dir = os.path.join(BRONZE, source, day)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"daily_schedule_{int(time.time())}.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path


def run(sources: list[str]) -> dict:
    targets = CONFIG["scraping"]["targets"]
    results = {}
    for src in sources:
        # Paginated deep fetch (RoyalRoad): grab N full listing pages.
        if src in PAGED:
            tmpl, npages = PAGED[src]
            got = 0
            for p in range(1, npages + 1):
                html, reason = _fetch(tmpl.format(p))
                if html:
                    _save(src, html)
                    got += 1
                time.sleep(random.uniform(1.0, 2.0))
            results[src] = "ok" if got else "failed"
            print(f"  {src:16} ok  ({got}/{npages} pages)")
            continue
        cfg = targets.get(src)
        if not cfg or not cfg.get("daily_schedule_url"):
            results[src] = "no_url"
            print(f"  {src:16} no daily_schedule_url in config")
            continue
        html, reason = _fetch(cfg["daily_schedule_url"])
        if html:
            path = _save(src, html)
            results[src] = "ok"
            print(f"  {src:16} ok  ({len(html):>8,}b)  -> {os.path.relpath(path, BRONZE)}")
        else:
            results[src] = reason
            print(f"  {src:16} SKIP ({reason})")
        time.sleep(random.uniform(1.0, 2.5))
    ok = sum(1 for v in results.values() if v == "ok")
    print(f"\n{ok}/{len(sources)} sources fetched usable HTML via requests.")
    return results


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Fetch server-rendered listings via requests.")
    ap.add_argument("--source", help="one source name")
    ap.add_argument("--all", action="store_true", help="every configured target")
    ap.add_argument("--dark", action="store_true", help="only the no-adapter dark platforms")
    args = ap.parse_args()
    if args.source:
        srcs = [args.source]
    elif args.dark:
        srcs = DARK
    elif args.all:
        srcs = list(CONFIG["scraping"]["targets"].keys())
    else:
        srcs = ["royalroad"]
    print(f"Fetching {len(srcs)} listing(s) via requests...")
    run(srcs)
