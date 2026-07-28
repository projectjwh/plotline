"""Data-quality gate — automated correctness checks on the Silver corpus.

Coverage metrics answer "does a field have a value"; this answers "is the value
plausibly *correct*". It codifies the anomaly classes found in the July 2026
audit (author/genre contamination, within-title disagreement, authors
mis-latched onto many unrelated titles) so regressions surface every run
instead of silently shipping to the artifact.

Writes ``data/gold/dq_report_<ts>.json`` + a stable ``dq_report_latest.json``
and prints a per-check scorecard. Exit code is 0 by default (report-only);
``--strict`` exits 1 when any CRITICAL check exceeds its threshold, so it can
gate a release build.

Run:  python -m src.pipelines.dq_checks [--strict]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from datetime import datetime, timezone

import polars as pl

sys.stdout.reconfigure(encoding="utf-8")

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
SILVER = os.path.join(_ROOT, "data", "silver", "comics")
GOLD = os.path.join(_ROOT, "data", "gold")

_METRIC = re.compile(r"\b\d[\d.,]*\s*[KMB]\b|\b(?:views?|likes?|reads?|subscribers?|eps?|episodes?)\b", re.I)
_EP_TOKEN = re.compile(r"화|\bEps\b|episode|^\s*\d", re.I)

# (name, severity, threshold) — a check "fails" (for --strict) when count > threshold.
THRESHOLDS = {
    "title_eq_author": ("CRITICAL", 0),
    "author_has_metric": ("CRITICAL", 0),
    "genre_is_episode_token": ("HIGH", 0),
    "within_title_author_conflict": ("HIGH", 10),
    "within_title_genre_conflict": ("MEDIUM", 25),
    "author_mislatched": ("HIGH", 0),
    "title_leading_badge": ("MEDIUM", 20),
}


def _unique(df: pl.DataFrame) -> pl.DataFrame:
    return df.sort("scraped_at", descending=True).unique(subset=["comic_id"], keep="first")


def _examples(df: pl.DataFrame, cols=("source", "title", "author", "genre"), k=8):
    cols = [c for c in cols if c in df.columns]
    return [{c: r[c] for c in cols} for r in df.select(cols).head(k).iter_rows(named=True)]


def run(strict: bool = False) -> int:
    files = glob.glob(os.path.join(SILVER, "**", "*.parquet"), recursive=True)
    if not files:
        print("No Silver data to check.")
        return 0
    df = pl.scan_parquet(files, hive_partitioning=False).collect()
    u = _unique(df)
    n = u.height
    checks: dict[str, dict] = {}

    def add(name, bad_df):
        sev, thr = THRESHOLDS.get(name, ("INFO", 0))
        cnt = bad_df.height
        checks[name] = {"severity": sev, "count": cnt, "pct": round(100 * cnt / max(n, 1), 3),
                        "threshold": thr, "failed": cnt > thr, "examples": _examples(bad_df)}

    # --- field-contamination checks (on unique titles) ---
    add("title_eq_author", u.filter(pl.col("author").is_not_null() & (pl.col("author") == pl.col("title"))))
    add("author_has_metric", u.filter(pl.col("author").is_not_null() & pl.col("author").str.contains(_METRIC.pattern)))
    add("genre_is_episode_token", u.filter(pl.col("genre").is_not_null() & pl.col("genre").str.contains(_EP_TOKEN.pattern)))
    add("title_leading_badge", u.filter(pl.col("title").str.contains(r"^(?i)(?:up|new|hot|event)\s")))

    # --- within-title disagreement (across all rows, not just latest) ---
    ac = (df.filter(pl.col("author").is_not_null())
            .group_by("comic_id").agg(pl.col("author").n_unique().alias("k"),
                                      pl.col("source").first(), pl.col("title").first(),
                                      pl.col("author").unique().alias("author"))
            .filter(pl.col("k") > 1))
    add("within_title_author_conflict", ac.with_columns(pl.col("author").list.join(" | ").alias("author")))
    gc = (df.filter(pl.col("genre").is_not_null())
            .group_by("comic_id").agg(pl.col("genre").n_unique().alias("k"),
                                      pl.col("source").first(), pl.col("title").first(),
                                      pl.col("genre").unique().alias("genre"))
            .filter(pl.col("k") > 1))
    add("within_title_genre_conflict", gc.with_columns(pl.col("genre").list.join(" | ").alias("genre")))

    # --- author mis-latched onto many distinct titles within a source ---
    ml = (u.filter(pl.col("author").is_not_null())
            .group_by(["source", "author"]).agg(pl.col("title").n_unique().alias("n_titles"))
            .filter(pl.col("n_titles") >= 8)
            .sort("n_titles", descending=True))
    add("author_mislatched", ml.rename({"n_titles": "genre"}) if "genre" not in ml.columns else ml)

    # --- completeness context (informational) ---
    coverage = {}
    for (src,), g in u.group_by("source"):
        coverage[src] = {"titles": g.height,
                         "author_pct": round(100 * g["author"].is_not_null().mean(), 1),
                         "genre_pct": round(100 * g["genre"].is_not_null().mean(), 1),
                         "synopsis_pct": round(100 * g["synopsis"].is_not_null().mean(), 1)}

    report = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "unique_titles": n, "checks": checks, "coverage_by_source": coverage}
    os.makedirs(GOLD, exist_ok=True)
    ts = int(datetime.now().timestamp())
    with open(os.path.join(GOLD, f"dq_report_{ts}.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    with open(os.path.join(GOLD, "dq_report_latest.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)

    print(f"Data-quality gate — {n} unique titles\n{'-'*54}")
    failed_critical = 0
    for name, c in sorted(checks.items(), key=lambda kv: (kv[1]["severity"], -kv[1]["count"])):
        mark = "✗" if c["failed"] else "✔"
        print(f"  {mark} {c['severity']:8} {name:32} {c['count']:>5}  (thr {c['threshold']})")
        if c["failed"] and c["severity"] == "CRITICAL":
            failed_critical += 1
    print(f"{'-'*54}\nReport -> data/gold/dq_report_latest.json")
    if strict and any(c["failed"] and c["severity"] in ("CRITICAL", "HIGH") for c in checks.values()):
        print("STRICT: critical/high checks failed.")
        return 1
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Data-quality gate for the Silver corpus.")
    ap.add_argument("--strict", action="store_true", help="exit 1 if CRITICAL/HIGH checks exceed threshold")
    raise SystemExit(run(strict=ap.parse_args().strict))
