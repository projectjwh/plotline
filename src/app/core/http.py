"""HTTP plumbing: client IP, request IDs with JSON access logs, a body-size cap and write rate limits.

All three middlewares are plain ASGI so they also cover streamed uploads.
"""
from __future__ import annotations

import contextvars
import json
import logging
import re
import time
import uuid

from limits import parse
from limits.storage import MemoryStorage
from limits.strategies import MovingWindowRateLimiter

request_id: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")
_RID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def client_ip(headers: dict[str, str], peer: str, *, trust_proxy: bool, ip_header: str | None) -> str:
    """The caller's IP.

    Behind a proxy, ``X-Forwarded-For`` is "<whatever the client sent>, ..., <what our proxy saw>",
    so only the rightmost entry is trustworthy (one proxy hop). A proxy that sets a dedicated
    header can be named with ``PLOTLINE_CLIENT_IP_HEADER`` instead.
    """
    if trust_proxy:
        if ip_header and headers.get(ip_header.lower()):
            return headers[ip_header.lower()].strip()
        fwd = headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[-1].strip()
    return peer


def _headers(scope) -> dict[str, str]:
    return {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}


class JsonFormatter(logging.Formatter):
    def format(self, r: logging.LogRecord) -> str:
        out = {"ts": self.formatTime(r, "%Y-%m-%dT%H:%M:%S"), "level": r.levelname, "logger": r.name,
               "msg": r.getMessage(), "request_id": request_id.get()}
        out.update(getattr(r, "fields", {}))
        if r.exc_info:
            out["exc"] = self.formatException(r.exc_info)
        return json.dumps(out, ensure_ascii=False)


class _PlainFormatter(logging.Formatter):
    def format(self, r: logging.LogRecord) -> str:
        fields = getattr(r, "fields", None)
        return super().format(r) + ("" if not fields else " " + " ".join(f"{k}={v}" for k, v in fields.items()))


def configure_logging(json_logs: bool) -> None:
    root = logging.getLogger("plotline")
    if getattr(root, "_plotline_configured", False):
        return
    h = logging.StreamHandler()
    h.setFormatter(JsonFormatter() if json_logs else _PlainFormatter("%(levelname)s %(name)s %(message)s"))
    root.addHandler(h)
    root.setLevel(logging.INFO)
    root.propagate = False
    root._plotline_configured = True


class RequestIdMiddleware:
    """Echo or assign ``X-Request-ID`` and write one access-log line per request."""

    def __init__(self, app):
        self.app = app
        self.log = logging.getLogger("plotline.access")

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        given = _headers(scope).get("x-request-id", "")
        rid = given if _RID.match(given) else uuid.uuid4().hex
        token = request_id.set(rid)
        start, status = time.perf_counter(), [500]

        async def _send(msg):
            if msg["type"] == "http.response.start":
                status[0] = msg["status"]
                msg["headers"] = list(msg.get("headers", [])) + [(b"x-request-id", rid.encode())]
            await send(msg)
        try:
            await self.app(scope, receive, _send)
        finally:
            # the path only: query strings can carry tokens
            self.log.info("request", extra={"fields": {"method": scope["method"], "path": scope["path"],
                                                       "status": status[0],
                                                       "ms": round((time.perf_counter() - start) * 1000, 1)}})
            request_id.reset(token)


async def _reply(send, status: int, code: str, message: str):
    body = json.dumps({"error": code, "message": message}).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})


class _TooLarge(Exception):
    pass


class BodyLimitMiddleware:
    """Refuse bodies over the cap by Content-Length, and cut off streamed bodies that exceed it.

    ``by_prefix`` raises the cap for specific paths (claim documents are larger than posts).
    """

    def __init__(self, app, max_bytes: int, by_prefix: dict[str, int] | None = None):
        self.app, self.default = app, max_bytes
        self.by_prefix = sorted((by_prefix or {}).items(), key=lambda x: -len(x[0]))

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        limit = next((m for p, m in self.by_prefix if scope["path"].startswith(p)), self.default)
        await self._limited(scope, receive, send, limit)

    async def _limited(self, scope, receive, send, limit: int):
        cl = _headers(scope).get("content-length")
        if cl and cl.isdigit() and int(cl) > limit:
            return await _reply(send, 413, "too_large", f"request body over {limit // (1024 * 1024)} MB")
        seen, started, cut = [0], [False], [False]

        async def _receive():
            msg = await receive()
            if msg["type"] == "http.request":
                seen[0] += len(msg.get("body", b""))
                if seen[0] > limit and not cut[0]:
                    cut[0] = True
                    if not started[0]:   # answer now: FastAPI would turn the exception below into a 400
                        started[0] = True
                        await _reply(send, 413, "too_large", f"request body over {limit // (1024 * 1024)} MB")
                    raise _TooLarge
            return msg

        async def _send(msg):
            if cut[0]:
                return               # the 413 has been sent; drop the app's own error response
            if msg["type"] == "http.response.start":
                started[0] = True
            await send(msg)
        try:
            await self.app(scope, _receive, _send)
        except _TooLarge:
            pass


class WriteRateLimitMiddleware:
    """Per-IP limits on writes (POST/PUT/PATCH/DELETE), set in ``app.yaml`` under ``http.rate_limits``.

    Counters are in memory, so they are per machine and reset on restart. The DB-backed
    limits (login throttle, posts per minute, images per hour) are the durable ones.
    """

    def __init__(self, app, limits: dict[str, str], *, trust_proxy: bool, ip_header: str | None):
        self.app = app
        self.default = parse(limits.get("write", "60/minute"))
        # longest prefix first, so "/auth/login" wins over "/auth/"
        self.by_prefix = sorted(((p, parse(v)) for p, v in limits.items() if p.startswith("/")), key=lambda x: -len(x[0]))
        self.limiter = MovingWindowRateLimiter(MemoryStorage())
        self.trust_proxy, self.ip_header = trust_proxy, ip_header

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in WRITE_METHODS:
            return await self.app(scope, receive, send)
        peer = scope["client"][0] if scope.get("client") else ""
        ip = client_ip(_headers(scope), peer, trust_proxy=self.trust_proxy, ip_header=self.ip_header)
        prefix, item = next(((p, i) for p, i in self.by_prefix if scope["path"].startswith(p)), ("*", self.default))
        if not self.limiter.hit(item, ip, prefix):
            return await _reply(send, 429, "rate_limited", "too many requests; slow down")
        await self.app(scope, receive, send)
