# Metrics & scores

Every derived signal in Plotline is a transparent, deterministic computation. This page gives
the exact formula and the honest caveat for each. Definitions here match the code in
`src/models/` and the explorer's Data-catalog glossary.

## PlotScore

The headline 0–100 composite (`src/models/plotscore.py`). Each of five components is
**percentile-normalized across the universe**, then weighted and scaled to 0–100:

```text
PlotScore = 100 × (0.30·Reach + 0.25·Momentum + 0.20·Engagement
                   + 0.15·Monetization + 0.10·Quality)
```

where each term is the title's percentile (0–1) on that component:

```{list-table}
:header-rows: 1
:widths: 20 12 68

* - Component
  - Weight
  - Signal
* - Reach
  - 0.30
  - Measured audience (views/subscribers), with a rank-based proxy fallback
* - Momentum
  - 0.25
  - Rank improvement across observations (needs history)
* - Engagement
  - 0.20
  - Like-through (likes ÷ views), else rating
* - Monetization
  - 0.15
  - The modeled earnings estimate (below)
* - Quality
  - 0.10
  - Sane user rating
```

A title with no history or metrics simply lands at a low percentile — the score rewards what
can be measured. Weights live in `WEIGHTS` and are tunable.

## Estimated revenue (modeled)

No platform publishes creator earnings, so this is a **model, not a scraped figure**
(`src/models/earnings.py`):

```text
revenue/mo = (views × mvf ÷ 1000) × rpm  +  subscribers × spr × arpu
```

- `mvf` (monthly-view-fraction) converts cumulative views to monthly active reads.
- `rpm` = revenue per 1,000 monthly reads (ads + unlocks blended).
- `spr` (sub-pay-rate) = fraction of subscribers paying per month; `arpu` = their monthly spend.

Assumptions per platform (`PARAMS`), shown to the user in the Revenue tab:

```{list-table}
:header-rows: 1
:widths: 24 14 24 20 18

* - Platform
  - RPM
  - Monthly view frac
  - Sub pay-rate
  - Sub ARPU
* - Webtoon
  - $0.60
  - 3.0%
  - 2.0%
  - $1.80
* - Tapas
  - $0.45
  - 4.0%
  - 3.0%
  - $2.20
* - Manga Plus
  - $0.35
  - 12.0%
  - —
  - —
* - Wattpad
  - $0.15
  - 5.0%
  - —
  - —
* - WebComics
  - —
  - —
  - 5.0%
  - $3.00
* - GlobalComix
  - —
  - —
  - 4.0%
  - $4.00
* - *default*
  - $0.30
  - 3.0%
  - 2.0%
  - $1.50
```

The estimate is presented as a wide band — **×0.4 (low) to ×2.5 (high)** — never a false-precise
point. Treat it as order-of-magnitude.

## Adaptation readiness (modeled)

A 0–100 "ready-to-option" signal for the studio/investor ICP, computed in the explorer:

```text
adaptation = 100 × (0.30·reach% + 0.15·engagement + 0.12·momentum
                    + 0.18·completeness + 0.10·depth + 0.15·genre_prior)
```

- **completeness** = 1.0 if status *completed*, 0.6 *ongoing*, 0.3 *hiatus*.
- **depth** = capped series length (enough material to adapt).
- **genre prior** = a static per-genre base rate for adaptation.

```{admonition} Readiness ≠ availability
:class: warning
This is **intrinsic readiness**, not confirmation a title is un-adapted. Confirming that needs
external sources (Wikipedia / MAL / IMDb), which are out of scope today. The UI labels it as
such.
```

## Anomaly detection

Sudden, statistically unusual jumps (explorer **Anomalies** view), at four grains:

- **Rank leaps** — the largest single-crawl rank change per title (from the rank history), above
  a threshold.
- **View surges** — the largest jump in cumulative views between two snapshots (with a
  baseline floor to suppress tiny-denominator artifacts).
- **Episode spikes** — episodes whose likes deviate most from their own series baseline via a
  **robust modified z-score**: `z = 0.6745 × (x − median) ÷ MAD`.
- **Author clustering** — authors flagged on ≥2 titles at once.

A **Low / Medium / High** sensitivity toggle adjusts the thresholds.

## Other derived signals

```{list-table}
:header-rows: 1
:widths: 24 76

* - Signal
  - Definition
* - **Momentum**
  - Rank improvement across observations (`first_rank − latest_rank`); positive = rising.
* - **View growth**
  - Measured % change in cumulative views between a title's first and latest crawl snapshot (needs ≥2 dated points).
* - **Cross-platform**
  - Count of platforms on which the same normalized title appears — a proxy for validated, travelling IP.
* - **Conversion / discussion**
  - Subscribers and comments per 1,000 views — loyalty and discussion depth, independent of raw reach.
* - **Whitespace (Blue Ocean)**
  - Average reach per title within a genre — high reach with few titles flags an under-served, high-demand niche.
* - **Content-structure decay**
  - Early-vs-late episode engagement drop across the tracked window.
```

## Honest limits

```{admonition} Read the numbers with these in mind
:class: important
- **Modeled ≠ scraped.** Revenue and adaptation-readiness are models; weekly-view figures where
  no dated series exists are modeled from cadence. All are labeled in the UI.
- **Rank cadence is bursty.** Some platforms (notably Webtoon) run a weekday chart roster, so
  short-window rank movement partly reflects crawl timing, not the market.
- **Coverage is uneven.** Genre/status/tags fill depends on what each platform exposes and what
  its adapter extracts. The Data-catalog view shows live per-column and per-source coverage.
```
