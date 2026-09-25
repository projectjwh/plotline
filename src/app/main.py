"""App factory. Run with:  uvicorn --factory src.app.main:create_app --reload"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.app.admin.router import router as admin_router
from src.app.community.router import router as community_router
from src.app.context import AppContext
from src.app.core.config import Settings
from src.app.core.errors import AppError
from src.app.core.http import BodyLimitMiddleware, request_id, RequestIdMiddleware, WriteRateLimitMiddleware, configure_logging
from src.app.fan.router import router as fan_router
from src.app.feed.router import router as feed_router
from src.app.identity.router import router as identity_router
from src.app.market.router import router as market_router
from src.app.media.router import router as media_router
from src.app.premium.router import router as premium_router
from src.app.verification.router import router as verification_router

log = logging.getLogger("plotline.app")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    configure_logging(json_logs=settings.env == "prod")
    app = FastAPI(title="Plotline", version="2.0",
                  description="Story-IP market + community. Fans free; verified authors, publishers and IP investors premium.")
    app.state.ctx = AppContext(settings)
    # added last = runs first: request id → body cap → rate limit → CORS → routes
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=False,
                       allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
                       allow_headers=["Authorization", "Content-Type", "X-Request-ID"], expose_headers=["X-Request-ID"])
    if settings.rate_limits:
        app.add_middleware(WriteRateLimitMiddleware, limits=app.state.ctx.policy.app("http", "rate_limits", default={}),
                           trust_proxy=settings.trust_proxy, ip_header=settings.client_ip_header)
    vcfg = app.state.ctx.policy.app("verification", default={})
    claims_mb = vcfg.get("max_file_mb", 10) * vcfg.get("max_files", 5) + 1   # every document at its limit + form fields
    app.add_middleware(BodyLimitMiddleware, max_bytes=settings.max_body_mb * 1024 * 1024,
                       by_prefix={"/claims": max(claims_mb, settings.max_body_mb) * 1024 * 1024})
    app.add_middleware(RequestIdMiddleware)

    @app.exception_handler(AppError)
    async def _app_error(_: Request, e: AppError):
        return JSONResponse(status_code=e.status, content={"error": e.code, "message": e.message})

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, e: Exception):
        log.exception("unhandled error")
        return JSONResponse(status_code=500, content={"error": "internal", "message": "unexpected error",
                                                      "request_id": request_id.get()})

    @app.get("/health", include_in_schema=False)
    def health():
        return {"status": "ok"}

    @app.get("/ready", include_in_schema=False)
    def ready():
        checks = app.state.ctx.readiness()
        return JSONResponse(status_code=200 if all(checks.values()) else 503,
                            content={"status": "ready" if all(checks.values()) else "not_ready", **checks})

    # fan/community routes carry sub-resources, so mount them before the /titles/{id:path} catch-all
    for r in (identity_router, fan_router, feed_router, community_router, media_router, verification_router, premium_router,
              admin_router, market_router):
        app.include_router(r)
    return app
