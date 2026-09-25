from tests.app.conftest import register


def _board(client, cid):
    return client.get(f"/fanboards/by/title/{cid}").json()["id"]


def _follow(client, h, t, ref):
    assert client.post("/follows", headers=h, json={"target_type": t, "ref": ref}).status_code == 204


def test_feed_needs_sign_in(client):
    assert client.get("/feed").status_code == 401


def test_feed_merges_sources_newest_first(client):
    _, h = register(client, "fan1")
    _, poster = register(client, "poster")
    for t, ref in (("title", "tapas_io:3"), ("title", "webtoon_global:2"), ("author", "c. vale")):
        _follow(client, h, t, ref)
    b3, b6 = _board(client, "tapas_io:3"), _board(client, "webtoon_global:6")
    client.post(f"/fanboards/{b3}/posts", headers=poster, json={"title": "Ep 41 thoughts", "body": "wow"})
    client.post(f"/fanboards/{b6}/posts", headers=poster, json={"title": "unfollowed board", "body": "x"})

    r = client.get("/feed", headers=h)
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    kinds = [i["kind"] for i in items]
    # the post is from today; market events are dated by the crawl (2026-09-24 last date, episode 2026-09-23)
    assert kinds[0] == "post" and items[0]["post"]["title"] == "Ep 41 thoughts"
    assert set(kinds) == {"post", "rank_move", "new_title", "episode"}
    assert [i["at"] for i in items] == sorted((i["at"] for i in items), reverse=True)

    moves = {i["title"]["comic_id"]: i["title"]["rank_change"] for i in items if i["kind"] == "rank_move"}
    assert moves == {"tapas_io:3": 2, "webtoon_global:2": -1}
    new = [i for i in items if i["kind"] == "new_title"]
    assert [n["title"]["comic_id"] for n in new] == ["royalroad:12"] and new[0]["via"] == [{"type": "author", "ref": "C. Vale"}]
    eps = [i for i in items if i["kind"] == "episode"]
    assert [(e["title"]["comic_id"], e["episode_no"]) for e in eps] == [("tapas_io:3", 41)]   # old and bad dates skipped
    assert "unfollowed board" not in {i["post"]["title"] for i in items if i["kind"] == "post"}


def test_feed_title_payloads_are_projected_for_fans(client):
    _, h = register(client, "fan1")
    _follow(client, h, "title", "tapas_io:3")
    items = client.get("/feed", headers=h, params={"kinds": "rank_moves"}).json()["items"]
    t = items[0]["title"]
    assert "rank_change" in t and "est_usd" not in t and "readiness" not in t


def test_feed_paging_and_filters(client):
    _, h = register(client, "fan1")
    _, poster = register(client, "poster")
    _follow(client, h, "title", "tapas_io:3")
    b3 = _board(client, "tapas_io:3")
    for n in range(4):  # posts_per_minute is 3, so a second author writes the 4th
        client.post(f"/fanboards/{b3}/posts", headers=poster, json={"title": f"p{n}", "body": "x"})
        if n == 2:
            _, poster = register(client, "poster2")
    client.post(f"/fanboards/{b3}/posts", headers=poster, json={"title": "안녕", "body": "ko", "lang": "ko"})

    seen, cursor = [], None
    while True:
        page = client.get("/feed", headers=h, params={"limit": 2, **({"cursor": cursor} if cursor else {})}).json()
        seen += [i["id"] for i in page["items"]]
        cursor = page["next_cursor"]
        if not cursor:
            break
    full = [i["id"] for i in client.get("/feed", headers=h, params={"limit": 50}).json()["items"]]
    assert seen == full and len(set(seen)) == len(seen) == 7      # 5 posts + 1 rank move + 1 episode

    ko = client.get("/feed", headers=h, params={"lang": "ko", "kinds": "posts"}).json()["items"]
    assert [i["post"]["title"] for i in ko] == ["안녕"]
    assert client.get("/feed", headers=h, params={"cursor": "%%%"}).status_code == 422


def test_feed_drops_deleted_posts_and_unfollows(client):
    _, h = register(client, "fan1")
    _, poster = register(client, "poster")
    _follow(client, h, "title", "tapas_io:3")
    pid = client.post(f"/fanboards/{_board(client, 'tapas_io:3')}/posts", headers=poster,
                      json={"title": "gone soon", "body": "x"}).json()["id"]
    assert client.post(f"/posts/{pid}/delete", headers=poster, json={}).status_code == 204
    assert not [i for i in client.get("/feed", headers=h).json()["items"] if i["kind"] == "post"]
    client.post("/follows/remove", headers=h, json={"target_type": "title", "ref": "tapas_io:3"})
    assert client.get("/feed", headers=h).json()["items"] == []
