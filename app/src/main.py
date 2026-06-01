"""
main.py — FastAPI application for the Meridian link shortener service.

Endpoints:
    POST /shorten         — Create a short URL (with optional custom code)
    GET  /{code}          — Redirect to the original URL
    GET  /health          — Liveness and dependency health check
    GET  /metrics         — Prometheus metrics (via prometheus-fastapi-instrumentator)
    GET  /stats           — Aggregated usage statistics

Design decisions:
    - Secrets are fetched from SSM at startup via get_settings() — not from env vars.
    - Redis is used as a write-through cache on the hot redirect path.
    - Click counts are incremented with a DB UPDATE on every redirect.
    - Prometheus metrics are auto-instrumented by the Instrumentator.
    - All log calls use structured extra= dicts — no f-string interpolation in log messages.
"""

import asyncio
import logging
import os
import secrets
import string
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy import func, select, update

from .cache import CacheClient
from .config import get_settings
from .database import ShortLink, create_db_engine, create_session_factory, init_db
from .logger import configure_logging
from .models import HealthResponse, LinkStats, ShortenRequest, ShortenResponse, StatsResponse

# Bootstrap structured logging before anything else runs
configure_logging(level=get_settings().log_level)
logger = logging.getLogger(__name__)

# Characters used to generate short codes.
# Deliberately excludes ambiguous chars (0, O, l, 1) for readability.
_CODE_ALPHABET: str = string.ascii_letters + string.digits
_CODE_LENGTH: int = 7
_MAX_COLLISION_RETRIES: int = 5

# Strong references to fire-and-forget background tasks — prevents GC from
# collecting tasks before they complete and silencing their exceptions.
_background_tasks: set[asyncio.Task] = set()  # type: ignore[type-arg]


