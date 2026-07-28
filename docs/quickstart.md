# Quickstart

This walks through a first end-to-end run: acquire data, process it, build the warehouse, and
generate the explorer. Assumes you have completed {doc}`installation`.

## 1. Acquire data

The safest first step reprocesses any existing Bronze snapshots without touching the network.
To pull fresh data, opt into the live stages:

```bash
# Fresh rankings (Playwright) + enrich 300 detail pages, then process everything:
python run_pipeline.py --scrape --enrich 300
```

`run_pipeline.py` runs the whole medallion pipeline as isolated stages with per-stage timing
and a captured log. The live scraping stages (`--scrape`, `--enrich N`) are **opt-in**; a bare
`python run_pipeline.py` safely reprocesses existing Bronze. See {doc}`pipeline` for the stage
list.

```{admonition} Datacenter IPs
:class: warning
Several platforms block datacenter IPs, so scraping is most reliable from a residential
connection (i.e. this machine) rather than CI runners. If a live crawl returns little, that is
usually why.
```

## 2. Build the warehouse

The orchestrator's final stage already rebuilds the warehouse. To build it on its own:

```bash
python -m src.db.warehouse
```

This produces `data/plotline.duckdb` — a star schema of facts, dimensions, entities, and KPI
tables ({doc}`data-model`).

## 3. Build the explorer

```bash
python -m src.reports.build_explorer --covers 6000 --out reports/leesearch_explorer.html
```

- `--covers N` — how many cover thumbnails to embed as base64. Use a high number (e.g. `6000`)
  to embed **all** available covers so titles show real art everywhere; a small number keeps
  the file lean but shows monogram placeholders for the rest.
- `--out PATH` — where to write the single-file HTML.

Open the resulting HTML in any browser — it is fully self-contained (data + fonts + covers
embedded) and needs no server. See the {doc}`user-guide/index`.

## 4. (Optional) Reports and API

```bash
# Static reports:
python -m src.reports.daily_report
python -m src.reports.weekly_report

# Serve the warehouse as a JSON API (docs at http://localhost:8000/docs):
uvicorn src.api.main:app --reload
```

## Typical daily refresh

```bash
python run_pipeline.py --enrich 300 \
  && python -m src.reports.build_explorer --covers 6000 --out reports/leesearch_explorer.html
```

To automate this, see {doc}`scheduling`.
