from tests.app.conftest import register, verified


def _gallery(client, ref="webtoon_global:1"):
    r = client.get(f"/galleries/by/title/{ref}")
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _guest_post(client, gid, title="Theory", pw="pw1234"):
    return client.post(f"/galleries/{gid}/posts", json={"title": title, "body": "text", "nick": "ㅇㅇ", "password": pw})


def test_gallery_created_on_first_use_and_validated(client):
    gid = _gallery(client)
    assert _gallery(client) == gid
    assert client.get("/galleries/by/title/nope:1").status_code == 404
    assert client.get("/galleries/by/genre/Fantasy").status_code == 200
    assert client.get("/galleries/by/free/random").status_code == 404


def test_guest_post_edit_delete_with_password(client):
    gid = _gallery(client)
    r = _guest_post(client, gid)
    assert r.status_code == 201
    p = r.json()
    assert p["author"] == {"guest": True, "name": "ㅇㅇ", "ip_prefix": "?", "verified_owner": False}
    assert client.patch(f"/posts/{p['id']}", json={"body": "hacked", "password": "wrong"}).status_code == 403
    r = client.patch(f"/posts/{p['id']}", json={"body": "edited", "password": "pw1234"})
    assert r.status_code == 200 and r.json()["body"] == "edited"
    assert client.post(f"/posts/{p['id']}/delete", json={"password": "wrong"}).status_code == 403
    assert client.post(f"/posts/{p['id']}/delete", json={"password": "pw1234"}).status_code == 204
    assert client.get(f"/posts/{p['id']}").status_code == 404


def test_guest_needs_nick_and_password(client):
    gid = _gallery(client)
    r = client.post(f"/galleries/{gid}/posts", json={"title": "t", "body": "b"})
    assert r.status_code == 422


def test_account_post_and_comments_threading(client):
    gid = _gallery(client)
    _, h = register(client, "reader1")
    p = client.post(f"/galleries/{gid}/posts", headers=h, json={"title": "Hi", "body": "b"}).json()
    assert p["author"]["name"] == "reader1" and p["author"]["ip_prefix"] is None
    c1 = client.post(f"/posts/{p['id']}/comments", headers=h, json={"body": "first"}).json()
    c2 = client.post(f"/posts/{p['id']}/comments", json={"body": "reply", "parent_id": c1["id"], "nick": "g", "password": "pw1234"})
    assert c2.status_code == 201
    bad = client.post(f"/posts/{p['id']}/comments", headers=h, json={"body": "deep", "parent_id": c2.json()["id"]})
    assert bad.status_code == 422  # one level of replies only
    full = client.get(f"/posts/{p['id']}").json()
    assert len(full["comments"]) == 2 and full["views"] == 1


def test_votes_dedupe_self_vote_and_concept_promotion(client):
    gid = _gallery(client)
    _, owner = register(client, "author0")
    p = client.post(f"/galleries/{gid}/posts", headers=owner, json={"title": "Big theory", "body": "b"}).json()
    assert client.post("/votes", headers=owner, json={"target_type": "post", "target_id": p["id"], "value": 1}).status_code == 403
    last = None
    for i in range(10):  # concept_min_up = 10 in config/policy/app.yaml
        _, h = register(client, f"voter{i}")
        last = client.post("/votes", headers=h, json={"target_type": "post", "target_id": p["id"], "value": 1})
        assert last.status_code == 200
        if i == 8:
            assert last.json()["is_concept"] is False
    assert last.json() == {"up": 10, "down": 0, "is_concept": True}
    assert client.post("/votes", headers=h, json={"target_type": "post", "target_id": p["id"], "value": 1}).status_code == 409
    concept = client.get(f"/galleries/{gid}/posts", params={"tab": "concept"}).json()["items"]
    assert [x["id"] for x in concept] == [p["id"]]


def test_rate_limit(client):
    gid = _gallery(client)
    codes = [_guest_post(client, gid, title=f"t{i}").status_code for i in range(4)]
    assert codes == [201, 201, 201, 429]  # posts_per_minute = 3


def test_report_ban_flow(client, admin):
    _, ah = admin
    gid = _gallery(client)
    p = _guest_post(client, gid).json()
    _, h = register(client, "reporter")
    assert client.post("/reports", headers=h, json={"target_type": "post", "target_id": p["id"], "reason": "spam"}).status_code == 202
    assert client.post("/reports", headers=h, json={"target_type": "post", "target_id": p["id"], "reason": "spam"}).status_code == 409
    q = client.get("/admin/reports", headers=ah).json()
    assert q[0]["target_id"] == p["id"] and q[0]["reports"] == 1
    assert client.get("/admin/reports", headers=h).status_code == 403
    key = q[0]["voter_key"]
    assert client.post("/admin/reports/resolve", headers=ah, json={"target_type": "post", "target_id": p["id"], "action": "remove"}).status_code == 204
    assert client.get(f"/posts/{p['id']}").status_code == 404
    assert client.post("/admin/bans", headers=ah, json={"voter_key": key, "days": 1, "reason": "spam"}).status_code == 204
    r = _guest_post(client, gid)
    assert r.status_code == 403 and r.json()["error"] == "banned"


def test_verified_badge_and_notices(client, admin):
    _, ah = admin
    gid = _gallery(client)
    _, fan = register(client, "fan1")
    assert client.post(f"/galleries/{gid}/posts", headers=fan, json={"title": "N", "body": "b", "notice": True}).status_code == 403
    _, author = verified(client, ah, "hseo", "author", "H. Seo", "author")
    r = client.post(f"/galleries/{gid}/posts", headers=author, json={"title": "Season 3 date", "body": "b", "notice": True})
    assert r.status_code == 201 and r.json()["author"]["verified_owner"] is True and r.json()["is_notice"] is True
    other = _gallery(client, "webtoon_global:6")  # not H. Seo's title
    r = client.post(f"/galleries/{other}/posts", headers=author, json={"title": "hi", "body": "b"})
    assert r.json()["author"]["verified_owner"] is False


def test_most_discussed_in_overview(client):
    gid = _gallery(client)
    _guest_post(client, gid)
    md = client.get("/market/overview").json()["most_discussed"]
    assert md[0]["comic_id"] == "webtoon_global:1" and md[0]["fan_activity_24h"] == 1
