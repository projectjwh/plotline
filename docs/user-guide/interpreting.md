# Interpreting the numbers

Plotline is deliberately transparent about what is measured versus modeled, and where coverage
is thin. Keep these in mind when you read any figure.

## Modeled vs. scraped

```{list-table}
:header-rows: 1
:widths: 30 18 52

* - Figure
  - Kind
  - Note
* - Views, likes, subscribers, comments, rating, ranks
  - **scraped**
  - Directly from the platform's HTML (where exposed).
* - PlotScore, momentum, ratios, growth, cross-platform
  - **derived**
  - Deterministic functions of the scraped data.
* - Estimated revenue
  - **modeled**
  - An assumption-based estimate; shown as a ×0.4–2.5 band, never a point.
* - Adaptation readiness
  - **modeled**
  - Intrinsic *readiness*, not confirmation a title is un-adapted.
* - Weekly / cadence-weighted views
  - **modeled**
  - Where no dated view series exists, weekly views are inferred from episode count and cadence — directional only.
```

## Rank cadence is bursty

Some platforms (notably Webtoon) publish their chart on a **weekday schedule**, so consecutive
crawls can have low overlap. As a result, short-window rank movement — and some entries in the
Anomalies view — partly reflect *when we crawled*, not a real market shift. Longer windows are
more trustworthy for rank trends.

## Coverage is uneven

What each column can tell you depends on what the platform exposes **and** what its adapter
extracts. For example, genre, publication status, and tags are well-covered on some platforms
and absent on others. The **Data catalog** view shows this directly: a live fill-rate bar per
column and a per-platform coverage table. Always sanity-check a metric's coverage before leaning
on it.

## Growth needs time

Measured view-growth and the "measured" anomaly signals require **≥ 2 dated snapshots** of a
title. They fill in and sharpen as daily crawls accumulate; on a fresh install most titles have
only their latest snapshot.

## The explorer is a snapshot

The published explorer artifact embeds a point-in-time copy of the warehouse. It reflects the
data as of the last build — re-run `build_explorer` after a refresh to update it
({doc}`../scheduling`).
