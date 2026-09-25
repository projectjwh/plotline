"""Fixtures: a tiny analytics warehouse with the real column names, plus a fresh app DB per test."""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta

import duckdb
import pytest
from fastapi.testclient import TestClient

from src.app.core.config import ROOT, Settings
from src.app.core.db import load_tables, make_engine, metadata
from src.app.main import create_app

ADMIN = "admin@plotline.test"
DATES = [date(2026, 9, 20) + timedelta(days=i) for i in range(5)]

# comic_id, title, genre, author, publisher, content_type, status, est_usd, momentum_pct, like_through, momentum
TITLES = [
    ("webtoon_global:1", "Tower of Ash", "Fantasy", "H. Seo", "Studio Nara", "comic", "ongoing", 1000.0, 0.9, 0.05, 12),
    ("webtoon_global:2", "Glass Orchard", "Fantasy", "M. Arden", "Studio Nara", "comic", "hiatus", 800.0, 0.3, 0.04, -3),
    ("tapas_io:3", "Nine Lanterns", "Fantasy", "K. Lim", "Moonbeam", "comic", "ongoing", 300.0, 0.95, 0.06, 20),
    ("royalroad:4", "The Salt Archivist", "Fantasy", "H. Seo", None, "novel", "completed", 200.0, 0.6, 0.02, 2),
    ("webnovel:5", "Red Ledger", "Fantasy", "J. Park", "Moonbeam", "novel", "ongoing", 150.0, 0.7, 0.01, 5),
    ("webtoon_global:6", "Velvet Oath", "Romance", "L. Moreau", "Studio Nara", "comic", "ongoing", 900.0, 0.4, 0.07, 0),
    ("tapas_io:7", "Paper Moth", "Romance", "A. Reyes", None, "comic", "completed", 120.0, 0.2, 0.03, -5),
    ("wattpad:8", "Crown Queen", "Romance", "Y. Chen", None, "novel", "ongoing", 50.0, 0.5, 0.02, 1),
    ("webtoon_global:9", "Winter Heir", "Romance", "E. Han", "Moonbeam", "comic", "ongoing", 400.0, 0.8, 0.05, 8),
    ("tapas_io:10", "Iron Sect", "Action", "T. Baek", None, "comic", "ongoing", 250.0, 0.55, 0.04, 0),
    ("webtoon_global:11", "Ember Knight", "Action", "N. Ito", "Studio Nara", "comic", "completed", 600.0, 0.65, 0.05, 4),
    ("royalroad:12", "Starfall Blade", "Action", "C. Vale", None, "novel", "ongoing", 90.0, 0.45, 0.03, 0),
]


def _daily_rows():
    rows = []
    for i, t in enumerate(TITLES):
        cid = t[0]
        base_views = 1_000_000 * (12 - i)
        for d_i, d in enumerate(DATES):
            if cid == "royalroad:12" and d_i < 4:  # new listing: first seen on the last date
                continue
            growth = 1 + 0.01 * (i % 4) * d_i        # deterministic growth by title
            views = int(base_views * growth)
            rank = (i + 1) + (0 if d_i < 4 else (-2 if cid == "tapas_io:3" else 1 if cid == "webtoon_global:2" else 0))
            # two snapshots on the same day for title 1: the later one must win (dedupe rule)
            rows.append((cid, "src", t[1], datetime(d.year, d.month, d.day, 8), d, rank, views, 10, 100, 5))
            if cid == "webtoon_global:1":
                rows.append((cid, "src", t[1], datetime(d.year, d.month, d.day, 20), d, rank, views + 1000, 10, 100, 5))
    return rows


