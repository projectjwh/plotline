# Installation

## Prerequisites

- **Python 3.9+** (3.11+ recommended).
- **git**.
- Enough disk for scraped data and cover images (the `data/` tree can reach tens of MB; it is
  git-ignored and never committed).

## Set up

```bash
git clone <your-remote>/leesearch.git
cd leesearch

python -m venv .venv
# Windows:  .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate

pip install -r requirements.txt
playwright install chromium      # required for the browser-based ranking scraper
```

```{admonition} Heavy optional dependencies
:class: note
`requirements.txt` includes the full analytics/ML stack (torch, transformers, bertopic,
xgboost, opencv). Most of the pipeline and the entire explorer build run **without** these —
they are only needed by specific model stages (e.g. topic modeling). If you only want to run
the core pipeline and build the explorer, the heavy packages can be skipped or installed
lazily.
```

## Verify

```bash
# Process whatever Bronze data exists end-to-end (no network), then build the warehouse:
python run_pipeline.py

# Build the self-contained explorer from the warehouse:
python -m src.reports.build_explorer --covers 320 --out reports/leesearch_explorer.html
```

Open `reports/leesearch_explorer.html` in a browser. If it loads with data, the toolchain is
working. See {doc}`quickstart` for a fuller first run and {doc}`cli` for every command.

## Configuration

All scraping targets, CSS selectors, delays, storage paths, and processing parameters live in
`config.yaml` (top-level sections `scraping`, `storage`, `processing`). Deployment/runtime
settings for the API are read from environment variables (see {doc}`deployment`); no secrets
are stored in the repo.
