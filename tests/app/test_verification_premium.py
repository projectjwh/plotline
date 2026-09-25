import shutil

import yaml
from fastapi.testclient import TestClient

from src.app.core.config import ROOT
from src.app.main import create_app
from src.app.valuation.revenue_multiple import RevenueMultipleModel
from tests.app.conftest import PDF, register, verified


def _claim(client, h, **data):
    files = data.pop("files", [("files", ("d.pdf", PDF, "application/pdf"))])
    return client.post("/claims", headers=h, data=data, files=files)


def test_claim_validation(client):
    _, h = register(client, "hseo")
    assert _claim(client, h, claim_type="author", entity_ref="Nobody").status_code == 404
    assert _claim(client, h, claim_type="wizard", entity_ref="H. Seo").status_code == 422
    exe = [("files", ("x.pdf", b"MZ\x90\x00 not a pdf", "application/pdf"))]
    assert _claim(client, h, claim_type="author", entity_ref="H. Seo", files=exe).status_code == 422
    big = [("files", ("big.pdf", PDF + b"0" * (10 * 1024 * 1024), "application/pdf"))]
    assert _claim(client, h, claim_type="author", entity_ref="H. Seo", files=big).status_code == 422
    assert _claim(client, h, claim_type="author", entity_ref="h. seo").status_code == 201  # case-insensitive match
    assert _claim(client, h, claim_type="author", entity_ref="h. seo").status_code == 409  # duplicate pending
    mine = client.get("/claims/mine", headers=h).json()
    assert mine[0]["entity_name"] == "H. Seo" and mine[0]["status"] == "pending" and "doc_keys" not in mine[0]


def test_admin_review_and_documents(client, admin):
    _, ah = admin
    _, h = register(client, "pub")
    c = _claim(client, h, claim_type="publisher", entity_ref="Studio Nara").json()
    assert client.get("/admin/claims", headers=h).status_code == 403
    q = client.get("/admin/claims", headers=ah).json()
    key = q[0]["doc_keys"][0]
    assert client.get(f"/admin/claims/{c['id']}/documents/{key}", headers=h).status_code == 403
    d = client.get(f"/admin/claims/{c['id']}/documents/{key}", headers=ah)
    assert d.status_code == 200 and d.content == PDF and d.headers["content-type"] == "application/pdf"
    assert client.get(f"/admin/claims/{c['id']}/documents/..%2F..%2Fetc", headers=ah).status_code == 404
    assert client.post(f"/admin/claims/{c['id']}/decision", headers=ah, json={"decision": "reject"}).status_code == 422
    r = client.post(f"/admin/claims/{c['id']}/decision", headers=ah, json={"decision": "approve"})
    assert r.json()["status"] == "approved"
    assert client.post(f"/admin/claims/{c['id']}/decision", headers=ah, json={"decision": "approve"}).status_code == 409


def test_premium_gating(client, admin):
    _, ah = admin
    _, fan = register(client, "fan1")
    assert client.get("/premium/valuation/webtoon_global:1", headers=fan).status_code == 403
    assert client.get("/premium/valuation/webtoon_global:1").status_code == 403
    # approved claim but no plan → still not entitled
    user, h = register(client, "hseo")
    c = _claim(client, h, claim_type="author", entity_ref="H. Seo").json()
    client.post(f"/admin/claims/{c['id']}/decision", headers=ah, json={"decision": "approve"})
    assert client.get("/premium/valuation/webtoon_global:1", headers=h).status_code == 403
    me = client.get("/me", headers=h).json()["entitlement"]
    assert me["requirements"]["author"] == {"claim": True, "plan": False, "claim_types": ["author", "title"]}
    # plan without the matching claim type → not an investor
    client.post("/admin/grants", headers=ah, json={"user_id": user["id"], "plan": "investor"})
    assert client.get("/me", headers=h).json()["entitlement"]["personas"] == []
    client.post("/admin/grants", headers=ah, json={"user_id": user["id"], "plan": "author"})
    assert client.get("/me", headers=h).json()["entitlement"]["personas"] == ["author"]
    assert client.get("/premium/valuation/webtoon_global:1", headers=h).status_code == 200


def test_valuation_null_until_multiples_configured(client, admin):
    _, ah = admin
    _, h = verified(client, ah, "fund", "investor_entity", "Lumen", "investor")
    v = client.get("/premium/valuation/webtoon_global:1", headers=h).json()
    assert v["is_model"] is True and v["valuation"] is None and "not configured" in v["reason"]
    assert v["revenue_annual"] == {"low": 4800.0, "mid": 12000.0, "high": 30000.0}


def test_valuation_band_with_configured_multiples(settings, tmp_path):
    pol = tmp_path / "policy"
    shutil.copytree(ROOT / "config" / "policy", pol)
    app_yaml = yaml.safe_load(open(pol / "app.yaml"))
    app_yaml["valuation"]["base_multiple"] = {"low": 2, "mid": 4, "high": 6}
    yaml.safe_dump(app_yaml, open(pol / "app.yaml", "w"))
    settings.policy_dir = str(pol)
    client = TestClient(create_app(settings))
    from tests.app.conftest import make_admin
    _, ah = make_admin(client)
    _, h = verified(client, ah, "fund", "investor_entity", "Lumen", "investor")
    v = client.get("/premium/valuation/webtoon_global:1", headers=h).json()["valuation"]
    assert v["low"] <= v["mid"] <= v["high"]


def test_revenue_multiple_adjustment_is_clamped():
    m = RevenueMultipleModel({"low": 1, "mid": 1, "high": 1},
                             {"momentum_weight": 10, "completed_bonus": 0, "platform_weight": 0, "clamp": [0.5, 2.0]})
    assert m.value({"est_usd": 100, "momentum_pct": 1.0})["adjustment"] == 2.0
    assert m.value({"est_usd": 100, "momentum_pct": 0.0})["adjustment"] == 0.5
    assert m.value({"est_usd": None})["valuation"] is None


def test_premium_screener_compare_portfolio(client, admin):
    _, ah = admin
    _, h = verified(client, ah, "nara", "publisher", "Studio Nara", "publisher")
    s = client.get("/premium/screener", headers=h, params={"min_readiness": 0, "status": "completed"}).json()
    assert s["total"] == 3 and all("readiness" in x for x in s["items"])
    cmp = client.get("/premium/compare", headers=h, params={"ids": "webtoon_global:1,tapas_io:3"}).json()
    assert [c["comic_id"] for c in cmp] == ["webtoon_global:1", "tapas_io:3"] and "reach_pct" in cmp[0]
    assert client.get("/premium/compare", headers=h, params={"ids": "webtoon_global:1"}).status_code == 422
    pf = client.get("/premium/portfolio", headers=h).json()
    assert {t["comic_id"] for t in pf["titles"]} == {"webtoon_global:1", "webtoon_global:2", "webtoon_global:6",
                                                     "webtoon_global:11"}
    # revoking the claim removes access
    cid = client.get("/admin/claims", headers=ah, params={"status": "approved"}).json()[0]["id"]
    client.post(f"/admin/claims/{cid}/decision", headers=ah, json={"decision": "revoke", "note": "expired"})
    assert client.get("/premium/portfolio", headers=h).status_code == 403
