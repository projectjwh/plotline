# Plotline

**Market intelligence for story IP — webcomics & web novels.**

Plotline is a "Crunchbase / Bloomberg for story IP." It scrapes 9 digital publishing
platforms, runs the data through a medallion pipeline into a DuckDB warehouse, scores every
title with a transparent composite (**PlotScore**), models revenue and adaptation-readiness,
and ships it all as a single-file **explorer** app — leaderboards, a market heatmap, an
adaptation scouting board, anomaly detection, an auto-generated news brief, and an in-browser
SQL data lake.

```{note}
Plotline is built **acquisition-first on a free/local budget** — no paid LLM APIs. Every
score and insight is deterministic and reproducible from the tracked data. Scraped content
stays local; the repository tracks only source, config, and deploy scaffolding.
```

This documentation is in two parts: a **product manual** (how the system works, how to run
it, and how every metric is computed) and a **user guide** (how to read and use the explorer
app).

## Product documentation

```{toctree}
:maxdepth: 2
:caption: Product

overview
architecture
installation
quickstart
pipeline
data-model
metrics
cli
scheduling
deployment
api
```

## User guide

```{toctree}
:maxdepth: 2
:caption: User guide

user-guide/index
user-guide/tabs
user-guide/data-lake
user-guide/interpreting
```

## Reference

```{toctree}
:maxdepth: 2
:caption: Reference

reference/modules
reference/glossary
```

## At a glance

| | |
|---|---|
| **Titles tracked** | ~5,200 across 9 platforms |
| **Pipeline** | Bronze (raw HTML) → Silver (Parquet) → Gold (DuckDB warehouse) |
| **Headline score** | PlotScore — a transparent 0–100 composite |
| **Explorer** | one self-contained HTML app, 13 views |
| **Stack** | Playwright · BeautifulSoup · Polars · DuckDB · FastAPI · scikit-learn / XGBoost |
| **Repository** | `leesearch` (private) |