def build_warehouse(path: str) -> None:
    con = duckdb.connect(path)
    con.execute("""CREATE TABLE fact_title (comic_id VARCHAR, source VARCHAR, platform VARCHAR, title VARCHAR,
        genre VARCHAR, author VARCHAR, publisher VARCHAR, content_type VARCHAR, views BIGINT, subscribers BIGINT,
        likes BIGINT, comments BIGINT, rating DOUBLE, best_rank INTEGER, latest_rank INTEGER, reach_pct DOUBLE,
        momentum_pct DOUBLE, engagement_pct DOUBLE, monetization_pct DOUBLE, quality_pct DOUBLE, plotscore DOUBLE,
        est_usd DOUBLE, momentum INTEGER, like_through DOUBLE, subs_per_view DOUBLE, cover VARCHAR, synopsis VARCHAR,
        status VARCHAR, tags VARCHAR)""")
    for i, (cid, title, genre, author, pub, ctype, status, est, mom_pct, lt, mom) in enumerate(TITLES):
        views = 1_234_567 * (12 - i)  # not round, so fan rounding is observable
        con.execute("INSERT INTO fact_title VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    [cid, cid.split(":")[0], cid.split(":")[0], title, genre, author, pub, ctype, views, views // 100,
                     views // 20, 50, 9.1, i + 1, i + 1, 1 - i / 12, mom_pct, 0.5, 0.5, 0.5, round(90 - i * 5.5, 1),
                     est, mom, lt, 0.01, None, "synopsis", status, None])
    con.execute("""CREATE TABLE fact_title_daily (comic_id VARCHAR, source VARCHAR, title VARCHAR, scraped_at TIMESTAMP,
        date DATE, rank INTEGER, views BIGINT, likes BIGINT, subscribers BIGINT, comments BIGINT)""")
    con.executemany("INSERT INTO fact_title_daily VALUES (?,?,?,?,?,?,?,?,?,?)", _daily_rows())
    # silver-episodes layout (src/db/warehouse.py): platform date strings, one malformed
    con.execute("""CREATE TABLE fact_episode (comic_id VARCHAR, episode_no INTEGER, episode_title VARCHAR,
        upload_date VARCHAR, likes BIGINT)""")
    con.executemany("INSERT INTO fact_episode VALUES (?,?,?,?,?)", [
        ("tapas_io:3", 41, "Ep. 41 - The Ninth Flame", "Sep 23, 2026", 900),
        ("tapas_io:3", 40, "Ep. 40", "Aug 1, 2026", 800),           # older than the feed window
        ("tapas_io:3", 39, "Ep. 39", "not a date", 700),             # unparseable: skipped
        ("webtoon_global:6", 12, "Ep. 12", "2026-09-22", 500)])      # not followed in the tests
    con.close()


def _app_db_url(tmp_path) -> str:
    """SQLite per test by default. Set PLOTLINE_TEST_PG_URL to run the suite on Postgres (schema reset per test)."""
    pg = os.environ.get("PLOTLINE_TEST_PG_URL")
    if not pg:
        return f"sqlite:///{tmp_path / 'app.db'}"
    load_tables()
    eng = make_engine(pg)
    metadata.drop_all(eng)
    eng.dispose()
    return pg


@pytest.fixture
def settings(tmp_path) -> Settings:
    wh = tmp_path / "plotline.duckdb"
    build_warehouse(str(wh))
    return Settings(env="test", app_db_url=_app_db_url(tmp_path), warehouse_path=str(wh),
                    doc_storage_dir=str(tmp_path / "docs"), policy_dir=str(ROOT / "config" / "policy"),
                    jwt_secret="test-secret-" + "x" * 32, ip_hash_salt="test-salt", rate_limits=False)


@pytest.fixture
def app(settings):
    return create_app(settings)


@pytest.fixture
def client(app):
    return TestClient(app)


def register(client, handle: str, email: str | None = None, verify: bool = True) -> tuple[dict, dict]:
    r = client.post("/auth/register", json={"email": email or f"{handle}@x.test", "password": "correct-horse-1",
                                            "handle": handle})
    assert r.status_code == 201, r.text
    body = r.json()
    if verify:
        confirm_email(client, email or f"{handle}@x.test")
    return body["user"], {"Authorization": f"Bearer {body['token']}"}


def last_token(client, email: str, kind: str = "verify") -> str:
    """Read the newest emailed link for ``email`` from the console sender and return its token."""
    mails = [m for m in client.app.state.ctx.mailer.outbox if m["to"] == email and f"/{kind}?token=" in m["text"]]
    assert mails, f"no {kind} email for {email}"
    return mails[-1]["text"].split("token=")[1].split()[0]


def confirm_email(client, email: str) -> None:
    r = client.post("/auth/verify/confirm", json={"token": last_token(client, email)})
    assert r.status_code == 200, r.text


def make_admin(client, email: str = ADMIN) -> tuple[dict, dict]:
    user, h = register(client, "admin", email)
    client.app.state.ctx.identity.set_admin(email, True)  # same path as `python -m src.app.cli make-admin`
    return {**user, "is_admin": True}, h


@pytest.fixture
def admin(client):
    return make_admin(client)


PDF = b"%PDF-1.4\n% test document\n"


def verified(client, admin_headers, handle: str, claim_type: str, ref: str, plan: str) -> tuple[dict, dict]:
    """Register a user, submit and approve a claim, grant the plan."""
    user, h = register(client, handle)
    data = {"claim_type": claim_type, "entity_ref": ref}
    if claim_type == "investor_entity":
        data["entity_name"] = ref
    r = client.post("/claims", headers=h, data=data, files=[("files", ("doc.pdf", PDF, "application/pdf"))])
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    r = client.post(f"/admin/claims/{cid}/decision", headers=admin_headers, json={"decision": "approve"})
    assert r.status_code == 200, r.text
    assert client.post("/admin/grants", headers=admin_headers, json={"user_id": user["id"], "plan": plan}).status_code == 204
    return user, h
