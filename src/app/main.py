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
from src.app.fan.router import router as fan_router
from src.app.identity.router import router as identity_router
from src.app.market.router import router as market_router
from src.app.premium.router import router as premium_router
from src.app.verification.router import router as verification_router

log = logging.getLogger("plotline.app")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    app = FastAPI(title="Plotline", version="2.0",
                  description="Story-IP market + community. Fans free; verified authors, publishers and IP investors premium.")
    app.state.ctx = AppContext(settings)
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=False,
                       allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"], allow_headers=["Authorization", "Content-Type"])

    @app.exception_handler(AppError)
    async def _app_error(_: Request, e: AppError):
        return JSONResponse(status_code=e.status, content={"error": e.code, "message": e.message})

    @app.get("/health", include_in_schema=False)
    def health():
        return {"status": "ok"}

    # fan/community routes carry sub-resources, so mount them before the /titles/{id:path} catch-all
    for r in (identity_router, fan_router, community_router, verification_router, premium_router, admin_router,
              market_router):
        app.include_router(r)
    return app
