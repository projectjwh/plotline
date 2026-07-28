# Data lake & SQL

The **Data lake** view lets you browse or query the full dataset as one flat table. Everything
runs **in your browser** — nothing is uploaded — over the 29-column `titles` table
({doc}`../data-model`).

## Table viewer

- **Filter rows** — free-text match across the shown columns.
- **Columns** — choose which of the 29 columns to display.
- **Sort** — click any header; click again to reverse.
- **Export CSV** — download the current (filtered, column-selected) view.
- **Row click** — opens that title's profile.

## SQL console

Write SQL against a single table named `titles` and press **Run** (or `Ctrl` / `⌘` + `Enter`).
The console has a built-in schema reference and clickable example queries; results render as a
sortable table you can export to CSV, and result rows click through to the title.

```{admonition} An in-browser SQL subset
:class: note
The engine is a compact SQL implementation written for the artifact (the strict artifact
sandbox can't load a database engine from a CDN). It supports the common analytical subset
below — read-only `SELECT` only.
```

### Supported syntax

```sql
SELECT <select_list>
FROM titles                      -- optional; there is one table
[WHERE <condition>]
[GROUP BY <columns>]
[ORDER BY <column|ordinal> [ASC|DESC], ...]
[LIMIT <n>]
```

```{list-table}
:header-rows: 1
:widths: 24 76

* - Feature
  - Supported
* - Select list
  - columns, `*`, `expr AS alias` (or implicit alias)
* - Aggregates
  - `COUNT(*)`, `COUNT(col)`, `SUM`, `AVG`, `MIN`, `MAX`
* - Scalar functions
  - `ROUND(x[,n])`, `LOWER`, `UPPER`, `ABS`, `COALESCE`, `LENGTH`
* - WHERE operators
  - `=` `!=`/`<>` `<` `<=` `>` `>=`, `LIKE` / `NOT LIKE` (`%`, `_`), `IN` / `NOT IN`, `IS [NOT] NULL`
* - Boolean logic
  - `AND`, `OR`, `NOT`, parentheses
* - Grouping / ordering
  - `GROUP BY`, `ORDER BY` (by output name or 1-based ordinal, `ASC`/`DESC`), `LIMIT`
* - Comments
  - `-- line comments`
```

String comparisons and `LIKE` are case-insensitive for convenience.

### Columns

`title` · `platform` · `type` · `genre` · `author` · `language` · `status` · `publisher` ·
`plotscore` · `adaptation` · `views` · `subscribers` · `likes` · `comments` · `rating` ·
`revenue_usd` · `best_rank` · `latest_rank` · `like_through` · `subs_per_1k` ·
`comments_per_1k` · `growth_pct` · `cross_platform` · `units` · `unit_type` · `episodes` ·
`cadence_wk` · `first_year` · `observations`. See {doc}`../data-model` for meanings.

### Examples

```sql
-- Platform leaderboard
SELECT platform, COUNT(*) AS titles, ROUND(AVG(plotscore),1) AS avg_score,
       SUM(views) AS total_views, SUM(revenue_usd) AS est_revenue
FROM titles WHERE plotscore IS NOT NULL
GROUP BY platform ORDER BY total_views DESC;

-- Top 20 by adaptation readiness
SELECT title, platform, genre, status, adaptation, plotscore
FROM titles ORDER BY adaptation DESC LIMIT 20;

-- Best reader conversion (subs per 1k views), among titles with real reach
SELECT title, platform, views, subscribers, subs_per_1k
FROM titles WHERE subs_per_1k IS NOT NULL AND views > 1000000
ORDER BY subs_per_1k DESC LIMIT 20;

-- Cross-platform IP (same title on 2+ platforms)
SELECT title, platform, cross_platform, plotscore
FROM titles WHERE cross_platform > 1
ORDER BY cross_platform DESC, plotscore DESC;
```
