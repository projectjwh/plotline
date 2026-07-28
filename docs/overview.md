# Overview

## What Plotline is

Plotline turns the scattered, platform-siloed world of webcomics and web novels into a single
queryable market. It answers questions that no individual platform will: *which titles are
breaking out, which under-served genres are worth entering, which completed series are ready
to option for a screen adaptation, and what is any given title roughly worth?*

It is a **decision platform for story IP**, not a raw-metrics dashboard. The value is in the
derived signals — scores, trends, anomalies, and comparables — not in the underlying counts.

## Who it is for

The intended buyer (ICP), in rough order of willingness-to-pay:

1. **IP investors & studios** — sourcing adaptation-ready properties and validating demand.
2. **Publishers & agencies** — competitive intelligence, whitespace, talent scouting.
3. **Authors & creators** — benchmarking, genre trends.

## What it does

- **Acquires** listings and detail pages from 9 platforms (Webtoon, Tapas, WebComics,
  GlobalComix, Webnovel, Ridibooks, Manga Plus, Wattpad, RoyalRoad).
- **Normalizes** everything into one validated schema and a DuckDB warehouse.
- **Scores** every title with **PlotScore** (a transparent 0–100 composite) and layers on
  modeled revenue, adaptation-readiness, per-episode engagement, content structure, and a
  cover/painting-style analysis.
- **Surfaces** it through a single-file explorer app: leaderboards, a Finviz-style market
  heatmap, a scouting board, anomaly detection, an auto-generated news brief, and an
  in-browser SQL data lake with a self-documenting data catalog.

## Design principles

```{admonition} Deterministic, free, and honest
:class: tip
- **Free / local-first.** No paid LLM APIs. Every insight is a deterministic computation over
  the tracked data, so it is reproducible and cheap to run.
- **Transparent.** Scores and models expose their formulas and assumptions (see {doc}`metrics`).
- **Honest about limits.** Modeled figures are labeled *modeled*, coverage gaps are shown in
  the data catalog, and rank-cadence caveats are stated in the UI.
```

## Current status

| Area | State |
|---|---|
| Data & pipeline | ✅ Working end-to-end; coverage uneven across platforms |
| Explorer app | ✅ 13 views, published as a self-contained artifact |
| Warehouse + API | ✅ DuckDB warehouse; FastAPI read layer |
| Deployment | ⚙️ Scaffolding built (free-tier split architecture); not yet live |
| Scheduling | ⚙️ Orchestrator + DAG + Actions workflow exist; **no live daily schedule yet** |
| Commercial rails | ⚙️ Auth/tiers/billing wired but **charging gated off** |

See {doc}`architecture` for how the pieces fit together, {doc}`quickstart` to run it, and the
{doc}`user-guide/index` to use the explorer.
