# Data model

Three schemas matter: the **Silver record** (what every adapter emits), the **warehouse
tables** (the Gold star schema), and the flat **`titles` table** (what the explorer and its SQL
data lake expose).

## Silver — the canonical record

Every adapter emits a `ComicRecord` (Pydantic model in `src/pipelines/schema_contract.py`), and
every Silver Parquet file conforms to the fixed `SILVER_SCHEMA`. This is what lets many
platform adapters produce one consistent dataset.

```{list-table}
:header-rows: 1
:widths: 22 14 64

* - Field
  - Type
  - Meaning
* - `comic_id`
  - str
  - Stable key, `"{source}:{native_id}"`
* - `source`
  - str
  - Platform id (e.g. `webtoon_global`)
* - `title` / `author` / `genre`
  - str
  - Core attributes (where exposed)
* - `url`
  - str
  - Detail-page URL (used by the detail crawler)
* - `rank`
  - int
  - Chart rank on the listing
* - `primary_metric` / `metric_type`
  - int / str
  - The listing's popularity number **and what it is** (views / likes / subscribers / …)
* - `views` / `likes` / `subscribers` / `comments`
  - int
  - Typed engagement metrics (kept for the Gold pipeline)
* - `rating`
  - float
  - User rating (platform scale)
* - `episode_count` / `chapter_count` / `volume_count`
  - int
  - Content structure — the applicable unit per type
* - `synopsis`
  - str
  - Logline / description
* - `tags`
  - list[str]
  - Granular descriptors
* - `cover_url`
  - str
  - Real cover-image URL
* - `publisher` / `status`
  - str
  - Publisher/studio; publication status (ongoing / completed / hiatus)
* - `content_type`
  - str
  - `comic` or `novel`
* - `scraped_at` / `source_file`
  - datetime / str
  - Provenance
```

Deduplication throughout is by `(comic_id, date)`, keeping the latest snapshot.

## Gold — the warehouse tables

`src/db/warehouse.py` builds `data/plotline.duckdb`. Base tables:

```{list-table}
:header-rows: 1
:widths: 26 24 50

* - Table
  - Grain
  - Contents
* - `fact_title`
  - one row per title
  - Current snapshot of every signal: metrics, PlotScore components, revenue, ranks, status, synopsis, tags
* - `fact_title_daily`
  - title × crawl date
  - Time series — rank + views/likes/subscribers/comments per crawl
* - `dim_platform`
  - one row per platform
  - Platform KPI layer (coverage, reach, avg score, monetization)
* - `dim_genre`
  - one row per genre
  - Genre KPI layer (titles, reach, HHI concentration, whitespace)
* - `dim_author`
  - one row per author
  - Author KPI layer (catalogue size, reach, best score)
* - `dim_publisher`
  - one row per publisher
  - Publisher KPI layer (where exposed)
* - `entities_ip`
  - one row per canonical IP
  - Titles clustered across platforms (entity resolution)
* - `entities_author`
  - one row per canonical author
  - Author-name variants unified
* - `fact_episode`
  - title × episode
  - Per-episode engagement (number, date, likes)
* - `kpi_episode`
  - one row per title
  - Episode rollups (avg likes / episode, release cadence)
* - `fact_content_structure`
  - one row per title
  - Unit counts, chapters-per-volume, engagement decay
* - `art_style`
  - one row per title
  - Cover palette + painting-style cluster
```

Convenience **views**: `v_title`, `v_leaderboard`, `v_market`, `v_content_structure`.

## The `titles` table (explorer & SQL)

`build_explorer.py` flattens the warehouse into one denormalized table of **29 columns** — the
schema you browse in the **Data lake** and query with SQL. Each column is tagged by layer
(Silver = scraped, Gold = pipeline-derived, App = computed in the browser) and provenance
(scraped / derived / modeled). The **Data catalog** view renders this dictionary with live fill
rates.

```{list-table}
:header-rows: 1
:widths: 22 10 12 56

* - Column
  - Type
  - Source
  - Meaning
* - `title` `platform` `type` `genre` `author` `language`
  - str
  - scraped/derived
  - Core identity; `type` = comic/novel; `language` inferred from script
* - `status` `publisher`
  - str
  - scraped
  - Publication status; publisher/studio
* - `plotscore`
  - num
  - derived
  - 0–100 composite ({doc}`metrics`)
* - `adaptation`
  - num
  - modeled
  - 0–100 adaptation-readiness signal
* - `views` `subscribers` `likes` `comments` `rating`
  - num
  - scraped
  - Engagement metrics
* - `revenue_usd`
  - num
  - modeled
  - Modeled monthly revenue
* - `best_rank` `latest_rank` `observations`
  - num
  - derived
  - Best/latest chart rank; # crawl observations
* - `like_through` `subs_per_1k` `comments_per_1k`
  - num
  - derived
  - Engagement ratios (likes/views; per-1k-view conversion & discussion)
* - `growth_pct`
  - num
  - derived
  - Measured % view change across snapshots
* - `cross_platform`
  - num
  - derived
  - # platforms the same title appears on
* - `units` `unit_type` `episodes` `cadence_wk`
  - num/str
  - scraped/derived
  - Content structure; releases per week
* - `first_year`
  - str
  - derived
  - First year seen in tracking
```

See {doc}`metrics` for how the derived and modeled columns are computed, and
{doc}`user-guide/data-lake` for querying them.
