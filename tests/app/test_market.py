from datetime import date

import polars as pl

from src.app.market import indices as ix
from src.app.market import readiness as rd


def _daily(rows):
    return pl.DataFrame(rows, schema=["comic_id", "date", "views", "rank"], orient="row")


def test_chain_index_uses_only_common_constituents():
    d1, d2, d3 = date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3)
    df = _daily([("A", d1, 100, 1), ("A", d2, 110, 1),
                 ("B", d1, 100, 2), ("B", d2, 90, 2), ("B", d3, 99, 2),
                 ("C", d2, 50, 3), ("C", d3, 60, 3)])
    s = ix.chain_index(df, base=1000)
    assert [p["value"] for p in s] == [1000.0, 1000.0, round(1000 * 159 / 140, 2)]
    assert [p["constituents"] for p in s] == [2, 3, 2]
    summ = ix.index_summary(s)
    assert summ["change_pct"] == round((1135.71 - 1000) / 1000 * 100, 3)


def test_latest_snapshot_wins_per_day():
    from datetime import datetime
    df = pl.DataFrame({"comic_id": ["A", "A"], "date": [date(2026, 1, 1)] * 2,
                       "scraped_at": [datetime(2026, 1, 1, 20), datetime(2026, 1, 1, 8)],
                       "views": [200, 100], "rank": [1, 2]})
    out = ix.latest_per_day(df)
    assert out.height == 1 and out["views"][0] == 200 and out["rank"][0] == 1


def test_readiness_matches_js_formula():
    c = rd.components(reach_pct=0.5, like_through_pct=4, momentum=25, status="completed", units=None,
                      genre="Fantasy", priors={"Fantasy": 0.92}, default_prior=0.6)
    # 100*(.3*.5 + .15*.5 + .12*.5 + .18*1 + .10*.4 + .15*.92) = 64.3 → 64
    assert rd.score(c) == 64


def test_overview_indices_breadth_listings(client):
    o = client.get("/market/overview").json()
    codes = {i["code"] for i in o["indices"]}
    assert {"PLT-ALL", "PLT-CMX", "PLT-NOV", "FANTASY", "ROMANCE", "ACTION"} <= codes
    assert o["breadth"] == {"advancing": 1, "declining": 1, "unchanged": 9, "untracked": 1, "rising": 0}
    assert [x["comic_id"] for x in o["listings"]] == ["royalroad:12"]
    assert o["listings"][0]["listed_days_ago"] == 0
    g = o["gainers"]
    assert g and all("views_change_pct" in x for x in g)
    assert [x["views_change_pct"] for x in g] == sorted([x["views_change_pct"] for x in g], reverse=True)


def test_rank_movers(client):
    up = client.get("/market/movers", params={"kind": "rank_up"}).json()
    down = client.get("/market/movers", params={"kind": "rank_down"}).json()
    assert [x["comic_id"] for x in up] == ["tapas_io:3"] and up[0]["rank_change"] == 2
    assert [x["comic_id"] for x in down] == ["webtoon_global:2"]
    assert client.get("/market/movers", params={"kind": "sideways"}).status_code == 422


def test_index_detail_and_404(client):
    i = client.get("/market/indices/fantasy").json()
    assert i["constituents"] == 5 and len(i["series"]) == 5 and i["series"][0]["value"] == 1000.0
    assert client.get("/market/indices/NOPE").status_code == 404


def test_treemap_genres_publishers(client):
    tm = client.get("/market/treemap").json()
    assert {g["group"] for g in tm} == {"Fantasy", "Romance", "Action"}
    assert all("est_usd" not in t for g in tm for t in g["titles"])
    genres = {g["name"]: g for g in client.get("/genres").json()}
    assert genres["Fantasy"]["titles"] == 5 and genres["Fantasy"]["index"]["code"] == "FANTASY"
    pubs = {p["name"] for p in client.get("/publishers").json()}
    assert pubs == {"Studio Nara", "Moonbeam"}


def test_search_filters_credits(client):
    assert [x["comic_id"] for x in client.get("/search", params={"q": "ash"}).json()] == ["webtoon_global:1"]
    novels = client.get("/titles", params={"content_type": "novel"}).json()
    assert novels["total"] == 4
    cr = client.get("/credits/author/H. Seo").json()
    assert {w["comic_id"] for w in cr["works"]} == {"webtoon_global:1", "royalroad:4"}
    assert client.get("/titles/nope:0").status_code == 404


def test_missing_warehouse_is_503(tmp_path, settings):
    from fastapi.testclient import TestClient
    from src.app.main import create_app
    settings.warehouse_path = str(tmp_path / "missing.duckdb")
    c = TestClient(create_app(settings))
    r = c.get("/market/overview")
    assert r.status_code == 503 and r.json()["error"] == "unavailable"
