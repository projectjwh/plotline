# Architecture

Plotline is a **medallion data pipeline** feeding a DuckDB warehouse, with two presentation
layers on top: a self-contained explorer artifact and a FastAPI read service.

## The medallion pipeline

```mermaid
flowchart LR
    subgraph Acquire
      A1[scraper_core / listing_fetch<br/>rankings & listings]
      A2[detail_crawler<br/>detail pages]
      A3[cover_crawler<br/>cover images]
    end
    A1 & A2 & A3 --> B[(Bronze<br/>raw HTML + images<br/>data/bronze)]
    B -->|parser.py + adapters| S[(Silver<br/>validated Parquet<br/>data/silver)]
    S -->|models + warehouse.py| G[(Gold<br/>DuckDB warehouse<br/>data/plotline.duckdb)]
    G -->|build_explorer.py| E[Explorer artifact<br/>single-file HTML]
    G -->|FastAPI| API[Read API<br/>/titles, /feed, ...]
```

- **Bronze** — raw platform HTML snapshots (and cover images), saved verbatim and partitioned
  by `source` and `date`. Nothing is interpreted here.
- **Silver** — every Bronze page is routed to its platform **adapter** and emitted as a
  `ComicRecord` conforming to one canonical schema ({doc}`data-model`). Written as partitioned
  Parquet under `data/silver/comics/`.
- **Gold** — the model layer (PlotScore, earnings, entity resolution, KPIs, art style, episode
  and unit stats) plus the **warehouse builder**, which assembles a single DuckDB file of
  facts, dimensions, entities, and KPI tables.

The whole chain is driven by one orchestrator, `run_pipeline.py` (see {doc}`pipeline`).

## Deployment architecture (split refresh / read)

The daily crawl is heavy (Playwright, thousands of pages) and cannot run on a small always-on
instance, so the production design splits **refresh** (offline/batch) from **read** (a light
API), connected by a published warehouse artifact:

```mermaid
flowchart TB
    subgraph Refresh["REFRESH — offline / scheduled"]
      R1[run_pipeline.py] --> R2[warehouse.py]
      R2 --> R3[publish_warehouse.py]
    end
    R3 -->|plotline.duckdb + explorer_data.json| OBJ[(Object storage<br/>Cloudflare R2)]
    subgraph Read["READ — always-on, light"]
      API[FastAPI on Fly.io] --> PG[(Neon Postgres<br/>api keys · plans · waitlist)]
    end
    OBJ -->|downloaded on boot| API
    subgraph Front["FRONTEND"]
      WEB[Explorer on Vercel]
    end
    OBJ -->|fetch explorer_data.json| WEB
    API -.->|premium feed| WEB
```

See {doc}`deployment` for the concrete free-tier service map and go-live gates.

## Repository layout

```text
leesearch/
├── config.yaml                 # scraping targets, selectors, storage paths, processing params
├── run_pipeline.py             # orchestrator (16 stages)
├── requirements.txt
├── src/
│   ├── scrapers/               # acquisition
│   │   ├── scraper_core.py         # Playwright ranking scraper
│   │   ├── listing_fetch.py        # requests-based listing fetch (server-rendered sites)
│   │   ├── detail_crawler.py       # hardened detail-page enrichment
│   │   ├── cover_crawler.py        # cover-image download + base64 map
│   │   ├── backfill_archive.py     # Wayback Machine backfill
│   │   └── adapters/               # per-platform Bronze→record parsers
│   ├── pipelines/
│   │   ├── schema_contract.py      # canonical Silver record + schema
│   │   ├── parser.py               # Bronze→Silver driver
│   │   └── pipeline_updates.py     # day-over-day deltas / velocity
│   ├── models/                 # the Gold model layer (scores, KPIs, analytics)
│   ├── db/                     # warehouse builder, schema, publish
│   ├── reports/                # daily/weekly/visual reports + build_explorer + template
│   └── api/                    # FastAPI read layer + auth/billing/config
├── dags/comic_scraper_dag.py   # Airflow DAG (Linux fallback)
├── .github/workflows/          # refresh.yml (data) + docs.yml (this documentation)
├── Dockerfile · docker-compose.yml · fly.toml · vercel.json
└── DEPLOYMENT.md
```

## Technology stack

- **Scraping** — Playwright (async), BeautifulSoup, `requests`, fake-useragent.
- **Data** — Polars (primary), PyArrow, DuckDB, Pydantic (schema validation).
- **Analytics / ML** — scikit-learn, XGBoost, BERTopic; NumPy/SciPy via the metrics toolkit.
- **Vision** — Pillow + OpenCV for cover palette / painting-style clustering.
- **Serving** — FastAPI + Uvicorn; a single-file HTML explorer (vanilla JS, no framework).
- **Orchestration** — `run_pipeline.py`; Airflow DAG and GitHub Actions as alternatives.
