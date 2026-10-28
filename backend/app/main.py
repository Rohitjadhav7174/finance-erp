from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from .config import get_settings
from .db import close_pool
from .errors import ConflictError, conflict_handler, db_error_handler
from .limits import BodySizeLimit
from .ratelimit import limiter
from .routers import admin_backups, approvals, bills, companies, entries, imports, insights, masters, me, reconcile, users

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
access_log = logging.getLogger("finance.access")
# httpx logs full request URLs at INFO; keep it quiet so URLs/query strings never reach logs.
logging.getLogger("httpx").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    close_pool()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Finance ERP API",
        lifespan=lifespan,
        docs_url=None if settings.environment == "production" else "/api/docs",
        redoc_url=None,
        openapi_url=None if settings.environment == "production" else "/api/openapi.json",
    )
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_exception_handler(psycopg.Error, db_error_handler)
    app.add_exception_handler(ConflictError, conflict_handler)
    app.add_middleware(SlowAPIMiddleware)
    app.add_middleware(BodySizeLimit)
    # Bearer tokens in the Authorization header (no cookies), so CSRF does not apply;
    # CORS still restricts which sites may call the API from a browser.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-Id"],
        expose_headers=["Content-Disposition", "X-Request-Id"],
        max_age=600,
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("x-request-id", "")[:64] or uuid.uuid4().hex
        request.state.request_id = request_id
        if settings.environment == "production" and request.headers.get("x-forwarded-proto", "https") != "https":
            return JSONResponse(status_code=400, content={"detail": "HTTPS is required."})
        start = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-Id"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        if settings.environment == "production":
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        # Never log bodies, query strings or headers (may contain tokens / amounts).
        access_log.info("%s %s %s %.0fms user=%s req=%s", request.method, request.url.path,
                        response.status_code, (time.perf_counter() - start) * 1000,
                        getattr(request.state, "user_id", "-"), request_id)
        return response

    @app.get("/api/health", tags=["health"])
    def health():
        return {"status": "ok"}

    for r in (me.router, companies.router, users.router, masters.router, entries.router, bills.router,
              approvals.router, insights.router, imports.router, reconcile.router, admin_backups.router):
        app.include_router(r, prefix="/api")
    return app


app = create_app()
