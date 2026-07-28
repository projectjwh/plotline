# Glossary

```{glossary}
Bronze
  The raw layer — platform HTML snapshots and cover images saved verbatim, partitioned by
  source and date. Nothing is interpreted here.

Silver
  The validated layer — every Bronze page parsed by its adapter into a canonical `ComicRecord`
  and written as partitioned Parquet.

Gold
  The modeled layer — scores, KPIs, and analytics, assembled into the DuckDB warehouse.

PlotScore
  Plotline's headline 0–100 composite: percentile-normalized reach, momentum, engagement,
  monetization, and quality, weighted 0.30 / 0.25 / 0.20 / 0.15 / 0.10.

Adaptation readiness
  A modeled 0–100 "ready-to-option" signal (completeness, reach, engagement, momentum, material
  depth, genre prior). Intrinsic readiness, not confirmed availability.

Momentum
  Rank improvement across observations (`first_rank − latest_rank`); positive means rising.

Like-through
  Likes divided by views — an engagement-intensity ratio.

Whitespace / Blue Ocean
  Average reach per title within a genre; high reach with few titles signals an under-served,
  high-demand niche.

Cross-platform IP
  The same normalized title appearing on more than one platform — a proxy for validated,
  travelling intellectual property.

Entity resolution
  Clustering platform-siloed titles (and author-name variants) into one canonical IP or author.

Modified z-score
  A robust outlier measure, `0.6745 (x − median) / MAD`, used to flag anomalous episodes.

Adapter
  A per-platform parser that turns Bronze HTML into canonical records.

Warehouse
  The single DuckDB file (`data/plotline.duckdb`) of facts, dimensions, entities, and KPIs.

Explorer
  The self-contained single-file HTML application built from the warehouse.

MAD
  Median absolute deviation — the robust spread used by the modified z-score.

HHI
  Herfindahl–Hirschman Index — a concentration measure (used for genre concentration).
```
