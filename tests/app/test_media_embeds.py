import io

import pytest
from PIL import Image

from src.app.embeds.service import Blocked, check_url, extract_urls, parse_preview, safe_fetch
from tests.app.conftest import register


def jpeg_with_gps() -> bytes:
    img = Image.new("RGB", (3000, 1500), (200, 30, 30))
    exif = Image.Exif()
    exif[0x010F] = "SecretCam"            # Make
    exif[0x8825] = {2: (37.0, 33.0, 1.0)}  # GPSInfo → latitude
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif.tobytes())
    return buf.getvalue()


def _board(client):
    return client.get("/fanboards/by/title/webtoon_global:1").json()["id"]


def test_image_upload_strips_metadata_and_resizes(client):
    _, h = register(client, "artist")
    raw = jpeg_with_gps()
    assert b"SecretCam" in raw
    r = client.post("/media", headers=h, files={"file": ("a.jpg", raw, "image/jpeg")})
    assert r.status_code == 201, r.text
    m = r.json()
    assert (m["width"], m["height"]) == (2048, 1024) and m["mime"] == "image/jpeg"
    served = client.get(m["url"])
    assert served.status_code == 200 and served.headers["content-type"] == "image/jpeg"
    assert b"SecretCam" not in served.content and not Image.open(io.BytesIO(served.content)).getexif()


def test_image_rules(client):
    raw = jpeg_with_gps()
    r = client.post("/media", files={"file": ("a.jpg", raw, "image/jpeg")})           # guest
    assert r.status_code == 403 and r.json()["error"] == "guest_images_off"
    _, h = register(client, "artist")
    assert client.post("/media", headers=h, files={"file": ("x.jpg", b"MZ not an image", "image/jpeg")}).status_code == 422
    big = b"\xff\xd8\xff" + b"0" * (5 * 1024 * 1024 + 10)
    assert client.post("/media", headers=h, files={"file": ("b.jpg", big, "image/jpeg")}).status_code == 422


def test_attach_images_to_post_and_moderator_removal(client, admin):
    _, ah = admin
    _, h = register(client, "artist")
    _, other = register(client, "other")
    mid = client.post("/media", headers=h, files={"file": ("a.jpg", jpeg_with_gps(), "image/jpeg")}).json()["id"]
    gid = _board(client)
    r = client.post(f"/fanboards/{gid}/posts", headers=other, json={"title": "t", "body": "b", "media_ids": [mid]})
    assert r.status_code == 403                                                        # not your image
    p = client.post(f"/fanboards/{gid}/posts", headers=h, json={"title": "Fanart", "body": "b", "media_ids": [mid]}).json()
    assert [m["id"] for m in client.get(f"/posts/{p['id']}").json()["media"]] == [mid]
    assert client.post(f"/admin/media/{mid}/remove", headers=ah).status_code == 204
    assert client.get(f"/media/{mid}").status_code == 404


def test_post_lang_filter(client):
    _, h = register(client, "reader1")
    gid = _board(client)
    client.post(f"/fanboards/{gid}/posts", headers=h, json={"title": "hello", "body": "en post"})
    client.post(f"/fanboards/{gid}/posts", headers=h, json={"title": "안녕", "body": "ko post", "lang": "ko"})
    ko = client.get(f"/fanboards/{gid}/posts", params={"lang": "ko"}).json()["items"]
    assert [p["title"] for p in ko] == ["안녕"] and ko[0]["lang"] == "ko"
    assert client.post(f"/fanboards/{gid}/posts", headers=h, json={"title": "x", "body": "y", "lang": "fr"}).status_code == 422


# ---------- SSRF guards ----------
PUBLIC = {"example.com": ["93.184.216.34"], "evil.test": ["127.0.0.1"], "meta.test": ["169.254.169.254"],
          "lan.test": ["10.0.0.5"], "mixed.test": ["93.184.216.34", "192.168.1.1"], "v6.test": ["::1"]}


def resolve(host):
    return PUBLIC.get(host, [])


