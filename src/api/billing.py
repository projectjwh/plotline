"""Billing router — Stripe Checkout + webhook for the Free / Pro / Enterprise tiers.

Design (matches the CEO gate in the deployment plan): while
``PLOTLINE_BILLING_ENABLED`` is False, the "Upgrade" flow records a **waitlist**
entry instead of charging — the SaaS rails are live but money stays off until
PMF + legal are green. Flip the flag (and set STRIPE_* + a price id) to turn on
real checkout. ``stripe`` is imported lazily so the API needs no billing deps
until billing is switched on.

Identity: the frontend authenticates the user with Clerk and passes the Clerk
``user_id`` (verify the Clerk JWT here before production charging — left as the
one integration seam for the account owner).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from src.api import auth
from src.api.config import cfg

log = logging.getLogger("plotline.api")
router = APIRouter(prefix="/billing", tags=["billing"])

TIERS = [
    {"id": "free", "name": "Free", "price_usd": 0,
     "features": ["Explorer + leaderboard", "Genre/platform/rank views", "Rate-limited API"]},
    {"id": "pro", "name": "Pro", "price_usd": 49,
     "features": ["Full data feed (/feed)", "Watchlists + alerts", "Higher rate limits"]},
    {"id": "enterprise", "name": "Enterprise", "price_usd": None,
     "features": ["Bulk export", "SLA + support", "Custom coverage"]},
]


class CheckoutReq(BaseModel):
    plan: str = "pro"
    user_id: str | None = None
    email: str | None = None


@router.get("/plans", summary="Pricing tiers + whether charging is live")
def plans():
    return {"billing_enabled": cfg.BILLING_ENABLED, "tiers": TIERS}


@router.post("/checkout", summary="Start upgrade — Stripe Checkout, or waitlist if billing is off")
def checkout(req: CheckoutReq):
    if req.plan not in ("pro", "enterprise"):
        raise HTTPException(400, "Unknown plan.")
    if not cfg.BILLING_ENABLED:
        auth.add_to_waitlist(req.user_id, req.email, req.plan)
        return {"waitlisted": True,
                "message": "Pro is in private beta — you're on the waitlist and we'll reach out."}
    price = cfg.STRIPE_PRICES.get(req.plan)
    if not (cfg.STRIPE_SECRET_KEY and price):
        raise HTTPException(503, "Billing is enabled but Stripe is not configured.")
    import stripe  # lazy
    stripe.api_key = cfg.STRIPE_SECRET_KEY
    session = stripe.checkout.Session.create(
        mode="subscription",
        line_items=[{"price": price, "quantity": 1}],
        success_url=cfg.CHECKOUT_SUCCESS_URL,
        cancel_url=cfg.CHECKOUT_CANCEL_URL,
        customer_email=req.email,
        client_reference_id=req.user_id or "",
        metadata={"plan": req.plan, "user_id": req.user_id or ""},
    )
    return {"url": session.url}


@router.post("/webhook", summary="Stripe webhook — provisions an API key on successful upgrade")
async def webhook(request: Request):
    if not (cfg.STRIPE_SECRET_KEY and cfg.STRIPE_WEBHOOK_SECRET):
        raise HTTPException(503, "Billing not configured.")
    import stripe  # lazy
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    try:
        event = stripe.Webhook.construct_event(payload, sig, cfg.STRIPE_WEBHOOK_SECRET)
    except Exception as e:  # noqa: BLE001 — bad signature / malformed payload
        raise HTTPException(400, f"Webhook signature verification failed: {e}")
    if event["type"] == "checkout.session.completed":
        obj = event["data"]["object"]
        meta = obj.get("metadata") or {}
        user_id = meta.get("user_id") or obj.get("client_reference_id") or "unknown"
        auth.provision_key(user_id, meta.get("plan", "pro"))
    return {"received": True}


@router.get("/me", summary="A user's active API keys + plan (account page)")
def me(user_id: str):
    keys = auth.keys_for_user(user_id)
    return {"user_id": user_id, "plan": keys[0]["plan"] if keys else "free", "keys": keys}
