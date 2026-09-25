from src.app.core.registry import Registry
from src.app.kpi.projector import KpiProjector, round_sig
from tests.app.conftest import register, verified

import pytest


def test_register_login_me(client):
    user, h = register(client, "reader1")
    assert client.get("/me", headers=h).json()["user"]["handle"] == "reader1"
    r = client.post("/auth/login", json={"email": "reader1@x.test", "password": "correct-horse-1"})
    assert r.status_code == 200 and r.json()["token"]


def test_bad_password_and_duplicates(client):
    register(client, "reader1")
    assert client.post("/auth/login", json={"email": "reader1@x.test", "password": "nope-nope-nope"}).status_code == 401
    r = client.post("/auth/register", json={"email": "reader1@x.test", "password": "correct-horse-1", "handle": "other"})
    assert r.status_code == 409
    r = client.post("/auth/register", json={"email": "z@x.test", "password": "short", "handle": "zzz"})
    assert r.status_code == 422


def test_bad_token_rejected(client):
    assert client.get("/me", headers={"Authorization": "Bearer garbage"}).status_code == 401
    assert client.get("/me").status_code == 401


def test_signup_never_grants_admin(client, admin):
    _, h = register(client, "sneaky", "someone@x.test")
    assert client.get("/me", headers=h).json()["user"]["is_admin"] is False
    _, ah = admin
    assert client.get("/me", headers=ah).json()["user"]["is_admin"] is True


def test_round_sig():
    assert round_sig(14_814_804) == 15_000_000
    assert round_sig(0.0123) == 0.012
    assert round_sig(None) is None and round_sig(True) is True


def test_projector_hides_undeclared_and_flags_models():
    p = KpiProjector({"audiences": ["fan", "investor"], "public": ["title"],
                      "fields": {"views": {"fan": "rounded", "investor": "shown"},
                                 "est_usd": {"fan": "hidden", "investor": "shown", "is_model": True}}})
    row = {"title": "X", "views": 14_814_804, "est_usd": 10.0, "secret": 1}
    assert p.project(row, {"fan"}) == {"title": "X", "views": 15_000_000}
    inv = p.project(row, {"fan", "investor"})
    assert inv["views"] == 14_814_804 and inv["est_usd"] == 10.0 and inv["model_fields"] == ["est_usd"]
    assert "secret" not in inv


def test_projector_rejects_bad_levels():
    with pytest.raises(ValueError):
        KpiProjector({"audiences": ["fan"], "fields": {"x": {"fan": "maybe"}}})


def test_fan_never_sees_premium_fields(client):
    t = client.get("/titles/webtoon_global:1").json()
    assert t["plotscore"] == 90.0 and t["views"] == 15_000_000          # rounded for fans
    for hidden in ("est_usd", "reach_pct", "like_through", "readiness", "momentum", "est_usd_low"):
        assert hidden not in t
    listing = client.get("/titles").json()["items"]
    assert listing and all("est_usd" not in x for x in listing)


def test_fan_cannot_sort_by_hidden_kpi(client):
    assert client.get("/titles", params={"sort": "est_usd"}).status_code == 403
    assert client.get("/titles", params={"sort": "plotscore"}).status_code == 200


def test_investor_sees_premium_fields(client, admin):
    _, ah = admin
    _, h = verified(client, ah, "fund1", "investor_entity", "Lumen Story Partners", "investor")
    t = client.get("/titles/webtoon_global:1", headers=h).json()
    assert t["views"] == 14_814_804 and t["est_usd"] == 1000.0 and "readiness" in t
    assert "est_usd" in t["model_fields"]


def test_kpi_catalog_exposes_matrix(client):
    cat = {r["field"]: r for r in client.get("/kpis/catalog").json()}
    assert cat["est_usd"]["fan"] == "hidden" and cat["est_usd"]["is_model"] is True
    assert cat["cover_coverage_pct"]["investor"] == "hidden"


def test_registry():
    r = Registry("thing")
    r.register("a")(lambda **k: k)
    assert r.create("a", x=1) == {"x": 1}
    with pytest.raises(KeyError):
        r.create("b")
    with pytest.raises(ValueError):
        r.register("a")(lambda: None)
