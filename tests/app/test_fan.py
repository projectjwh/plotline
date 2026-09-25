from datetime import datetime, timedelta, timezone

from src.app.fan.ratings import BayesianAggregator
from src.app.fan.scout import LeadTimeRule
from tests.app.conftest import register, verified


def test_bayesian_aggregator():
    a = BayesianAggregator(prior_mean=7.0, prior_weight=20)
    r = a.aggregate([10, 10])
    assert r["mean"] == 10.0 and r["votes"] == 2 and r["histogram"]["10"] == 2
    assert r["weighted"] == round((20 * 7 + 20) / 22, 2)
    assert a.aggregate([])["weighted"] is None


def test_rating_upsert_and_reviews(client):
    _, h = register(client, "reader1")
    assert client.put("/ratings/webtoon_global:1", json={"score": 11}).status_code == 401
    assert client.put("/ratings/webtoon_global:1", headers=h, json={"score": 11}).status_code == 422
    client.put("/ratings/webtoon_global:1", headers=h, json={"score": 6})
    s = client.put("/ratings/webtoon_global:1", headers=h, json={"score": 9, "review": "Great"}).json()
    assert s["votes"] == 1 and s["mean"] == 9.0
    assert client.get("/reviews/webtoon_global:1").json()[0]["review"] == "Great"
    assert client.get("/titles/webtoon_global:1").json()["fan_rating"]["votes"] == 1
    assert client.put("/ratings/nope:1", headers=h, json={"score": 5}).status_code == 404


def test_owner_votes_excluded_even_when_approved_later(client, admin):
    _, ah = admin
    user, h = register(client, "hseo")
    client.put("/ratings/webtoon_global:1", headers=h, json={"score": 10})
    assert client.get("/titles/webtoon_global:1").json()["fan_rating"]["votes"] == 1
    r = client.post("/claims", headers=h, data={"claim_type": "author", "entity_ref": "H. Seo"},
                    files=[("files", ("d.pdf", b"%PDF-1.4 x", "application/pdf"))])
    client.post(f"/admin/claims/{r.json()['id']}/decision", headers=ah, json={"decision": "approve"})
    assert client.get("/titles/webtoon_global:1").json()["fan_rating"]["votes"] == 0


def test_follow_lists_wishlist(client):
    _, h = register(client, "reader1")
    assert client.post("/follows", headers=h, json={"target_type": "title", "ref": "webtoon_global:1"}).status_code == 204
    assert client.post("/follows", headers=h, json={"target_type": "author", "ref": "H. Seo"}).status_code == 204
    assert len(client.get("/me/follows", headers=h).json()) == 2
    assert client.get("/titles/webtoon_global:1").json()["followers"] == 1
    assert client.get("/credits/author/H. Seo").json()["followers"] == 1
    lst = client.post("/lists", headers=h, json={"name": "Best dark fantasy"}).json()
    client.post(f"/lists/{lst['id']}/items", headers=h, json={"title_key": "webtoon_global:1"})
    assert client.post(f"/lists/{lst['id']}/items", headers=h, json={"title_key": "webtoon_global:1"}).status_code == 409
    _, other = register(client, "reader2")
    assert client.post(f"/lists/{lst['id']}/items", headers=other, json={"title_key": "tapas_io:3"}).status_code == 403
    assert [i["title_key"] for i in client.get(f"/lists/{lst['id']}").json()["items"]] == ["webtoon_global:1"]
    assert client.post("/wishlist/webtoon_global:1", headers=h, json={"medium": "anime"}).json() == {"anime": 1}
    assert client.post("/wishlist/webtoon_global:1", headers=h, json={"medium": "anime"}).status_code == 409
    assert client.post("/wishlist/webtoon_global:1", headers=h, json={"medium": "opera"}).status_code == 422
    board = client.get("/wishlist", params={"medium": "anime"}).json()
    assert board[0]["title_key"] == "webtoon_global:1" and board[0]["total"] == 1 and board[0]["recent"] == 1


def test_scout_points_on_rising(client, admin):
    _, ah = admin
    user, h = register(client, "scout1")
    client.post("/follows", headers=h, json={"target_type": "title", "ref": "tapas_io:3"})
    at = (datetime.now(timezone.utc) + timedelta(days=10)).isoformat()  # tz-aware input is normalised
    assert client.post("/admin/events/rising", headers=ah, json={"title_key": "tapas_io:3", "at": at}).status_code == 200
    prof = client.get("/users/scout1").json()
    assert prof["scout_points"] == 27 or prof["scout_points"] == 30  # 9–10 whole days × 3 points
    assert client.get("/scouts").json()[0]["handle"] == "scout1"
    # firing again does not double-award
    client.post("/admin/events/rising", headers=ah, json={"title_key": "tapas_io:3", "at": at})
    assert client.get("/users/scout1").json()["scout_points"] == prof["scout_points"]


def test_lead_time_rule_caps():
    r = LeadTimeRule(points_per_day=3, max_points=500)
    t = datetime(2026, 1, 1)
    assert r.points(t, t + timedelta(days=10)) == 30
    assert r.points(t, t + timedelta(days=1000)) == 500
    assert r.points(t, t - timedelta(days=1)) == 0
