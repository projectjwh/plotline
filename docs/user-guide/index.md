# Using the explorer

The explorer is a single self-contained HTML file — open it in any browser, no server needed.
Everything (data, fonts, and cover art) is embedded, and every computation runs locally in your
browser.

## Layout

- **Left rail** — navigation between the 13 views ({doc}`tabs`).
- **Top bar** — a global **search** box (matches title, author, genre, and tags), a **content
  type** toggle (All / Comics / Novels), and dropdown filters for **genre**, **language**, and
  **first-seen age**.
- **Platform chips** — click a platform to filter every view to that source; click again to
  clear.
- **Result bar** — shows the active count and any applied filters, with a *clear filters* link.

Filters apply across all views (except the Data lake and Data catalog, which operate on the full
dataset).

## The title drawer → full page

Clicking any title (a table row, a chart marker, a card) opens a **profile drawer** on the
right: a quick look with the cover, PlotScore composition, adaptation readiness, modeled
revenue, logline, per-episode engagement, rank-over-time, similar IP, and more.

The drawer header has an **⤢ Open full page** button that promotes the quick look to a full
dedicated page (a two-column layout with the same sections at more depth). A **← Back** button
returns you to where you were. Authors have the same drawer → full-page flow, reached from the
Authors view.

## Reading charts

- Line and bump charts render at natural resolution and scale to fit — the same font size as
  the rest of the UI.
- Hover any mark for a tooltip; click through to the underlying title.
- Colors follow a consistent semantic: **emerald** = value (high scores, money), **indigo** =
  structure/UI, **amber** = mid-tier, **red** = falling, **slate** = neutral. The market heatmap
  uses a Finviz-style red → slate → green diverging scale.

Continue to {doc}`tabs` for what each view does, {doc}`data-lake` for querying the data with
SQL, and {doc}`interpreting` for how to read the numbers honestly.
