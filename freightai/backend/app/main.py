import logging

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.base import BaseHTTPMiddleware

from app.api import ai, analytics, auth, carriers, deals, intake, loads, pricing
from app.core.config import settings
from app.core.database import Base, engine, get_db
from app.core.logging_config import Timer, configure_logging, new_request_id, request_id_var

# Both model modules must be imported before create_all() so their tables
# are registered on Base.metadata -- easy to forget when a schema is split
# across files.
from app.models import models, pricing_schema, leads  # noqa: F401

configure_logging(level="DEBUG" if settings.environment == "development" else "INFO")
logger = logging.getLogger("freightai")

app = FastAPI(
    title="FreightAI Saudi",
    description="نظام تشغيل أعمال لوساطة النقل البري - MVP Phase 1. "
                 "هذا النظام أداة لتنظيم ومطابقة طلبات النقل ولا يغني عن التراخيص أو المتطلبات النظامية ذات الصلة.",
    version="0.3.0",
)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """
    Assigns each request a short id (visible in every log line via
    logging_config's ContextVar) and logs method/path/status/duration.
    Doesn't touch the response body, so it's safe alongside streaming
    responses.
    """
    async def dispatch(self, request: Request, call_next):
        rid = new_request_id()
        token = request_id_var.set(rid)
        try:
            with Timer() as t:
                response = await call_next(request)
            logger.info(
                f"{request.method} {request.url.path} -> {response.status_code} ({t.elapsed_ms}ms)"
            )
            response.headers["X-Request-Id"] = rid
            return response
        finally:
            request_id_var.reset(token)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Baseline HTTP security headers. This is a JSON API consumed by a bot
    process today, not a browser -- but it's designed to grow an admin
    dashboard (see README Roadmap), and these cost nothing to have in
    place before that day arrives rather than being retrofitted under
    time pressure later:
      - X-Content-Type-Options: stops a browser from MIME-sniffing a
        response into something more dangerous than the declared
        Content-Type (relevant the moment any endpoint ever serves
        user-influenced content).
      - X-Frame-Options: blocks this API's responses from being framed by
        another site (clickjacking defense) -- irrelevant for JSON today,
        free insurance for tomorrow.
      - Referrer-Policy: don't leak full request URLs (which may contain
        query params) to third parties via the Referer header.
      - Permissions-Policy: explicitly disables browser features this API
        never needs.
    This does NOT set Strict-Transport-Security -- that's the deploying
    platform's responsibility (see README "Security": TLS termination is
    explicitly out of this codebase's scope) and setting it here would
    incorrectly imply this code controls something it doesn't.
    """
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()"
        return response


app.add_middleware(RequestContextMiddleware)
app.add_middleware(SecurityHeadersMiddleware)


# --- Global exception handlers -------------------------------------------
# Previously an unhandled SQLAlchemyError (e.g. a bad connection, a
# constraint violation not caught locally) would surface FastAPI's default
# 500 page, which in debug mode includes a full stack trace -- fine for
# local dev, a real information leak in production. These handlers make
# every unexpected error path log the trace server-side but return a
# generic, request-id-tagged message to the client.

@app.exception_handler(SQLAlchemyError)
async def sqlalchemy_exception_handler(request: Request, exc: SQLAlchemyError):
    rid = request_id_var.get()
    logger.exception(f"Unhandled database error [{rid}]")
    return JSONResponse(
        status_code=500,
        content={"detail": "حدث خطأ في قاعدة البيانات. حاول لاحقًا.", "request_id": rid},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    rid = request_id_var.get()
    logger.exception(f"Unhandled error [{rid}]")
    return JSONResponse(
        status_code=500,
        content={"detail": "حدث خطأ غير متوقع. حاول لاحقًا.", "request_id": rid},
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    # Pass-through, but attach the request id for support/debugging.
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "request_id": request_id_var.get()},
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors(), "request_id": request_id_var.get()},
    )


app.include_router(auth.router)
app.include_router(loads.router)
app.include_router(carriers.router)
app.include_router(deals.router)
app.include_router(analytics.router)
app.include_router(ai.router)
app.include_router(pricing.router)
app.include_router(intake.router)


@app.on_event("startup")
async def on_startup():
    # create_all() is a dev convenience only: it has no migration history,
    # can't alter existing tables, and silently diverges from what Alembic
    # thinks the schema is. Restricting it to `development` forces staging
    # and production through `alembic upgrade head` (see backend/alembic/),
    # which is the only way schema changes are tracked and reversible.
    if settings.environment == "development":
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Startup: create_all() ran (development mode)")
    else:
        logger.info("Startup: skipping create_all() -- run alembic upgrade head instead")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/health/db")
async def health_db(db: AsyncSession = Depends(get_db)):
    """
    Unlike /health (process-alive check, touches nothing), this runs a
    trivial real query against Postgres. Its purpose is specifically to
    generate genuine database activity -- Supabase's free tier pauses a
    project after 7 days with no database activity, and an app-level
    health check that never touches the DB wouldn't prevent that. See
    bot/keepalive.py, which calls this on a schedule well under 7 days.
    """
    result = await db.execute(text("SELECT 1"))
    result.scalar_one()
    return {"status": "ok", "db": "reachable"}
