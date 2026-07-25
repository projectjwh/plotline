"""Detail-enrichment crawler (the hardened fetch layer, applied).

Reads the titles already in Silver, fetches each one's **detail page** (where
absolute views / subscribers / likes / ratings live), and lands the HTML in
Bronze as ``comic_detail_*.html`` so the normal parser enriches it. Most
platforms (Tapas, GlobalComix, …) serve these metrics in raw HTML, so this uses
a light ``requests`` path — no browser — with real hardening:

  * exponential backoff + jitter on failure / 429 / 503 (``max_retries``)
  * per-host rate limiting (never hammer one platform)
  * bounded concurrency across hosts (ThreadPoolExecutor)
  * user-agent rotation
  * block/empty detection -> quarantine log, not saved as valid Bronze

It is safe to run partially: targets are ordered by rank, so a capped run
enriches the most important titles first.

Run:
  python -m src.scrapers.detail_crawler --limit 20                 # small sample
  python -m src.scrapers.detail_crawler --source tapas_io          # one platform
  python -m src.scrapers.detail_crawler --all                      # everything
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from urllib.parse import urlsplit

import polars as pl
import requests

from src.scrapers.adapters.base import detect_block

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
SILVER = os.path.join(_ROOT, "data", "silver", "comics")
BRONZE = os.path.join(_ROOT, "data", "bronze")
QUARANTINE = os.path.join(_ROOT, "data", "quarantine")

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
]


class RateLimiter:
    """Enforce a minimum (jittered) interval between requests to the same host."""

    def __init__(self, min_delay: float, max_delay: float):
        self.min, self.max = min_delay, max_delay
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, host: str) -> None:
        with self._lock:
            now = time.monotonic()
            wait = self._last.get(host, 0) + random.uniform(self.min, self.max) - now
            if wait > 0:
                time.sleep(wait)
            self._last[host] = time.monotonic()


class DetailCrawler:
    def __init__(self, delay=(1.5, 3.5), max_retries=3, concurrency=4, timeout=20):
        self.limiter = RateLimiter(*delay)
        self.max_retries = max_retries
        self.concurrency = concurrency
        self.timeout = timeout
        self.session = requests.Session()

    # -- target selection --
    def targets(self, source=None, limit=None, only_missing=True) -> list[dict]:
        files = glob.glob(os.path.join(SILVER, "**", "*.parquet"), recursive=True)
        if not files:
            return []
        df = pl.scan_parquet(files, hive_partitioning=False).drop("tags").collect()
        df = df.filter(pl.col("url").is_not_null())
        if source:
            df = df.filter(pl.col("source") == source)
        if only_missing:
            df = df.filter((pl.col("views") == 0) & (pl.col("subscribers").fill_null(0) == 0))
        # one row per title, most important (best rank) first
        df = (df.sort("rank", nulls_last=True)
                .unique(subset=["comic_id"], keep="first")
                .sort("rank", nulls_last=True))
        if limit:
            df = df.head(limit)
        return df.select(["source", "comic_id", "title", "url", "rank"]).to_dicts()

    # -- hardened fetch --
    def fetch(self, url: str) -> tuple[str | None, str]:
        host = urlsplit(url).netloc
        for attempt in range(self.max_retries + 1):
            self.limiter.wait(host)
            try:
                r = self.session.get(
                    url, timeout=self.timeout,
                    headers={"User-Agent": random.choice(USER_AGENTS),
                             "Accept": "text/html,application/xhtml+xml"},
                )
                if r.status_code == 200:
                    reason = detect_block(r.text)
                    return (None, reason) if reason else (r.text, "ok")
                if r.status_code in (429, 500, 502, 503):
                    time.sleep((2 ** attempt) + random.uniform(0, 1))  # backoff
                    continue
                return None, f"http_{r.status_code}"
            except requests.RequestException as e:
                if attempt == self.max_retries:
                    return None, f"error:{type(e).__name__}"
                time.sleep((2 ** attempt) + random.uniform(0, 1))
        return None, "max_retries"

    def _save(self, source: str, html: str, idx: int) -> None:
        day = datetime.now().strftime("%Y-%m-%d")
        out_dir = os.path.join(BRONZE, source, day)
        os.makedirs(out_dir, exist_ok=True)
        ts = int(time.time()) + idx  # unique, 10-digit -> parser reads scraped_at
        with open(os.path.join(out_dir, f"comic_detail_{ts}.html"), "w", encoding="utf-8") as f:
            f.write(html)

    # -- orchestrate --
    def crawl(self, targets: list[dict]) -> dict:
        stats = {"ok": 0, "blocked": 0, "failed": 0}
        quarantine = []
        print(f"Crawling {len(targets)} detail pages "
              f"(concurrency={self.concurrency}, retries={self.max_retries})...")

        def work(i_t):
            i, t = i_t
            html, reason = self.fetch(t["url"])
            if html:
                self._save(t["source"], html, i)
                return "ok", t, reason
            return ("blocked" if reason.startswith(("block", "too_small")) else "failed"), t, reason

        with ThreadPoolExecutor(max_workers=self.concurrency) as ex:
            futures = [ex.submit(work, it) for it in enumerate(targets)]
            for n, fut in enumerate(as_completed(futures), 1):
                status, t, reason = fut.result()
                stats[status] += 1
                if status != "ok":
                    quarantine.append({"source": t["source"], "url": t["url"], "reason": reason})
                if n % 25 == 0 or n == len(targets):
                    print(f"  {n}/{len(targets)}  ok={stats['ok']} "
                          f"blocked={stats['blocked']} failed={stats['failed']}")

        if quarantine:
            os.makedirs(QUARANTINE, exist_ok=True)
            path = os.path.join(QUARANTINE, f"detail_crawl_{datetime.now():%Y-%m-%d}.jsonl")
            with open(path, "w", encoding="utf-8") as f:
                for q in quarantine:
                    f.write(json.dumps(q, ensure_ascii=False) + "\n")
        return stats


def run(source=None, limit=None, only_missing=True, **kw) -> dict:
    crawler = DetailCrawler(**kw)
    targets = crawler.targets(source=source, limit=limit, only_missing=only_missing)
    if not targets:
        print("No detail targets (need Silver titles with a url and no metric yet).")
        return {"ok": 0, "blocked": 0, "failed": 0}
    stats = crawler.crawl(targets)
    print(f"\nDone. Saved {stats['ok']} detail pages to Bronze. "
          f"Re-run 'python -m src.pipelines.parser' to enrich Silver.")
    return stats


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Fetch detail pages to enrich Silver metrics.")
    ap.add_argument("--source", help="limit to one platform (e.g. tapas_io)")
    ap.add_argument("--limit", type=int, default=25, help="max titles (default 25; use --all for no cap)")
    ap.add_argument("--all", action="store_true", help="crawl every eligible title (overrides --limit)")
    ap.add_argument("--refresh", action="store_true", help="re-crawl even titles that already have metrics")
    ap.add_argument("--concurrency", type=int, default=4)
    args = ap.parse_args()
    run(source=args.source, limit=None if args.all else args.limit,
        only_missing=not args.refresh, concurrency=args.concurrency)
