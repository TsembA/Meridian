"""
models.py — Pydantic request/response models for the Meridian link shortener API.

All input validation happens here via Pydantic v2 — no raw string manipulation
in the route handlers. Reserved paths are blocked to prevent shadowing API routes.
"""

from datetime import datetime
from typing import Any, Optional

from pydantic import AnyHttpUrl, BaseModel, Field, field_validator


# ── Request Models ────────────────────────────────────────────────────────────

class ShortenRequest(BaseModel):
    """Request body for POST /shorten."""

    url: AnyHttpUrl = Field(
        ...,
        description="The original URL to shorten. Must be a valid HTTP/HTTPS URL.",
        examples=["https://www.example.com/some/very/long/path?query=value"],
    )
    custom_code: Optional[str] = Field(
        default=None,
        min_length=3,
        max_length=20,
        pattern=r"^[a-zA-Z0-9_-]+$",
        description=(
            "Optional custom short code (3–20 chars, alphanumeric plus - and _). "
            "Returns 409 if already taken."
        ),
        examples=["my-link", "promo2024"],
    )

    @field_validator("custom_code")
    @classmethod
    def reject_reserved_paths(cls, v: Optional[str]) -> Optional[str]:
        """Block codes that would shadow API routes."""
        if v is None:
            return v
        # These paths are served by FastAPI route handlers — a short code with
        # the same name would make the route unreachable.
        reserved: frozenset[str] = frozenset(
            {"health", "metrics", "stats", "shorten", "admin", "docs", "openapi"}
        )
        if v.lower() in reserved:
            raise ValueError(
                f"'{v}' is a reserved path and cannot be used as a short code"
            )
        return v


# ── Response Models ───────────────────────────────────────────────────────────

class ShortenResponse(BaseModel):
    """Response for POST /shorten."""

    short_code: str = Field(description="The generated or custom short code")
    short_url: str = Field(description="Full short URL ready to share")
    original_url: str = Field(description="The destination URL")
    created_at: datetime = Field(description="UTC timestamp of creation")
    expires_at: Optional[datetime] = Field(
        default=None,
        description="Expiry timestamp, or null for permanent links",
    )


class LinkStats(BaseModel):
    """Per-link stats entry in StatsResponse.top_links."""

    code: str
    original_url: str
    click_count: int


class StatsResponse(BaseModel):
    """Response for GET /stats."""

    total_links: int = Field(description="Total number of short links created")
    total_clicks: int = Field(description="Total redirect events across all links")
    top_links: list[LinkStats] = Field(
        description="Top 10 most-clicked links (descending order)"
    )


class HealthResponse(BaseModel):
    """Response for GET /health — liveness and dependency status."""

    status: str = Field(description="'healthy' or 'degraded'")
    version: str = Field(description="Application version string")
    database: str = Field(description="'healthy' or 'unhealthy'")
    cache: str = Field(description="'healthy' or 'unhealthy'")
    timestamp: datetime = Field(description="UTC timestamp of the health check")
