# Deployment

Plotline can go live as a SaaS on the **free tiers** of managed services. The commercial rails
(auth, tiers, billing) are wired, but **charging stays off** until the go-live gates below are
green. The authoritative runbook is `DEPLOYMENT.md` in the repo; this page summarizes it.

## The load-bearing decision: split refresh from read

The daily crawl is heavy and cannot run on a small always-on API instance, so the system splits
into an offline **refresh** and a light **read API** connected by a published warehouse
artifact (see the diagram in {doc}`architecture`).

## Free-tier service map

```{list-table}
:header-rows: 1
:widths: 26 30 44

* - Concern
  - Service
  - Notes
* - Read API
  - **Fly.io**
  - FastAPI over DuckDB; scale-to-zero, 256 MB
* - Market DB artifact
  - **Cloudflare R2**
  - `plotline.duckdb` + `explorer_data.json`; API downloads on boot
* - App state DB
  - **Neon Postgres**
  - API keys, plans, waitlist
* - Auth
  - **Clerk**
  - free ≤ 10k MAU
* - Billing
  - **Stripe**
  - checkout + webhook (inert until enabled)
* - Frontend
  - **Vercel**
  - the API-backed explorer shell
* - Refresh
  - **GitHub Actions**
  - `refresh.yml` cron → publish to R2
```

## What's built

| Component | Where |
|---|---|
| Hardened read API (`/health`, `/ready`, CORS, rate limit, JSON logs) | `src/api/{main,config,ratelimit,warehouse_loader}.py` |
| Postgres-backed API keys (static fallback) | `src/api/auth.py` |
| Stripe checkout + webhook, **waitlist-gated** | `src/api/billing.py` |
| Warehouse download-on-boot | `warehouse_loader.py` (`PLOTLINE_WAREHOUSE_URL`) |
| Slim API image + healthcheck | `Dockerfile` |
| Fly host config (scale-to-zero, `/ready`) | `fly.toml` |
| Refresh automation → publish to R2 | `.github/workflows/refresh.yml`, `src/db/publish_warehouse.py` |
| API-backed frontend build | `build_explorer.py --mode api`, `vercel.json` |

## Deploy (one command each, all free tier)

1. **R2** — create a bucket + token, enable a public URL. Note `R2_ENDPOINT`, keys, bucket,
   `R2_PUBLIC_BASE`.
2. **Neon** — create a Postgres project; copy `DATABASE_URL` (tables auto-create on boot).
3. **API (Fly.io)** — `fly launch --no-deploy`, set secrets, `fly deploy`.
4. **Frontend (Vercel)** — build the API-backed shell and deploy `web/`.
5. **Refresh (Actions)** — add the R2 repo secrets; the daily workflow publishes new data with
   no redeploy.

## Turning on billing

Only after the go-live gates are green:

```bash
fly secrets set PLOTLINE_BILLING_ENABLED=true \
  STRIPE_SECRET_KEY=sk_live_... STRIPE_WEBHOOK_SECRET=whsec_... STRIPE_PRICE_PRO=price_...
```

Until then `POST /billing/checkout` records a **waitlist** entry instead of charging.

## Go-live gates (the honest call)

- **Free public launch:** ready once the API + frontend + refresh are deployed.
- **Turn on payments** only when **all** are green:
  1. **Legal** — per-platform ToS/robots review for scraping + data resale.
  2. **Coverage** — deepen ≥ 3 platforms.
  3. **Demand** — 3 design partners actively using it.