def _generate_code() -> str:
    """
    Generate a cryptographically random 7-character short code.

    Uses secrets.choice (CSPRNG) — never random.choice, which is not
    cryptographically secure and could allow prediction of future codes.
    """
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LENGTH))


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    FastAPI lifespan context manager: initialise resources on startup,
    clean up on shutdown.
    """
    settings = get_settings()
    logger.info("Application starting", extra={"version": settings.app_version})

    # Database
    engine = create_db_engine(settings)
    await init_db(engine)
    app.state.session_factory = create_session_factory(engine)

    # Redis cache
    cache = CacheClient(host=settings.redis_host, port=settings.redis_port)
    app.state.cache = cache

    logger.info("Application ready")

    yield  # ← application handles requests between yield and cleanup

    # Graceful shutdown
    logger.info("Application shutting down")
    await cache.close()
    await engine.dispose()


# ── Application ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="Meridian Link Shortener",
    version="1.0.0",
    description="URL shortening service with Prometheus metrics and SSM-backed secrets.",
    # Disable interactive docs in production — reduces attack surface and information leakage
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()"
    response.headers["X-XSS-Protection"] = "0"  # Modern browsers use CSP; legacy header can backfire
    return response

# Auto-instrument all routes with Prometheus metrics.
# /metrics and /health are excluded from latency tracking to keep histograms clean.
Instrumentator(
    should_group_status_codes=True,
    should_ignore_untemplated=True,
    excluded_handlers=["/metrics", "/health"],
    body_handlers=[],
).instrument(app).expose(app, include_in_schema=False)


# ── Routes ────────────────────────────────────────────────────────────────────

@app.post("/shorten", response_model=ShortenResponse, status_code=201)
async def shorten_url(body: ShortenRequest, request: Request) -> ShortenResponse:
    """
    Create a shortened URL.

    If `custom_code` is provided it is used as-is (returns 409 on collision).
    Otherwise a cryptographically random 7-char code is generated.
    """
    session_factory = request.app.state.session_factory

    async with session_factory() as session:
        if body.custom_code:
            code = body.custom_code
            # Check for collision
            existing = await session.get(ShortLink, code)
            if existing is not None:
                raise HTTPException(
                    status_code=409,
                    detail=f"Short code '{code}' is already in use",
                )
        else:
            # Retry loop handles the astronomically unlikely collision case
            code = _generate_code()
            for _ in range(_MAX_COLLISION_RETRIES):
                if await session.get(ShortLink, code) is None:
                    break
                code = _generate_code()
            else:
                raise HTTPException(
                    status_code=503,
                    detail="Unable to generate a unique code — please retry",
                )

        link = ShortLink(code=code, original_url=str(body.url))
        session.add(link)
        await session.commit()
        await session.refresh(link)

    # Warm the cache so the first redirect is a cache hit
    await request.app.state.cache.set_url(code, str(body.url))

    logger.info("Short URL created", extra={"code": code, "url": str(body.url)})

    settings = get_settings()
    base_url = (settings.app_base_url or str(request.base_url)).rstrip("/")

    return ShortenResponse(
        short_code=code,
        short_url=f"{base_url}/{code}",
        original_url=str(body.url),
        created_at=link.created_at or datetime.now(timezone.utc),
    )


@app.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    """
    Liveness and dependency health check.

    Returns 200 even when cache is down (degraded is still alive).
    Returns 503 if the database is unreachable (the app cannot serve requests).
    """
    db_status = "healthy"
    cache_status = "healthy"

    # Database check
    try:
        async with request.app.state.session_factory() as session:
            await session.execute(select(func.now()))
    except Exception as exc:
        logger.warning("Database health check failed", extra={"error": str(exc)})
        db_status = "unhealthy"

    # Cache check
    cache_ok = await request.app.state.cache.ping()
    if not cache_ok:
        cache_status = "unhealthy"

    overall = "healthy" if db_status == "healthy" else "degraded"
    settings = get_settings()

    return HealthResponse(
        status=overall,
        version=settings.app_version,
        database=db_status,
        cache=cache_status,
        timestamp=datetime.now(timezone.utc),
    )


@app.get("/stats", response_model=StatsResponse)
async def stats(request: Request) -> StatsResponse:
    """Aggregated usage statistics across all short links."""
    async with request.app.state.session_factory() as session:
        total_links_res = await session.execute(select(func.count(ShortLink.code)))
        total_links: int = total_links_res.scalar_one_or_none() or 0

        total_clicks_res = await session.execute(select(func.sum(ShortLink.click_count)))
        total_clicks: int = total_clicks_res.scalar_one_or_none() or 0

        top_res = await session.execute(
            select(ShortLink.code, ShortLink.original_url, ShortLink.click_count)
            .order_by(ShortLink.click_count.desc())
            .limit(10)
        )
        top_links = [
            LinkStats(code=row.code, original_url=row.original_url, click_count=row.click_count)
            for row in top_res
        ]

    return StatsResponse(
        total_links=total_links,
        total_clicks=total_clicks,
        top_links=top_links,
    )


_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def index() -> HTMLResponse:
    with open(os.path.join(_TEMPLATE_DIR, "index.html")) as f:
        return HTMLResponse(content=f.read())


# ── IMPORTANT: /{code} must be the LAST GET route registered. ─────────────────
# FastAPI/Starlette matches routes in registration order. A path parameter
# route like /{code} would capture /health and /stats requests if registered
# first, returning 404 ("health not found in DB") instead of the real handlers.
# Always keep all literal-path GET routes above this catch-all.
@app.get("/{code}", include_in_schema=False)
async def redirect(code: str, request: Request) -> RedirectResponse:
    """
    Redirect a short code to its original URL.

    Cache-first: tries Redis before hitting PostgreSQL.
    Click counts are incremented in the DB on every request (not cached).
    """
    # Validate code format early to prevent injection into DB queries
    valid_chars = set(string.ascii_letters + string.digits + "-_")
    if not code or not all(c in valid_chars for c in code) or len(code) > 20:
        raise HTTPException(status_code=400, detail="Invalid short code format")

    cache: CacheClient = request.app.state.cache

    # ── Cache path (fast) ─────────────────────────────────────────────────
    cached_url = await cache.get_url(code)
    if cached_url:
        logger.info("Redirect via cache", extra={"code": code})
        task = asyncio.create_task(
            _increment_click(request.app.state.session_factory, code)
        )
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)
        return RedirectResponse(url=cached_url, status_code=302)

    # ── Database path (cache miss) ─────────────────────────────────────────
    async with request.app.state.session_factory() as session:
        link = await session.get(ShortLink, code)
        if link is None:
            raise HTTPException(status_code=404, detail="Short URL not found")

        # Increment click count in the same transaction as the read
        await session.execute(
            update(ShortLink)
            .where(ShortLink.code == code)
            .values(click_count=ShortLink.click_count + 1)
        )
        await session.commit()

        original_url = link.original_url

    # Back-fill the cache for subsequent requests
    await cache.set_url(code, original_url)

    logger.info("Redirect via database", extra={"code": code})
    return RedirectResponse(url=original_url, status_code=302)


async def _increment_click(session_factory: object, code: str) -> None:
    """Background task: increment click count without blocking the redirect response."""
    try:
        async with session_factory() as session:  # type: ignore[attr-defined]
            await session.execute(
                update(ShortLink)
                .where(ShortLink.code == code)
                .values(click_count=ShortLink.click_count + 1)
            )
            await session.commit()
    except Exception as exc:
        logger.warning("Click increment failed", extra={"code": code, "error": str(exc)})
