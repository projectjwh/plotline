# Command reference

Every component runs as a module: `python -m <module> [flags]`. The orchestrator chains most of
them; the tables below list what each does and its key flags.

## Orchestrator

```bash
python run_pipeline.py [--scrape] [--enrich N] [--only a,b] [--strict]
```

```{list-table}
:header-rows: 1
:widths: 22 78

* - Flag
  - Effect
* - `--scrape`
  - Include the live Playwright ranking scrape (stage 1).
* - `--enrich N`
  - Crawl `N` detail pages before parsing (stage 2).
* - `--only a,b`
  - Run only the named stages (overrides defaults).
* - `--strict`
  - Abort on the first failing stage.
```

See {doc}`pipeline` for the full stage list.

## Acquisition

```{list-table}
:header-rows: 1
:widths: 34 66

* - Command
  - Notes
* - `python -m src.scrapers.scraper_core`
  - Playwright ranking scrape → Bronze.
* - `python -m src.scrapers.listing_fetch [--source S] [--all] [--dark]`
  - Requests-based listing fetch for server-rendered sites.
* - `python -m src.scrapers.detail_crawler [--source S] [--limit N] [--all] [--refresh] [--concurrency C]`
  - Enrich Silver titles with detail-page metrics.
* - `python -m src.scrapers.cover_crawler [--limit N] [--all] [--refresh] [--concurrency C]`
  - Download cover images; `--all` fetches every missing cover.
* - `python -m src.scrapers.backfill_archive`
  - Backfill historical snapshots from the Wayback Machine.
```

## Processing & models

```{list-table}
:header-rows: 1
:widths: 40 60

* - Command
  - Purpose
* - `python -m src.pipelines.parser`
  - Bronze → Silver (routes to adapters).
* - `python -m src.pipelines.pipeline_updates`
  - Day-over-day deltas / velocity (Gold metrics).
* - `python -m src.models.earnings`
  - Modeled monthly revenue per title.
* - `python -m src.models.plotscore`
  - The 0–100 PlotScore.
* - `python -m src.models.entity_resolution`
  - Canonical IP / author clustering.
* - `python -m src.models.trends_engine`
  - Multi-dimensional trend signals.
* - `python -m src.models.kpi_layers`
  - Genre / platform / author / publisher KPI layers.
* - `python -m src.models.art_style`
  - Cover palette + painting-style clusters.
* - `python -m src.models.episode_analytics`
  - Per-episode / per-week / per-author stats.
* - `python -m src.models.unit_stats`
  - Episode / chapter / volume structure stats.
* - `python -m src.models.trend_detection`
  - Statistical trend detection.
* - `python -m src.models.gap_analysis`
  - Blue-Ocean / whitespace analysis.
* - `python -m src.models.concept_scorer`
  - XGBoost success-probability scoring.
```

## Warehouse & publishing

```{list-table}
:header-rows: 1
:widths: 44 56

* - Command
  - Purpose
* - `python -m src.db.warehouse`
  - Build `data/plotline.duckdb` (star schema).
* - `python -m src.db.schema`
  - Create the DuckDB schema (dimension/fact tables).
* - `python -m src.db.migrate_data`
  - Migrate existing Parquet into DuckDB.
* - `python -m src.db.publish_warehouse`
  - Upload the warehouse artifact to object storage (R2).
```

## Reports & explorer

```{list-table}
:header-rows: 1
:widths: 52 48

* - Command
  - Purpose
* - `python -m src.reports.daily_report`
  - Daily HTML report.
* - `python -m src.reports.weekly_report`
  - Weekly Markdown report.
* - `python -m src.reports.visual_report`
  - Visual (chart) report.
* - `python -m src.reports.build_explorer [--covers N] [--out PATH] [--mode embedded|api] [--data-url URL]`
  - Build the single-file explorer artifact.
```

### `build_explorer` flags

```{list-table}
:header-rows: 1
:widths: 22 78

* - Flag
  - Effect
* - `--covers N`
  - Max cover thumbnails to embed as base64. Use a high value (e.g. `6000`) to embed **all** covers.
* - `--out PATH`
  - Output HTML path (default `reports/leesearch_explorer.html`).
* - `--mode embedded`
  - Self-contained file with data baked in (default).
* - `--mode api --data-url URL`
  - A light shell that fetches `explorer_data.json` from `URL` at runtime (for the deployed build).
```

## API

```bash
uvicorn src.api.main:app --reload    # docs at http://localhost:8000/docs
```

See {doc}`api` for the endpoint reference.
