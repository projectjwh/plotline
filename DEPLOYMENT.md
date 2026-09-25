# Plotline — Deployment & Go-Live (Full SaaS, free-tier)

Story-IP market intelligence. This is the runbook for taking the built backend to
a live SaaS on **free tiers of managed services**. The commercial rails (auth,
billing, tiers) are wired; **charging stays off** until the go-live gates at the
bottom are green.

## Architecture — read this first

The daily crawl is heavy (Playwright, thousands of pages) and **cannot** run on a
free API instance, so the system is split into an offline **refresh** and a
lightweight **read API**:

```
 REFRESH (GitHub Actions cron, or local)          READ API (Fly.io, 256 MB)
   run_pipeline → src.db.warehouse                   FastAPI over DuckDB (read-only)
   → src.db.publish_warehouse  ── R2 ──▶  plotline.duckdb ─▶ downloaded on boot
                               └─ R2 ──▶  explorer_data.json
                                                      + Neon Postgres (api_keys, plan, waitlist)
 FRONTEND (Vercel)                                    + Clerk (auth) · Stripe (billing)
   web/index.html (API-backed shell) ── fetch ──▶ explorer_data.json (R2/CDN)
```

## What's built and verified

| Component | Where | Status |
|---|---|---|
| Hardened read API — `/health`, `/ready`, CORS, rate limit, JSON logs | `src/api/{main,config,ratelimit,warehouse_loader}.py` | ✅ |
| Postgres-backed API keys (static fallback) | `src/api/auth.py` | ✅ |
| Billing — Stripe checkout + webhook, **waitlist-gated** | `src/api/billing.py` | ✅ (inert w/o keys) |
| Warehouse download-on-boot | `warehouse_loader.py` (uses `PLOTLINE_WAREHOUSE_URL`) | ✅ |
| Slim API image + healthcheck | `Dockerfile` | ✅ |
| Fly.io host config (scale-to-zero, `/ready` check) | `fly.toml` | ✅ |
| Refresh automation → publish to R2 | `.github/workflows/refresh.yml`, `src/db/publish_warehouse.py` | ✅ |
| API-backed frontend build (304 KB shell) | `build_explorer.py --mode api`, `vercel.json` | ✅ |
| Medallion pipeline + warehouse + explorer | `run_pipeline.py`, `src/db/warehouse.py`, `src/reports/build_explorer.py` | ✅ |

## Run locally

```bash
pip install -r requirements.txt && playwright install chromium
python run_pipeline.py --enrich 500 && python -m src.db.warehouse   # build the warehouse
docker compose up api                                               # http://localhost:8000/docs
# self-contained explorer (marketing/offline):
python -m src.reports.build_explorer --out reports/leesearch_explorer.html
```

## Deploy — one command each (all free tier)

1. **Object storage (Cloudflare R2)** — create a bucket, an API token, and enable a
   public URL (or a custom domain). Note `R2_ENDPOINT`, keys, bucket, `R2_PUBLIC_BASE`.
2. **App DB (Neon)** — create a Postgres project; copy `DATABASE_URL`. Tables auto-create on boot.
3. **API (Fly.io):**
   ```bash
   fly launch --no-deploy            # uses fly.toml
   fly secrets set \
     PLOTLINE_WAREHOUSE_URL="$R2_PUBLIC_BASE/plotline.duckdb" \
     PLOTLINE_CORS_ORIGINS="https://<your-app>.vercel.app" \
     DATABASE_URL="$NEON_URL"
   fly deploy                        # merge-to-deploy after this
   ```
4. **Frontend (Vercel):** build the shell, then deploy `web/`:
   ```bash
   python -m src.reports.build_explorer --mode api \
     --data-url "$R2_PUBLIC_BASE/explorer_data.json" --out web/index.html
   vercel deploy --prebuilt web      # or connect the repo (outputDirectory=web)
   ```
5. **Refresh (GitHub Actions):** add repo secrets `R2_ENDPOINT, R2_BUCKET,
   R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_PUBLIC_BASE`. The `refresh` workflow
   runs daily (and on demand with an `enrich` count) → new data goes live with **no redeploy**.
   For a guaranteed heavy crawl, run locally and let `publish_warehouse.py` push the artifact.

## App backend (`src/app`, Phase 2b)

The accounts, fanboards, feed, media and claims API is a separate Fly app (`plotline-app`). It reads the same published warehouse, keeps its state in Neon, and keeps uploads in a **private** R2 bucket. Decisions: D-031 to D-042 in `docs/product/decisions.md`.

