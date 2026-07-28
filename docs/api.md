# API reference

`src/api/main.py` serves the DuckDB warehouse as a JSON API — discovery, title profiles,
leaderboard, trends, and per-layer KPIs. The full data feed is gated behind an API key (the
premium tier). Interactive docs are available at `/docs` when running.

```bash
uvicorn src.api.main:app --reload      # http://localhost:8000/docs
```

## Public endpoints

```{list-table}
:header-rows: 1
:widths: 34 66

* - Endpoint
  - Description
* - `GET /`
  - Service info + market summary (`v_market`).
* - `GET /titles`
  - Filterable, ranked title list. Query: `source`, `genre`, `min_score`, `sort` (`plotscore` \| `reach` \| `revenue`), `limit`, `offset`.
* - `GET /title/{comic_id}`
  - Full title profile (`v_title`).
* - `GET /leaderboard`
  - Top titles by PlotScore. Query: `limit`.
* - `GET /trends`
  - Rising / falling movers by rank change. Query: `limit`.
* - `GET /genres`
  - Genre KPI layer.
* - `GET /platforms`
  - Platform KPI layer.
* - `GET /authors`
  - Author KPI layer. Query: `limit`.
* - `GET /search`
  - Search titles by name. Query: `query`, `limit`.
```

## Premium (API-key gated)

```{list-table}
:header-rows: 1
:widths: 34 66

* - Endpoint
  - Description
* - `GET /feed/titles`
  - Full data feed. Requires header `X-API-Key`. Query: `limit` (≤ 5000), `offset`.
```

## Health & operations

```{list-table}
:header-rows: 1
:widths: 24 76

* - Endpoint
  - Description
* - `GET /health`
  - Liveness — process is up.
* - `GET /ready`
  - Readiness — the warehouse is queryable.
```

## Billing (`/billing`)

Waitlist-gated while `PLOTLINE_BILLING_ENABLED` is false ({doc}`deployment`).

```{list-table}
:header-rows: 1
:widths: 30 70

* - Endpoint
  - Description
* - `GET /billing/plans`
  - Pricing tiers + whether charging is live.
* - `POST /billing/checkout`
  - Start an upgrade (Stripe Checkout), or record a waitlist entry if billing is off.
* - `POST /billing/webhook`
  - Stripe webhook — provisions an API key on a successful upgrade.
* - `GET /billing/me`
  - A user's active API keys + plan.
```

## Configuration

The API is configured entirely from environment variables (`src/api/config.py`): CORS origins,
the warehouse URL to download on boot (`PLOTLINE_WAREHOUSE_URL`), `DATABASE_URL` (Neon), and the
`STRIPE_*` / `PLOTLINE_BILLING_ENABLED` billing settings. Optional dependencies (Postgres,
Stripe, boto3) are imported lazily so the API runs in a minimal environment without them.