@pytest.mark.parametrize("url", [
    "http://evil.test/", "http://meta.test/latest/meta-data", "http://lan.test/", "http://mixed.test/",
    "http://v6.test/", "http://127.0.0.1/", "ftp://example.com/", "http://user:pw@example.com/",
    "http://example.com:8080/", "http://unknown.test/"])
def test_check_url_blocks(url):
    with pytest.raises(Blocked):
        check_url(url, resolve)


def test_check_url_allows_public():
    check_url("https://example.com/story", resolve)


class StubFetcher:
    def __init__(self, responses):
        self.responses, self.calls = responses, []

    def get(self, url):
        self.calls.append(url)
        return self.responses[url]


def test_redirect_to_private_address_is_blocked():
    f = StubFetcher({"https://example.com/a": (302, {"location": "http://meta.test/secret"}, b"")})
    with pytest.raises(Blocked):
        safe_fetch("https://example.com/a", f, resolve)
    assert f.calls == ["https://example.com/a"]            # the private hop was never requested


def test_oversize_and_non_html_are_blocked():
    big = StubFetcher({"https://example.com/": (200, {"content-type": "text/html"}, b"x" * (512 * 1024 + 1))})
    with pytest.raises(Blocked):
        safe_fetch("https://example.com/", big, resolve)
    pdf = StubFetcher({"https://example.com/": (200, {"content-type": "application/pdf"}, b"%PDF")})
    with pytest.raises(Blocked):
        safe_fetch("https://example.com/", pdf, resolve)


def test_parse_preview_and_extract():
    html = b'<html><head><title>T</title><meta property="og:title" content="Tower &amp; Ash">' \
           b'<meta property="og:image" content="/c.jpg"><meta property="og:image:alt" content="x">' \
           b'<meta name="og:description" content="Ep 142"></head></html>'
    p = parse_preview("https://example.com/s", html)
    assert p == {"title": "Tower & Ash", "description": "Ep 142", "image": "https://example.com/c.jpg", "site": "example.com"}
    assert extract_urls("see https://a.com/x, and http://b.com/y. also https://a.com/x") == ["https://a.com/x", "http://b.com/y"]


def test_post_links_get_previews_after_posting(client):
    ctx = client.app.state.ctx
    ctx.embeds.resolve = resolve
    ctx.embeds.fetcher = StubFetcher({"https://example.com/review": (
        200, {"content-type": "text/html; charset=utf-8"}, b'<meta property="og:title" content="Great review">')})
    ctx.embeds.cfg = {**ctx.embeds.cfg, "embed_deny_domains": ["pirate.test"]}
    _, h = register(client, "reader1")
    gid = _board(client)
    p = client.post(f"/fanboards/{gid}/posts", headers=h,
                    json={"title": "links", "body": "read https://example.com/review and http://evil.test/x and https://www.pirate.test/ep1"}).json()
    embeds = {e["url"]: e for e in client.get(f"/posts/{p['id']}").json()["embeds"]}
    assert embeds["https://example.com/review"]["title"] == "Great review"
    assert embeds["http://evil.test/x"]["title"] is None                     # blocked: private address
    assert embeds["https://www.pirate.test/ep1"]["title"] is None            # denied: no preview


def test_oversized_dimensions_are_refused_before_decoding():
    from src.app.core.errors import Invalid
    from src.app.media.service import reencode
    img = Image.new("1", (7000, 7000))          # 49M pixels, tiny as a 1-bit PNG, under Pillow's own 2× limit
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    assert len(buf.getvalue()) < 5 * 1024 * 1024
    with pytest.raises(Invalid):
        reencode(buf.getvalue(), 2048)
    frames = [Image.new("L", (2000, 2000), i * 4) for i in range(60)]   # 240M pixels; distinct so none merge
    buf = io.BytesIO()
    frames[0].save(buf, format="GIF", save_all=True, append_images=frames[1:])
    with pytest.raises(Invalid):
        reencode(buf.getvalue(), 2048)