**Accounts you create** (not done from this repo):
- a Neon project
- a private R2 bucket plus an API token scoped to it
- a Resend account with a verified sending domain
- the Fly app

**Secrets** (`fly secrets set -a plotline-app KEY=value …`; the full list is in `fly.app.toml`):

| Secret | Value |
|---|---|
| `DATABASE_URL` | Neon connection string |
| `PLOTLINE_JWT_SECRET` | ≥ 32 random characters (`python -c "import secrets;print(secrets.token_urlsafe(48))"`) |
| `PLOTLINE_IP_SALT` | random; hashes guest IPs |
| `PLOTLINE_WAREHOUSE_URL` | https URL of the published `plotline.duckdb` |
| `PLOTLINE_CORS_ORIGINS`, `PLOTLINE_APP_BASE_URL` | the frontend origin |
| `PLOTLINE_EMAIL_SENDER=resend`, `RESEND_API_KEY`, `PLOTLINE_EMAIL_FROM` | email |
| `PLOTLINE_BLOB_STORE=r2`, `R2_ENDPOINT`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_APP_BUCKET` | uploads |
| `PLOTLINE_CLIENT_IP_HEADER` (optional) | a proxy header holding the client IP. Unset = rightmost `X-Forwarded-For` entry (D-042, O-18) |

**First deploy:**
```bash
fly apps create plotline-app
fly secrets set -a plotline-app DATABASE_URL=... PLOTLINE_JWT_SECRET=... # etc.
fly deploy -c fly.app.toml          # release command: alembic upgrade head
# grant yourself admin after signing up and confirming your email
fly ssh console -a plotline-app -C "python -m src.app.cli make-admin you@example.com"
```

**Migrations:** edit a table in a module's `repo.py`, then run `alembic revision --autogenerate -m "..."` and review the file. `pytest` fails if the models and migrations drift. The next deploy applies the revision.

**Daily jobs:** `.github/workflows/claim-docs-purge.yml` deletes claim documents 90 days after the decision (D-040). It needs the same secrets as repository secrets, and skips itself while `DATABASE_URL` is unset.

**Not verified from this sandbox:**
- `docker build` (no Docker daemon here). Instead, the image's file set and `requirements-app.txt` were installed into a clean venv and smoke-tested with uvicorn.
- Fly's `release_command` key and client-IP header (fly.io was unreachable) — O-18.

## Turning on billing (after the gates below)

```bash
fly secrets set PLOTLINE_BILLING_ENABLED=true \
  STRIPE_SECRET_KEY=sk_live_... STRIPE_WEBHOOK_SECRET=whsec_... STRIPE_PRICE_PRO=price_...
# Stripe dashboard → webhook → https://<api>/billing/webhook (event checkout.session.completed)
# Clerk → wrap the frontend; pass the Clerk user_id to /billing/checkout and /billing/me.
```
Until then, `POST /billing/checkout` records a **waitlist** entry instead of charging.

## Operations (Sana's gates — all satisfied)

- **Health:** liveness `/health`, readiness `/ready` (verifies the warehouse is queryable); wired into `Dockerfile` HEALTHCHECK, `fly.toml`, and `docker-compose`.
- **Resource limits:** `shared-cpu-1x` / 256 MB in `fly.toml`; scale-to-zero when idle.
- **One-command / merge-to-deploy:** `fly deploy`; no SSH, no manual state.
- **Rollback:** `fly releases` → `fly deploy --image <previous>` (or `fly releases rollback`). Data rollback = re-publish a prior `plotline.duckdb` to R2.
- **Logs:** structured JSON to stdout → `fly logs`. **Monitoring:** add Sentry DSN + an uptime ping on `/ready`.

## Go-live gating (the CEO call)

- **Free public launch:** ready now — deploy API + frontend + refresh.
- **Turn on payments (`PLOTLINE_BILLING_ENABLED=true`)** only when **all** are green:
  1. **Legal** — per-platform ToS/robots review for scraping + data resale in your jurisdiction.
  2. **Coverage** — deepen ≥3 platforms (run `detail_crawler --all`; build the synopsis/NLP layer).
  3. **Demand** — 3 design partners actively using it.

## Known data gaps (structure complete, population ongoing)

- Coverage uneven (deep on Webtoon/Wattpad); genre ~21%; synopsis NLP (L2) unbuilt.
- Webtoon rank is a daily *weekday schedule* → short-window rank movement is thin (see explorer note).
- Publisher captured only where platforms expose it (GlobalComix).
