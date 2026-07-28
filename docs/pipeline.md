# Data pipeline

The pipeline is orchestrated by `run_pipeline.py`, a dependency-light runner that executes each
stage as an isolated module invocation with per-stage timing and a captured log under `logs/`.
Live-scraping stages are **opt-in** so a default run safely reprocesses existing Bronze.

```bash
python run_pipeline.py                    # process existing data end-to-end (no network)
python run_pipeline.py --enrich 300       # crawl 300 detail pages first, then process
python run_pipeline.py --scrape --enrich 500   # full refresh (fresh rankings + detail)
python run_pipeline.py --only parse,gold  # run just those stages
python run_pipeline.py --strict           # abort on the first failing stage
```

## Stages

Executed in order; **default** stages run with no flags, **opt-in** stages require a flag.

| # | Stage | Module | Default | Purpose |
|---|-------|--------|:---:|---------|
| 1 | `scrape` | `src.scrapers.scraper_core` | opt-in `--scrape` | Playwright ranking scrape → Bronze |
| 2 | `enrich` | `src.scrapers.detail_crawler` | opt-in `--enrich N` | Fetch N detail pages → Bronze |
| 3 | `parse` | `src.pipelines.parser` | ✅ | Bronze → Silver (routes to adapters) |
| 4 | `gold` | `src.pipelines.pipeline_updates` | ✅ | Day-over-day deltas / velocity |
| 5 | `earnings` | `src.models.earnings` | ✅ | Modeled monthly revenue per title |
| 6 | `plotscore` | `src.models.plotscore` | ✅ | The 0–100 composite score |
| 7 | `entities` | `src.models.entity_resolution` | ✅ | Cluster titles/authors into canonical IP |
| 8 | `signals` | `src.models.trends_engine` | ✅ | Multi-dimensional trend signals |
| 9 | `kpis` | `src.models.kpi_layers` | ✅ | Genre/platform/author/publisher KPI layers |
| 10 | `style` | `src.models.art_style` | ✅ | Cover palette + painting-style clustering |
| 11 | `episodes` | `src.models.episode_analytics` | ✅ | Per-episode / per-week / per-author stats |
| 12 | `units` | `src.models.unit_stats` | ✅ | Episode/chapter/volume structure stats |
| 13 | `trends` | `src.models.trend_detection` | ✅ | Statistical trend detection |
| 14 | `daily` | `src.reports.daily_report` | ✅ | Daily HTML report |
| 15 | `weekly` | `src.reports.weekly_report` | ✅ | Weekly Markdown report |
| 16 | `warehouse` | `src.db.warehouse` | ✅ | Assemble the DuckDB warehouse |

```{admonition} The explorer is not a pipeline stage
:class: note
`build_explorer.py` (and `cover_crawler.py`) are run **separately** after the pipeline. So a
scheduled `run_pipeline.py` refreshes the warehouse but does **not** rebuild the explorer HTML.
See {doc}`scheduling`.
```

## Acquisition layer

Three complementary fetchers write to Bronze:

- **`scraper_core.py`** — the async Playwright scraper for ranking/listing pages, with stealth
  measures (user-agent rotation, randomized 3–8s delays). Best for JS-heavy sites.
- **`listing_fetch.py`** — a `requests`-based fetcher for server-rendered sites that Playwright
  handles poorly (notably RoyalRoad). Flags: `--source`, `--all`, `--dark`.
- **`detail_crawler.py`** — a hardened, concurrent `requests` crawler (retry/backoff, per-host
  rate limiting, UA rotation, block→quarantine) that enriches Silver titles with detail-page
  metrics. Flags: `--source`, `--limit N`, `--all`, `--refresh`, `--concurrency`.
- **`cover_crawler.py`** — downloads each title's cover image and can emit a base64 map for
  embedding. Flags: `--limit`, `--all`, `--refresh`, `--concurrency`.
- **`backfill_archive.py`** — pulls historical snapshots from the Internet Archive's Wayback
  Machine.

## Adapters (Bronze → records)

`parser.py` routes each Bronze HTML file to the platform **adapter** registered for its source.
Adapters live in `src/scrapers/adapters/` and subclass `BaseAdapter`:

- **`webtoon.py`** — CSS-selector based (selectors sourced from `config.yaml`); extracts views,
  subscribers, rating, episode count, synopsis, tags, and publication **status** (from the
  schedule badge).
- **`royalroad.py`** — parses the server-rendered fiction list; the listing alone yields views,
  followers, chapter count, genre and **tags**.
- **`listings.py`** — generic href-anchor listing adapters for the remaining platforms.
- **`base.py`** — the adapter framework: registration, soup helpers, metric cleaning, and the
  `parse` / `parse_detail` / `parse_episodes` hooks.

Adapters are the extension point for coverage: what a column's fill rate looks like ultimately
depends on what each platform exposes in HTML **and** what its adapter extracts. The
{doc}`user-guide/tabs` Data-catalog view shows the resulting per-source coverage live.
