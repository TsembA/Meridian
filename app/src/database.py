"""
database.py — Async SQLAlchemy engine, session factory, and ORM model for the
Meridian link shortener.

Connection string is assembled from SSM-sourced settings — no credentials appear
in code or environment variables. Uses asyncpg driver for non-blocking I/O.
"""

import logging
from typing import AsyncGenerator
from urllib.parse import quote

from sqlalchemy import Column, DateTime, Integer, String, Text, func, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

logger = logging.getLogger(__name__)


# ── ORM Base ──────────────────────────────────────────────────────────────────

class Base(DeclarativeBase):
    """SQLAlchemy declarative base for all ORM models."""
    pass


# ── ORM Model ─────────────────────────────────────────────────────────────────

class ShortLink(Base):
    """Represents a short URL mapping in the database."""

    __tablename__ = "short_links"

    # Short code is the primary key — no surrogate integer PK needed
    code = Column(String(20), primary_key=True, index=True, nullable=False)
    original_url = Column(Text, nullable=False)
    click_count = Column(Integer, default=0, nullable=False)

    # server_default uses the DB clock — avoids timezone skew between app and DB
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=True,
    )

    def __repr__(self) -> str:
        return f"<ShortLink code={self.code!r} clicks={self.click_count}>"


# ── Engine Factory ────────────────────────────────────────────────────────────

def create_db_engine(settings: "Settings") -> AsyncEngine:  # type: ignore[name-defined]
    """
    Build an async SQLAlchemy engine from SSM-sourced settings.

    pool_pre_ping=True prevents stale connection errors after the DB restarts
    (common after k3s pod reschedules the PostgreSQL container).
    """
    dsn = (
        f"postgresql+asyncpg://{quote(settings.db_user, safe='')}:{quote(settings.db_password, safe='')}"
        f"@{settings.db_host}:{settings.db_port}/{settings.db_name}"
    )

    engine = create_async_engine(
        dsn,
        pool_size=5,           # Conservative — t3.micro + single container
        max_overflow=5,
        pool_pre_ping=True,    # Verify connection health before each checkout
        pool_recycle=1800,     # Recycle connections every 30 min — avoids server-side timeouts
        echo=settings.debug,   # Log SQL only in debug mode — never in production
    )

    logger.info(
        "Database engine created",
        extra={"host": settings.db_host, "db": settings.db_name},
    )
    return engine


async def init_db(engine: AsyncEngine) -> None:
    """
    Create all tables defined in Base.metadata if they don't already exist.

    Idempotent — safe to call on every startup. For schema migrations beyond
    initial creation, use Alembic.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Verify connectivity with a trivial query
        await conn.execute(text("SELECT 1"))
    logger.info("Database schema initialised")


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Return an async session factory bound to the given engine."""
    return async_sessionmaker(
        engine,
        expire_on_commit=False,  # Objects remain usable after commit without re-query
        class_=AsyncSession,
    )
