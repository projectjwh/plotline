"""Rate limiting — slowapi when available, a transparent no-op when not.

Keeps the API import-safe in minimal environments (local dev without slowapi
installed) while enforcing per-IP limits in production. Wire-up in ``main.py``:

    from src.api.ratelimit import limiter, install
    install(app)                     # registers the handler + middleware (if enabled)
    @app.get(...); @limiter.limit(cfg.RATE_LIMIT)
"""
from __future__ import annotations

import logging

log = logging.getLogger("plotline.api")

try:
    from slowapi import Limiter
    from slowapi.errors import RateLimitExceeded
    from slowapi.util import get_remote_address
    _ENABLED = True
except ImportError:  # pragma: no cover - minimal env
    _ENABLED = False


if _ENABLED:
    from src.api.config import cfg
    # default_limits are enforced globally by SlowAPIMiddleware — no per-route
    # decorators (and no `request` param plumbing) needed.
    limiter = Limiter(key_func=get_remote_address, default_limits=[cfg.RATE_LIMIT])

    def install(app) -> None:
        from slowapi import _rate_limit_exceeded_handler
        from slowapi.middleware import SlowAPIMiddleware
        app.state.limiter = limiter
        app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
        app.add_middleware(SlowAPIMiddleware)
        log.info("rate limiting: enabled")
else:
    class _NoopLimiter:
        """Mimic slowapi's decorator API but do nothing (dependency absent)."""
        def limit(self, *_a, **_k):
            def deco(fn):
                return fn
            return deco

    limiter = _NoopLimiter()

    def install(app) -> None:  # noqa: ARG001
        log.warning("rate limiting: disabled (slowapi not installed)")
