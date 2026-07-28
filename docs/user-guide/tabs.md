# The views

The explorer has 13 views, reached from the left rail. Global filters ({doc}`index`) apply to
all of them except **Data lake** and **Data catalog**, which always operate on the full dataset.

## Overview

The market at a glance. A KPI strip (titles, comics, novels, authors, titles with metrics,
modeled revenue) sits above **Top performers** — a rank-movement bump chart of the top 15
titles. Pick the ranking **metric** (PlotScore, views, likes, subscribers, revenue) and the
**period** (1W / 1M / YTD / 1Y / custom); each smooth line is one title, tipped with its cover.
Below are platform/genre breakdowns, top modeled earners, and a data-coverage bar.

## Trends

The core "what's moving" view. It includes:

- **Rising / Falling** — biggest rank gains and declines.
- **Top views / Top likes** — leaderboards with a **1D / 1W / YTD / 1Y / All** window selector.
  (These four sit in one responsive row that reflows to a 2×2 grid on narrow screens.)
- **Over-time charts** — tracked universe, new titles per crawl, cumulative reach & revenue,
  average PlotScore, genre / platform / language mix, genre concentration (HHI), and ranked-titles
  breadth.
- **Modeled weekly views** and **cadence-weighted weekly views** (see {doc}`interpreting`).
- **Measured view growth** — real % change from dated snapshots.
- **Blue Ocean** — demand intensity (avg reach per title) by genre — under-served niches.
- **Popular tags** and score/views distributions.

## Titles

The full, sortable, paginated table of every title in the current filter — PlotScore, platform,
genre, best rank, views, modeled revenue, and a trend sparkline. Click any row for its profile.

## Scouting

The adaptation **scouting board** for the studio/investor buyer: titles ranked by modeled
{doc}`adaptation-readiness <../metrics>` with KPI tiles
(ready-to-option count, completed series, average readiness). Each row shows publication status
and a readiness score. Read it as *readiness*, not confirmed availability.

## Market map

The whole market as one picture, with a **VIEW** toggle:

- **Map** — a Finviz-style squarified treemap. Choose the **size** metric and the **color**
  metric (score, views, revenue, momentum, …); tiles are grouped and tinted by category, and you
  can scroll to zoom.
- **Bubble** — a scatter with selectable **X axis**, **Y axis**, **bubble size**, and **bubble
  color**; hover a bubble for a floating detail box.

## Revenue

The modeled monetization view. KPI tiles show the modeled monthly market and its ad-vs-subscription
split, followed by a **"How revenue is modeled"** card (the formula + the per-platform
assumptions table) and a per-title table with the inputs (views, subscribers), the ad/sub split,
the estimate, and its low–high band. All figures are modeled — see {doc}`../metrics`.

## Genres

Genre analytics as a wide table: titles, platforms, total & average views, average score, best
rank, modeled revenue, momentum, top author, and share. Click a genre to drill every view into it.

## Platforms

One card per platform: coverage percentages (metrics / genre / author / status), depth
(episodes/chapters/volumes), and its top titles by PlotScore. A "filter to platform" button
scopes the whole explorer.

## Authors

A paginated table of creators ranked by catalogue size, with total reach, languages, average
score, and top title. Selecting an author opens a **profile** (drawer, or a full page) with their
KPIs, genre/platform mix, and full title list.

## Anomalies

Sudden, statistically unusual jumps ({doc}`method <../metrics>`): chart-rank
leaps, measured view surges, viral/anomalous episodes, and authors moving on several titles at
once. A **Low / Medium / High** sensitivity toggle adjusts the thresholds. Every row clicks
through to the title or author.

## News

An auto-generated **market brief** — a grid of news cards written from the tracked data (no
external feed). Each card has a cover banner, a category chip (Breakout / Rankings / Revenue /
Adaptation / Market), a dateline, a headline, and a one-line body, and clicks through to the
title. A category filter narrows the feed.

## Data lake

Browse or query the full dataset. See {doc}`data-lake` for the full reference.

- **Table viewer** — the 29-column `titles` table with a row filter, a column chooser, sortable
  headers, pagination, CSV export, and row-click-to-profile.
- **SQL** — an in-browser SQL console over a `titles` table, with a schema reference, clickable
  example queries, results as a table, and CSV export.

## Data catalog

The self-documenting catalog: a KPI strip; the Bronze → Silver → Gold → App **lineage**; the
**datasets** table (warehouse tables with live row counts, grain, and purpose); the **column
dictionary** for `titles` (type, layer, provenance, and a **live coverage bar** per column); a
**source-coverage** table (per-platform fill %); and a **metrics glossary**.
