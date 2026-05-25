"""
cache.py — Redis async client wrapper for URL redirect caching.

Caches the short_code → original_url mapping so frequent redirects (the hot path)
bypass the database. Cache misses fall through to PostgreSQL gracefully.

Failure philosophy: cache errors are logged and swallowed — the application
must remain functional even when Redis is unavailable (degraded mode).
"""

import logging
from typing import Optional

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

# How long a cached URL entry lives (seconds).
# 1 hour is a balance between cache freshness and DB load reduction.
CACHE_TTL_SECONDS: int = 3600

# Redis key prefix — namespaces our entries to avoid collisions with other apps
KEY_PREFIX: str = "meridian:url:"


class CacheClient:
    """
    Thin async wrapper around the redis.asyncio client.

    All methods handle exceptions internally and return safe fallbacks —
    callers do not need to wrap cache calls in try/except.
    """

    def __init__(self, host: str, port: int = 6379) -> None:
        # decode_responses=True returns Python str, not bytes
        self._client: aioredis.Redis = aioredis.from_url(
            f"redis://{host}:{port}",
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=3,
            retry_on_timeout=False,  # Fast-fail — don't block the request waiting for Redis
        )
        logger.info("Redis client initialised", extra={"host": host, "port": port})

    # ── Public API ────────────────────────────────────────────────────────────

    async def get_url(self, code: str) -> Optional[str]:
        """
        Look up the original URL for a short code.

        Returns None on cache miss or Redis error.
        """
        try:
            value: Optional[str] = await self._client.get(f"{KEY_PREFIX}{code}")
            if value:
                logger.debug("Cache hit", extra={"code": code})
            else:
                logger.debug("Cache miss", extra={"code": code})
            return value
        except Exception as exc:
            logger.warning(
                "Cache get failed — degrading gracefully",
                extra={"code": code, "error": str(exc)},
            )
            return None

    async def set_url(self, code: str, url: str) -> None:
        """
        Store a short_code → URL mapping with a TTL.

        Fire-and-forget — errors are logged but not raised.
        """
        try:
            await self._client.set(f"{KEY_PREFIX}{code}", url, ex=CACHE_TTL_SECONDS)
            logger.debug("Cache set", extra={"code": code, "ttl": CACHE_TTL_SECONDS})
        except Exception as exc:
            logger.warning(
                "Cache set failed",
                extra={"code": code, "error": str(exc)},
            )

    async def delete_url(self, code: str) -> None:
        """Evict a short code from cache (called after DB delete)."""
        try:
            await self._client.delete(f"{KEY_PREFIX}{code}")
        except Exception as exc:
            logger.warning(
                "Cache delete failed",
                extra={"code": code, "error": str(exc)},
            )

    async def ping(self) -> bool:
        """
        Health check — returns True if Redis is reachable, False otherwise.
        Used by GET /health to report cache status.
        """
        try:
            await self._client.ping()
            return True
        except Exception:
            return False

    async def close(self) -> None:
        """Close the underlying connection pool on application shutdown."""
        try:
            await self._client.aclose()
        except Exception:
            pass  # Shutdown errors are not actionable
