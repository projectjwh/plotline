"""Bronze -> Silver driver.

Routes every Bronze HTML snapshot to its platform adapter
(``src/scrapers/adapters``), validates the emitted records against the canonical
schema (``schema_contract``), and writes an **idempotent, partitioned** Silver
dataset. Blocked / un-renderable / unparseable files are recorded in a coverage
manifest and a non-destructive quarantine log instead of silently vanishing.

Silver layout (idempotent — re-running rewrites each partition in place):
    data/silver/comics/source=<source>/date=<YYYY-MM-DD>/data.parquet

Run:  python -m src.pipelines.parser
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime
from glob import glob

import polars as pl

from src.pipelines.schema_contract import SILVER_SCHEMA, records_to_frame
from src.scrapers.adapters import detect_block, get_adapter

sys.stdout.reconfigure(encoding="utf-8")

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
BRONZE_DIR = os.path.join(_ROOT, "data", "bronze")
SILVER_COMICS_DIR = os.path.join(_ROOT, "data", "silver", "comics")
MANIFEST_DIR = os.path.join(BRONZE_DIR, "_manifest")
QUARANTINE_DIR = os.path.join(_ROOT, "data", "quarantine")

_TS_RE = re.compile(r"_(\d{10})\.html$")


def timestamp_from_filename(path: str) -> datetime:
    """Epoch in the filename (…_1770336774.html), else file mtime."""
    m = _TS_RE.search(os.path.basename(path))
    if m:
        try:
            return datetime.fromtimestamp(int(m.group(1)))
        except (ValueError, OSError):
            pass
    return datetime.fromtimestamp(os.path.getmtime(path))


def _kind(filename: str) -> str:
    if "comic_detail" in filename:
        return "detail"
    if "daily_schedule" in filename or "ranking" in filename or "listing" in filename:
        return "listing"
    return "other"


def run_bronze_to_silver() -> None:
    files = glob(os.path.join(BRONZE_DIR, "*", "*", "*.html"))
    if not files:
        print("No Bronze files to process.")
        return
    print(f"Scanning {len(files)} Bronze files across "
          f"{len({os.path.normpath(f).split(os.sep)[-3] for f in files})} sources...")

    all_records = []
    episode_records = []
    manifest_rows = []
    quarantine_rows = []

    for f in files:
        source = os.path.normpath(f).split(os.sep)[-3]
        filename = os.path.basename(f)
        kind = _kind(filename)
        adapter = get_adapter(source)
        row = {"source": source, "file": f, "kind": kind,
               "bytes": os.path.getsize(f), "n_records": 0,
               "status": "ok", "reason": None}

        if adapter is None:
            row.update(status="no_adapter", reason=f"no adapter registered for '{source}'")
            manifest_rows.append(row)
            continue

        html = open(f, encoding="utf-8", errors="ignore").read()
        reason = detect_block(html)
        if reason:
            row.update(status="blocked", reason=reason)
            quarantine_rows.append({k: row[k] for k in ("source", "file", "kind", "reason")})
            manifest_rows.append(row)
            continue

        try:
            recs = adapter.parse(html, source_file=f, scraped_at=timestamp_from_filename(f))
        except Exception as e:  # noqa: BLE001 — record, don't crash the run
            row.update(status="error", reason=f"{type(e).__name__}: {e}")
            quarantine_rows.append({k: row[k] for k in ("source", "file", "kind", "reason")})
            manifest_rows.append(row)
            continue

        if not recs:
            row.update(status="empty", reason="adapter returned 0 records")
            manifest_rows.append(row)
            continue

        all_records.extend(recs)
        row["n_records"] = len(recs)
        manifest_rows.append(row)

        if kind == "detail":  # per-episode granularity from detail pages
            try:
                episode_records.extend(
                    adapter.parse_episodes(html, source_file=f, scraped_at=timestamp_from_filename(f)))
            except Exception:  # noqa: BLE001 — episodes are best-effort
                pass

    _write_manifest(manifest_rows, quarantine_rows)
    _write_silver(all_records)
    _write_episodes(episode_records)


def _write_episodes(records) -> None:
    if not records:
        return
    ep_dir = os.path.join(_ROOT, "data", "silver", "episodes")
    os.makedirs(ep_dir, exist_ok=True)
    df = (pl.DataFrame(records)
            .with_columns(pl.col("episode_no").cast(pl.Int32, strict=False))
            .sort("scraped_at", descending=True)
            .unique(subset=["comic_id", "episode_no"], keep="first"))
    df.write_parquet(os.path.join(ep_dir, "episodes.parquet"))
    print(f"Episodes: {len(df)} per-episode rows across "
          f"{df['comic_id'].n_unique()} titles → data/silver/episodes/")


def _write_silver(records) -> None:
    if not records:
        print("No records parsed — Silver not updated.")
        return
    df = records_to_frame(records).with_columns(
        pl.col("scraped_at").dt.date().cast(pl.Utf8).alias("_date")
    )
    # Merge listing + detail rows for the same (comic_id, day) into one enriched
    # record: rank comes from the ranking page, granular metrics from the detail
    # page. This is idempotent — re-running rewrites each partition identically.
    df = _merge_enrich(df)

    os.makedirs(SILVER_COMICS_DIR, exist_ok=True)
    partitions = df.partition_by(["source", "_date"], as_dict=True)
    for (source, date), part in partitions.items():
        out_dir = os.path.join(SILVER_COMICS_DIR, f"source={source}", f"date={date}")
        os.makedirs(out_dir, exist_ok=True)
        part.drop("_date").select(SILVER_SCHEMA.keys()).write_parquet(
            os.path.join(out_dir, "data.parquet")
        )

    enriched = df.filter((pl.col("views") > 0) | (pl.col("subscribers") > 0) | (pl.col("likes") > 0)).height
    print(f"\nSilver written: {len(df)} records across "
          f"{df['source'].n_unique()} sources, {len(partitions)} partitions "
          f"({enriched} with an absolute engagement metric).")
    print(df.group_by("source").len().sort("len", descending=True))


def _merge_enrich(df: pl.DataFrame) -> pl.DataFrame:
    """Collapse all rows for a (comic_id, day) into one enriched record."""
    def firstnn(col):
        return pl.col(col).drop_nulls().first().alias(col)

    # Prefer the most complete title: a detail page's <title> can be generic
    # ("Comics"), so the longest candidate (usually the listing) wins.
    df = df.with_columns(pl.col("title").str.len_chars().fill_null(0).alias("_tlen"))
    merged = df.group_by(["comic_id", "_date"]).agg([
        pl.col("source").first().alias("source"),
        firstnn("platform_native_id"),
        pl.col("title").sort_by("_tlen").last().alias("title"),
        firstnn("author"),
        firstnn("genre"), firstnn("url"),
        pl.col("rank").min().alias("rank"),
        pl.col("views").max().alias("views"),
        pl.col("likes").max().alias("likes"),
        pl.col("subscribers").max().alias("subscribers"),
        pl.col("comments").max().alias("comments"),
        pl.col("rating").max().alias("rating"),
        pl.col("episode_count").max().alias("episode_count"),
        pl.col("chapter_count").max().alias("chapter_count"),
        pl.col("volume_count").max().alias("volume_count"),
        firstnn("synopsis"),
        pl.col("tags").first().alias("tags"),
        firstnn("cover_url"), firstnn("publisher"), firstnn("status"),
        pl.col("content_type").first().alias("content_type"),
        pl.col("scraped_at").max().alias("scraped_at"),
        pl.col("source_file").first().alias("source_file"),
    ])
    # Primary metric = the strongest typed signal available (views > subs > likes).
    subs0 = pl.col("subscribers").fill_null(0)
    return merged.with_columns([
        pl.when(pl.col("views") > 0).then(pl.col("views"))
          .when(subs0 > 0).then(pl.col("subscribers"))
          .when(pl.col("likes") > 0).then(pl.col("likes"))
          .otherwise(0).cast(pl.Int64).alias("primary_metric"),
        pl.when(pl.col("views") > 0).then(pl.lit("views"))
          .when(subs0 > 0).then(pl.lit("subscribers"))
          .when(pl.col("likes") > 0).then(pl.lit("likes"))
          .otherwise(pl.lit("unknown")).alias("metric_type"),
    ])


def _write_manifest(manifest_rows, quarantine_rows) -> None:
    run = datetime.now().strftime("%Y-%m-%d")
    os.makedirs(MANIFEST_DIR, exist_ok=True)
    os.makedirs(QUARANTINE_DIR, exist_ok=True)

    mf = pl.DataFrame(manifest_rows)
    mf.write_parquet(os.path.join(MANIFEST_DIR, f"manifest_{run}.parquet"))

    if quarantine_rows:
        with open(os.path.join(QUARANTINE_DIR, f"quarantine_{run}.jsonl"), "w",
                  encoding="utf-8") as q:
            for r in quarantine_rows:
                q.write(json.dumps(r, ensure_ascii=False) + "\n")

    summary = mf.group_by("status").len().sort("len", descending=True)
    print("\nCoverage manifest (per-file status):")
    print(summary)
    ok = mf.filter(pl.col("status") == "ok")
    if len(ok):
        print("Records by source:")
        print(ok.group_by("source").agg(pl.col("n_records").sum()).sort("n_records", descending=True))
    if quarantine_rows:
        print(f"Quarantined {len(quarantine_rows)} files "
              f"(reasons logged, raw Bronze left intact).")


if __name__ == "__main__":
    run_bronze_to_silver()
