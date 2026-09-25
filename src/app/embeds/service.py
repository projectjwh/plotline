"""Link previews for fanboard posts (decision D-036).

The server fetches OpenGraph tags for links in a post. Because the server makes the
request, every fetch is guarded against server-side request forgery (SSRF):

* http/https only, default ports only, no credentials in the URL
* every hostname must resolve to public (globally routable) addresses only
* redirects are followed manually (at most 3) and every hop is re-checked
* 3 s timeout, 512 KB cap, text/html only

Residual risk: DNS can change between the check and the connect (DNS rebinding).
Production can close that by fetching through an egress proxy that allows only
public ranges; noted in docs/product/decisions.md (D-036).

The domain deny list (``community.embed_deny_domains``) suppresses previews for
listed sites. It is a switch the operator edits; there is no automated filtering.
"""
from __future__ import annotations

import html
import ipaddress
import re
import socket
import urllib.error
import urllib.request
from typing import Callable, Protocol
from urllib.parse import urljoin, urlsplit

from sqlalchemy import Column, DateTime, String, Table, Text, insert, select
from sqlalchemy.engine import Engine

from src.app.core.db import metadata, now
from src.app.core.registry import Registry

embeds = Table(
    "embeds", metadata,
    Column("url", String(2048), primary_key=True),
    Column("status", String(12), nullable=False),     # ok | blocked | failed | denied
    Column("title", String(300)),
    Column("description", Text),
    Column("image", String(2048)),
    Column("site", String(120)),
    Column("fetched_at", DateTime, nullable=False),
)

URL_RE = re.compile(r"https?://[^\s<>\"')\]]+", re.I)
MAX_BYTES = 512 * 1024
fetchers = Registry("embed fetcher")


class Blocked(Exception):
    """The URL (or a redirect hop) is not allowed to be fetched."""


def extract_urls(text: str, limit: int = 3) -> list[str]:
    return list(dict.fromkeys(m.group(0).rstrip(".,;:!?") for m in URL_RE.finditer(text or "")))[:limit]


def check_url(url: str, resolve: Callable[[str], list[str]]) -> None:
    p = urlsplit(url)
    if p.scheme not in ("http", "https"):
        raise Blocked("scheme")
    if p.username or p.password:
        raise Blocked("credentials in URL")
    if p.port not in (None, 80, 443):
        raise Blocked("port")
    host = p.hostname or ""
    if not host:
        raise Blocked("no host")
    addrs = resolve(host)
    if not addrs:
        raise Blocked("unresolvable")
    for a in addrs:
        ip = ipaddress.ip_address(a.split("%")[0])
        if not ip.is_global or ip.is_multicast:
            raise Blocked(f"non-public address {ip}")


def dns_resolve(host: str) -> list[str]:
    try:
        return sorted({ai[4][0] for ai in socket.getaddrinfo(host, None)})
    except socket.gaierror:
        return []


class Fetcher(Protocol):
    def get(self, url: str) -> tuple[int, dict, bytes]:
        """One request without following redirects: (status, lowercase headers, body ≤ MAX_BYTES+1)."""
        ...


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


@fetchers.register("urllib")
class UrllibFetcher:
    def __init__(self, timeout: float = 3.0, **_):
        self.timeout = timeout
        self.opener = urllib.request.build_opener(_NoRedirect)

    def get(self, url: str) -> tuple[int, dict, bytes]:
        req = urllib.request.Request(url, headers={"User-Agent": "PlotlineLinkPreview/1.0",
                                                   "Accept": "text/html"})
        try:
            r = self.opener.open(req, timeout=self.timeout)  # noqa: S310 — URL checked by check_url first
        except urllib.error.HTTPError as e:
            return e.code, {k.lower(): v for k, v in e.headers.items()}, b""
        with r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read(MAX_BYTES + 1)


def safe_fetch(url: str, fetcher: Fetcher, resolve: Callable[[str], list[str]], max_hops: int = 3) -> tuple[str, bytes]:
    for _ in range(max_hops + 1):
        check_url(url, resolve)
        status, headers, body = fetcher.get(url)
        if status in (301, 302, 303, 307, 308) and headers.get("location"):
            url = urljoin(url, headers["location"])
            continue
        if status != 200:
            raise Blocked(f"status {status}")
        if "text/html" not in headers.get("content-type", ""):
            raise Blocked("not html")
        if len(body) > MAX_BYTES:
            raise Blocked("too large")
        return url, body
    raise Blocked("too many redirects")


def _meta(doc: str, prop: str) -> str | None:
    for pat in (rf'<meta[^>]+(?:property|name)=["\']{prop}["\'][^>]*content=["\']([^"\']*)["\']',
                rf'<meta[^>]+content=["\']([^"\']*)["\'][^>]*(?:property|name)=["\']{prop}["\']'):
        m = re.search(pat, doc, re.I)
        if m:
            return html.unescape(m.group(1)).strip()
    return None


def parse_preview(url: str, body: bytes) -> dict:
    doc = body.decode("utf-8", "replace")
    title = _meta(doc, "og:title") or (lambda m: html.unescape(m.group(1)).strip() if m else None)(
        re.search(r"<title[^>]*>(.*?)</title>", doc, re.I | re.S))
    image = _meta(doc, "og:image")
    if image:
        image = urljoin(url, image)
        if urlsplit(image).scheme not in ("http", "https"):
            image = None
    return {"title": (title or "")[:300] or None, "description": (_meta(doc, "og:description") or "")[:500] or None,
            "image": image, "site": (_meta(doc, "og:site_name") or urlsplit(url).hostname or "")[:120]}


class EmbedService:
    def __init__(self, engine: Engine, fetcher: Fetcher, cfg: dict, resolve: Callable[[str], list[str]] = dns_resolve):
        self.e, self.fetcher, self.cfg, self.resolve = engine, fetcher, cfg, resolve

    def _denied(self, url: str) -> bool:
        host = (urlsplit(url).hostname or "").lower()
        return any(host == d or host.endswith("." + d) for d in (x.lower() for x in self.cfg.get("embed_deny_domains", [])))

    def cached(self, urls: list[str]) -> list[dict]:
        if not urls:
            return []
        with self.e.connect() as c:
            rows = {r["url"]: dict(r) for r in c.execute(select(embeds).where(embeds.c.url.in_(urls))).mappings()}
        out = []
        for u in urls:
            r = rows.get(u)
            if r and r["status"] == "ok":
                out.append({"url": u, "title": r["title"], "description": r["description"], "image": r["image"], "site": r["site"]})
            else:
                out.append({"url": u, "title": None, "description": None, "image": None, "site": urlsplit(u).hostname})
        return out

    def refresh(self, urls: list[str]) -> None:
        """Fetch previews for urls not cached yet. Runs after the response (background task)."""
        with self.e.connect() as c:
            have = {r[0] for r in c.execute(select(embeds.c.url).where(embeds.c.url.in_(urls)))} if urls else set()
        for u in urls:
            if u in have:
                continue
            row = {"url": u, "fetched_at": now(), "title": None, "description": None, "image": None, "site": None}
            if self._denied(u):
                row["status"] = "denied"
            else:
                try:
                    final, body = safe_fetch(u, self.fetcher, self.resolve)
                    row.update(parse_preview(final, body), status="ok")
                except Blocked:
                    row["status"] = "blocked"
                except Exception:  # network errors: record, never break posting
                    row["status"] = "failed"
            with self.e.begin() as c:
                if not c.execute(select(embeds.c.url).where(embeds.c.url == u)).first():
                    c.execute(insert(embeds).values(**row))
