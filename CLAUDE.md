# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

LeeSearch is a web comic and web novel market intelligence platform. It scrapes data from 16+ digital publishing platforms (Webtoon, Tapas, Tappytoon, Manta, etc.), processes it through a medallion data pipeline, performs statistical trend analysis, and generates reports.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt
playwright install  # Required for browser-based scraping

# Run the full pipeline manually (in order)
python -m src.scrapers.scraper_core        # Scrape → Bronze
python -m src.pipelines.parser             # Bronze → Silver
python -m src.pipelines.pipeline_updates   # Silver → Gold
python -m src.models.trend_detection       # Analytics
python -m src.models.gap_analysis          # Blue Ocean analysis

# Generate reports
python -m src.reports.daily_report
python -m src.reports.weekly_report
python -m src.reports.visual_report

# Database setup (optional, for SQL-based analytics)
python -m src.db.schema
python -m src.db.migrate_data

# Airflow DAG (orchestrates the full pipeline daily)
# DAG definition: dags/comic_scraper_dag.py
```

## Architecture

### Medallion Data Pipeline (Bronze → Silver → Gold)

```
scraper_core.py / backfill_archive.py
  → data/bronze/{source}/{date}/*.html     (raw HTML snapshots)

parser.py
  → data/silver/comics_update_*.parquet    (parsed structured records)

pipeline_updates.py
  → data/gold/gold_metrics_*.parquet       (velocity metrics, engagement ratios)

trend_detection.py / gap_analysis.py
  → data/gold/*.csv                        (statistical analysis results)

daily_report.py / weekly_report.py / visual_report.py
  → reports/                               (HTML, Markdown, charts)
```

### Key Modules

- **`src/scrapers/`** — Playwright-based async scraping with stealth mode (user-agent rotation, random delays 3-8s). `scraper_core.py` has the `WebComicScraper` class; `backfill_archive.py` fetches historical data from Internet Archive's Wayback Machine.
- **`src/pipelines/`** — `parser.py` transforms HTML to Parquet (handles both listing and detail pages, normalizes metrics like "1.2M" → integers). `pipeline_updates.py` computes day-over-day deltas and velocity.
- **`src/models/`** — `advanced_metrics.py` is a shared statistical toolkit (Mann-Kendall, HHI, linear regression, engagement ratios). `trend_detection.py` applies these per-genre. `gap_analysis.py` identifies underserved niches. `concept_scorer.py` uses XGBoost for success prediction.
- **`src/reports/`** — Daily (HTML), weekly (Markdown), and visual (HTML + matplotlib charts) report generators.
- **`src/db/`** — DuckDB star schema with dimension tables (`dim_comics`, `dim_sources`, `dim_genres`) and fact tables (`fact_daily_metrics`, `fact_genre_daily`, `agg_weekly_trends`).
- **`dags/comic_scraper_dag.py`** — Airflow DAG chaining: scrape → parse → metrics → analytics.

### Configuration

All scraping targets, CSS selectors, delays, storage paths, and processing parameters are in `config.yaml`. Platform reference info is in `data/platforms_reference.md`.

### Technology Stack

- **Scraping**: Playwright (async), BeautifulSoup, fake-useragent
- **Data Processing**: Polars (primary), Pandas, PyArrow, DuckDB
- **Analytics/ML**: SciPy, scikit-learn, XGBoost, BERTopic
- **Visualization**: Matplotlib, Seaborn
- **Orchestration**: Apache Airflow

### Conventions

- Polars is the preferred DataFrame library over Pandas for pipeline code.
- Scraper output follows `data/bronze/{source_name}/{YYYY-MM-DD}/` directory structure.
- Report filenames include timestamps or dates for idempotency.
- Deduplication is always done by `(comic_id, date)` pair, keeping the latest snapshot.
