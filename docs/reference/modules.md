# Module reference

A map of the codebase, by package. Modules marked ▶ are runnable as `python -m <module>`
(see {doc}`../cli` for flags).

## `src/scrapers` — acquisition

```{list-table}
:header-rows: 1
:widths: 30 8 62

* - Module
  - CLI
  - Purpose
* - `scraper_core`
  - ▶
  - Async Playwright ranking scraper with stealth (UA rotation, random delays) → Bronze.
* - `listing_fetch`
  - ▶
  - Requests-based listing fetcher for server-rendered sites (e.g. RoyalRoad).
* - `detail_crawler`
  - ▶
  - Hardened concurrent detail-page enrichment (retry/backoff, rate limit, block→quarantine).
* - `cover_crawler`
  - ▶
  - Downloads cover images; builds a base64 map for embedding in the explorer.
* - `backfill_archive`
  - ▶
  - Backfills historical snapshots from the Internet Archive (Wayback Machine).
```

### `src/scrapers/adapters` — per-platform parsers

```{list-table}
:header-rows: 1
:widths: 26 74

* - Module
  - Purpose
* - `base`
  - Adapter framework: registration, soup/metric helpers, `parse` / `parse_detail` / `parse_episodes` hooks.
* - `webtoon`
  - Webtoon adapter (CSS selectors from `config.yaml`): views, subs, rating, episodes, synopsis, tags, status.
* - `royalroad`
  - RoyalRoad adapter — the server-rendered fiction list (views, followers, chapters, genre, tags).
* - `listings`
  - Generic href-anchor listing adapters for the remaining platforms.
* - `__init__`
  - Registers every adapter on import.
```

## `src/pipelines` — Bronze → Silver

```{list-table}
:header-rows: 1
:widths: 30 8 62

* - Module
  - CLI
  - Purpose
* - `schema_contract`
  - 
  - The canonical `ComicRecord` + fixed `SILVER_SCHEMA` that every adapter conforms to.
* - `parser`
  - ▶
  - Bronze → Silver driver; routes each snapshot to its adapter, quarantines blocks.
* - `pipeline_updates`
  - ▶
  - Day-over-day deltas and velocity (Gold metrics).
```

## `src/models` — the Gold model layer

```{list-table}
:header-rows: 1
:widths: 30 8 62

* - Module
  - CLI
  - Purpose
* - `plotscore`
  - ▶
  - The 0–100 composite PlotScore ({doc}`../metrics`).
* - `earnings`
  - ▶
  - Modeled monthly revenue per title.
* - `entity_resolution`
  - ▶
  - Cluster platform-siloed titles/authors into canonical IP.
* - `trends_engine`
  - ▶
  - Multi-dimensional trend signals over the resolved universe.
* - `kpi_layers`
  - ▶
  - Genre / platform / author / publisher / readership / revenue KPI layers.
* - `art_style`
  - ▶
  - Cover palette + painting-style clustering.
* - `episode_analytics`
  - ▶
  - Per-episode / per-week / per-author engagement stats.
* - `unit_stats`
  - ▶
  - Episode / chapter / volume structure statistics.
* - `gap_analysis`
  - ▶
  - Blue-Ocean / whitespace (under-served niches).
* - `concept_scorer`
  - ▶
  - XGBoost success-probability scoring.
* - `trend_detection`
  - ▶
  - Statistical trend detection.
* - `advanced_metrics`
  - ▶
  - Shared statistical toolkit (Mann-Kendall, HHI, regression, engagement ratios).
```

## `src/db` — warehouse

```{list-table}
:header-rows: 1
:widths: 30 8 62

* - Module
  - CLI
  - Purpose
* - `warehouse`
  - ▶
  - Build the DuckDB warehouse (facts, dimensions, entities, KPIs, views).
* - `schema`
  - ▶
  - Create the DuckDB schema (dimension/fact tables).
* - `migrate_data`
  - ▶
  - Migrate existing Parquet into DuckDB.
* - `publish_warehouse`
  - ▶
  - Upload the built warehouse to object storage (Cloudflare R2).
```

## `src/reports` — reporting & explorer

```{list-table}
:header-rows: 1
:widths: 30 8 62

* - Module
  - CLI
  - Purpose
* - `build_explorer`
  - ▶
  - Build the single-file explorer artifact from the warehouse.
* - `daily_report`
  - ▶
  - Daily HTML report.
* - `weekly_report`
  - ▶
  - Weekly Markdown report.
* - `visual_report`
  - ▶
  - Visual (chart) report.
* - `explorer_assets/template.html`
  - 
  - The explorer front-end (vanilla JS) — the single source of truth for the views, `MET` metric registry, and in-browser SQL engine.
```

## `src/api` — read layer

```{list-table}
:header-rows: 1
:widths: 26 74

* - Module
  - Purpose
* - `main`
  - FastAPI app — titles, profiles, leaderboard, trends, KPI layers, premium feed, health.
* - `config`
  - Environment-driven configuration.
* - `auth`
  - API-key validation and plan lookup (Postgres or static fallback).
* - `billing`
  - Stripe checkout + webhook; waitlist-gated tiers.
* - `ratelimit`
  - Per-IP rate limiting (slowapi when present, no-op otherwise).
* - `warehouse_loader`
  - Download the warehouse artifact before the API opens it.
```
