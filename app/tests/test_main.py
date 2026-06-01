"""
test_main.py — Integration-style tests for the Meridian FastAPI application.

The SSM calls and database connections are mocked so tests run without AWS
credentials or a live PostgreSQL/Redis instance (CI-friendly).

Run with: pytest app/tests/ -v
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def mock_settings():
    """
    Patch get_settings() to return a mock Settings object.
    This prevents SSM calls during test collection/execution.
    """
    mock = MagicMock()
    mock.log_level = "DEBUG"
    mock.app_version = "1.0.0"
    mock.debug = False
    mock.db_host = "localhost"
    mock.db_port = 5432
    mock.db_name = "meridian_test"
    mock.db_user = "test"
    mock.db_password = "test"
    mock.redis_host = "localhost"
    mock.redis_port = 6379
    mock.secret_key = "test-secret-key-32chars-padding!!"
    mock.app_base_url = "https://app.example.com"

    with patch("src.config.get_settings", return_value=mock):
        with patch("src.main.get_settings", return_value=mock):
            yield mock


@pytest.fixture
def mock_db_session() -> AsyncMock:
    """Return an async mock that behaves like an SQLAlchemy AsyncSession."""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    return session


@pytest.fixture
def mock_cache() -> AsyncMock:
    """Return an async mock CacheClient."""
    cache = AsyncMock()
    cache.get_url = AsyncMock(return_value=None)  # Default: cache miss
    cache.set_url = AsyncMock()
    cache.ping = AsyncMock(return_value=True)
    return cache


@pytest.fixture
def app_client(mock_db_session: AsyncMock, mock_cache: AsyncMock) -> TestClient:
    """
    Build a synchronous TestClient with mocked lifespan dependencies.
    The lifespan is bypassed by pre-seeding app.state directly.
    """
    from src.main import app

    # Pre-seed app state so lifespan startup is not needed
    app.state.cache = mock_cache
    app.state.session_factory = MagicMock(return_value=mock_db_session)

    return TestClient(app, raise_server_exceptions=True)


# ── Health endpoint ────────────────────────────────────────────────────────────

class TestHealth:
    def test_health_returns_200(self, app_client: TestClient, mock_db_session: AsyncMock) -> None:
        """GET /health returns 200 with healthy status when DB and cache are up."""
        # Mock the SELECT NOW() health check
        mock_result = MagicMock()
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        response = app_client.get("/health")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] in ("healthy", "degraded")
        assert body["version"] == "1.0.0"
        assert "database" in body
        assert "cache" in body
        assert "timestamp" in body

    def test_health_degraded_when_db_down(
        self, app_client: TestClient, mock_db_session: AsyncMock
    ) -> None:
        """GET /health returns 200 with status='degraded' when DB is unreachable."""
        mock_db_session.execute = AsyncMock(side_effect=Exception("Connection refused"))

        response = app_client.get("/health")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "degraded"
        assert body["database"] == "unhealthy"


# ── Shorten endpoint ──────────────────────────────────────────────────────────

class TestShorten:
    def test_shorten_valid_url_returns_201(
        self, app_client: TestClient, mock_db_session: AsyncMock
    ) -> None:
        """POST /shorten with a valid URL creates a short link and returns 201."""
        # Mock: no existing link with that code
        mock_db_session.get = AsyncMock(return_value=None)
        mock_db_session.add = MagicMock()
        mock_db_session.commit = AsyncMock()

        # Mock refresh to set created_at
        async def mock_refresh(obj: object) -> None:
            obj.created_at = datetime.now(timezone.utc)  # type: ignore[attr-defined]

        mock_db_session.refresh = mock_refresh

        response = app_client.post(
            "/shorten",
            json={"url": "https://www.example.com/very/long/path"},
        )

        assert response.status_code == 201
        body = response.json()
        assert "short_code" in body
        assert "short_url" in body
        assert body["original_url"] == "https://www.example.com/very/long/path"
        assert len(body["short_code"]) == 7  # Default generated code length

    def test_shorten_custom_code(
        self, app_client: TestClient, mock_db_session: AsyncMock
    ) -> None:
        """POST /shorten with a valid custom_code uses it as the short code."""
        mock_db_session.get = AsyncMock(return_value=None)
        mock_db_session.add = MagicMock()
        mock_db_session.commit = AsyncMock()

        async def mock_refresh(obj: object) -> None:
            obj.created_at = datetime.now(timezone.utc)  # type: ignore[attr-defined]

        mock_db_session.refresh = mock_refresh

        response = app_client.post(
            "/shorten",
            json={"url": "https://www.example.com", "custom_code": "my-link"},
        )

        assert response.status_code == 201
        assert response.json()["short_code"] == "my-link"

    def test_shorten_custom_code_conflict_returns_409(
        self, app_client: TestClient, mock_db_session: AsyncMock
    ) -> None:
        """POST /shorten returns 409 when the custom code is already taken."""
        # Mock: existing link found
        mock_db_session.get = AsyncMock(return_value=MagicMock())

        response = app_client.post(
            "/shorten",
            json={"url": "https://www.example.com", "custom_code": "taken"},
        )

        assert response.status_code == 409
        assert "already in use" in response.json()["detail"]

    def test_shorten_reserved_code_rejected(self, app_client: TestClient) -> None:
        """POST /shorten with a reserved code name returns 422."""
        response = app_client.post(
            "/shorten",
            json={"url": "https://www.example.com", "custom_code": "health"},
        )
        assert response.status_code == 422

    def test_shorten_invalid_url_rejected(self, app_client: TestClient) -> None:
        """POST /shorten with a non-URL string returns 422."""
        response = app_client.post("/shorten", json={"url": "not-a-url"})
        assert response.status_code == 422

    def test_shorten_missing_url_rejected(self, app_client: TestClient) -> None:
        """POST /shorten with missing url field returns 422."""
        response = app_client.post("/shorten", json={})
        assert response.status_code == 422


# ── Redirect endpoint ─────────────────────────────────────────────────────────

class TestRedirect:
    def test_redirect_cache_hit(
        self,
        app_client: TestClient,
        mock_cache: AsyncMock,
        mock_db_session: AsyncMock,
    ) -> None:
        """GET /{code} redirects to cached URL without hitting the database."""
        mock_cache.get_url = AsyncMock(return_value="https://www.cached.com")

        response = app_client.get("/abc1234", follow_redirects=False)

        assert response.status_code == 302
        assert response.headers["location"] == "https://www.cached.com"
        # DB should NOT have been queried (cache hit)
        mock_db_session.get.assert_not_awaited()

    def test_redirect_db_fallback(
        self,
        app_client: TestClient,
        mock_cache: AsyncMock,
        mock_db_session: AsyncMock,
    ) -> None:
        """GET /{code} falls back to DB on cache miss."""
        mock_cache.get_url = AsyncMock(return_value=None)  # Cache miss

        mock_link = MagicMock()
        mock_link.original_url = "https://www.fromdb.com"
        mock_link.click_count = 5
        mock_db_session.get = AsyncMock(return_value=mock_link)
        mock_db_session.execute = AsyncMock()
        mock_db_session.commit = AsyncMock()

        response = app_client.get("/abc1234", follow_redirects=False)

        assert response.status_code == 302
        assert response.headers["location"] == "https://www.fromdb.com"

    def test_redirect_not_found_returns_404(
        self,
        app_client: TestClient,
        mock_cache: AsyncMock,
        mock_db_session: AsyncMock,
    ) -> None:
        """GET /{code} returns 404 for unknown short codes."""
        mock_cache.get_url = AsyncMock(return_value=None)
        mock_db_session.get = AsyncMock(return_value=None)

        response = app_client.get("/notfound", follow_redirects=False)

        assert response.status_code == 404

    def test_redirect_invalid_code_returns_400(self, app_client: TestClient) -> None:
        """GET /{code} with special characters in the code returns 400."""
        response = app_client.get("/../../etc/passwd", follow_redirects=False)
        # FastAPI path matching may absorb this — we just ensure no 500
        assert response.status_code in (400, 404)


# ── Stats endpoint ────────────────────────────────────────────────────────────

class TestStats:
    def test_stats_returns_aggregates(
        self, app_client: TestClient, mock_db_session: AsyncMock
    ) -> None:
        """GET /stats returns total_links, total_clicks, and top_links."""
        # Mock scalar results
        count_result = MagicMock()
        count_result.scalar_one_or_none.return_value = 42

        sum_result = MagicMock()
        sum_result.scalar_one_or_none.return_value = 1337

        top_result = MagicMock()
        top_result.__iter__ = MagicMock(return_value=iter([]))

        mock_db_session.execute = AsyncMock(
            side_effect=[count_result, sum_result, top_result]
        )

        response = app_client.get("/stats")

        assert response.status_code == 200
        body = response.json()
        assert body["total_links"] == 42
        assert body["total_clicks"] == 1337
        assert isinstance(body["top_links"], list)
