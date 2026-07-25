"""API-key validation and plan lookup.

Two backends, chosen at runtime:
  * **Postgres** (Neon) when ``DATABASE_URL`` is set — keys live in an ``api_keys``
    table (``key``, ``plan``, ``active``), provisioned by the billing webhook.
  * **Static env list** (``PLOTLINE_API_KEYS``) as a zero-dependency fallback for
    local dev and the free launch before billing is switched on.

``psycopg`` is imported lazily so the base API has no hard Postgres dependency.
"""
from __future__ import annotations

import logging
import secrets

from src.api.config import cfg

log = logging.getLogger("plotline.api")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS api_keys (
    key        TEXT PRIMARY KEY,
    plan       TEXT NOT NULL DEFAULT 'pro',
    user_id    TEXT,
    active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS waitlist (
    user_id    TEXT,
    email      TEXT,
    plan       TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def _pg():
    """Return a psycopg connection, or None if unavailable/unconfigured."""
    if not cfg.DATABASE_URL:
        return None
    try:
        import psycopg  # lazy: only needed when DATABASE_URL is set
    except ImportError:
        log.warning("DATABASE_URL set but psycopg not installed — using static keys")
        return None
    try:
        return psycopg.connect(cfg.DATABASE_URL, connect_timeout=5)
    except Exception as e:  # noqa: BLE001 — never let auth take the API down
        log.error("postgres connect failed (%s) — falling back to static keys", e)
        return None


def init_schema() -> None:
    con = _pg()
    if con is None:
        return
    with con, con.cursor() as cur:
        cur.execute(_SCHEMA)


def plan_for_key(key: str | None) -> str | None:
    """Return the plan for a key ('pro'/'enterprise'/...), or None if invalid."""
    if not key:
        return None
    con = _pg()
    if con is not None:
        try:
            with con, con.cursor() as cur:
                cur.execute("SELECT plan FROM api_keys WHERE key=%s AND active", (key,))
                row = cur.fetchone()
                return row[0] if row else None
        except Exception as e:  # noqa: BLE001
            log.error("key lookup failed (%s) — falling back to static keys", e)
        finally:
            con.close()
    return "pro" if key in cfg.STATIC_API_KEYS else None


def valid_key(key: str | None) -> bool:
    return plan_for_key(key) is not None


def provision_key(user_id: str, plan: str = "pro") -> str | None:
    """Mint + store a per-user API key (called by the billing webhook on upgrade).
    Returns the key, or None if there is no Postgres backend to store it in."""
    con = _pg()
    if con is None:
        log.error("provision_key: no DATABASE_URL — cannot persist a key")
        return None
    key = "pk_" + secrets.token_urlsafe(24)
    with con, con.cursor() as cur:
        cur.execute("INSERT INTO api_keys (key, plan, user_id) VALUES (%s, %s, %s)",
                    (key, plan, user_id))
    con.close()
    log.info("provisioned %s key for user %s", plan, user_id)
    return key


def keys_for_user(user_id: str) -> list[dict]:
    """Active keys for a user (the frontend shows these on the account page)."""
    con = _pg()
    if con is None:
        return []
    try:
        with con, con.cursor() as cur:
            cur.execute("SELECT key, plan FROM api_keys WHERE user_id=%s AND active", (user_id,))
            return [{"key": k, "plan": p} for k, p in cur.fetchall()]
    finally:
        con.close()


def add_to_waitlist(user_id: str | None, email: str | None, plan: str) -> None:
    con = _pg()
    if con is None:
        log.info("waitlist (no DB): user=%s email=%s plan=%s", user_id, email, plan)
        return
    with con, con.cursor() as cur:
        cur.execute("INSERT INTO waitlist (user_id, email, plan) VALUES (%s, %s, %s)",
                    (user_id, email, plan))
    con.close()
