"""Environment-driven API configuration.

Everything the deployed API needs is read from the environment so the same image
runs locally, in CI, and on the host with no code changes (12-factor). Sensible
local defaults keep `uvicorn src.api.main:app` working with zero setup.
"""
from __future__ import annotations

import os

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))


def _csv(name: str, default: str = "") -> list[str]:
    return [x.strip() for x in os.environ.get(name, default).split(",") if x.strip()]


class Config:
    ENV = os.environ.get("PLOTLINE_ENV", "dev")

    # Market-data warehouse: serve a local file, or download one on boot (R2/HTTPS).
    WAREHOUSE_PATH = os.environ.get(
        "PLOTLINE_WAREHOUSE_PATH", os.path.join(_ROOT, "data", "plotline.duckdb"))
    WAREHOUSE_URL = os.environ.get("PLOTLINE_WAREHOUSE_URL")  # optional; pulled if the file is absent

    # CORS: lock to the frontend origin(s) in prod; default open for local dev.
    CORS_ORIGINS = _csv("PLOTLINE_CORS_ORIGINS", "*") or ["*"]

    # Rate limits (slowapi syntax). Public endpoints vs the premium feed.
    RATE_LIMIT = os.environ.get("PLOTLINE_RATE_LIMIT", "60/minute")
    FEED_RATE_LIMIT = os.environ.get("PLOTLINE_FEED_RATE_LIMIT", "600/minute")

    # App state (users↔plan, API keys, watchlists). Neon Postgres in prod; when
    # unset, the API falls back to the static PLOTLINE_API_KEYS list below.
    DATABASE_URL = os.environ.get("DATABASE_URL")
    STATIC_API_KEYS = _csv("PLOTLINE_API_KEYS")  # comma list; empty = no static keys

    # Billing (Stripe). BILLING_ENABLED is the CEO gate: while False the "Upgrade"
    # flow collects a waitlist instead of charging (ship Free until PMF + legal green).
    BILLING_ENABLED = os.environ.get("PLOTLINE_BILLING_ENABLED", "false").lower() == "true"
    STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY")
    STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET")
    STRIPE_PRICES = {"pro": os.environ.get("STRIPE_PRICE_PRO"),
                     "enterprise": os.environ.get("STRIPE_PRICE_ENTERPRISE")}
    CHECKOUT_SUCCESS_URL = os.environ.get("PLOTLINE_CHECKOUT_SUCCESS_URL", "https://plotline.app/welcome")
    CHECKOUT_CANCEL_URL = os.environ.get("PLOTLINE_CHECKOUT_CANCEL_URL", "https://plotline.app/pricing")

    @property
    def is_prod(self) -> bool:
        return self.ENV == "prod"


cfg = Config()
