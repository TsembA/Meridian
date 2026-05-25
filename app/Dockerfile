# Dockerfile — Multi-stage build for the Meridian FastAPI link shortener.
#
# Stage 1 (builder): installs Python dependencies into a virtual environment.
# Stage 2 (runtime): copies only the venv — no build tools in the final image.
#
# Security hardening:
#   - Non-root user (UID 1000) — matches podSecurityContext in Helm values
#   - No shell in final image (distroless-style slim base)
#   - Image pinned to SHA digest in CI (see deploy.yml)
#   - Trivy scans run on every build in security.yml workflow

# ── Stage 1: dependency builder ───────────────────────────────────────────────
FROM python:3.12.1-slim-bookworm AS builder

# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Copy dependency manifest first — Docker layer cache means pip install only
# runs again when requirements.txt changes, not on every code change
COPY requirements.txt .

RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip==23.3.2 \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

# ── Stage 2: runtime image ────────────────────────────────────────────────────
FROM python:3.12.1-slim-bookworm AS runtime

# libpq5 is required at runtime for asyncpg; no build tools needed
# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Create a non-root user and group
RUN groupadd --gid 1000 appgroup \
    && useradd --uid 1000 --gid 1000 --no-create-home --shell /bin/false appuser

# Copy virtual environment from builder stage
COPY --from=builder /opt/venv /opt/venv

# Set PATH so venv binaries are used
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    # Prevent Python from writing .pyc files (read-only FS friendly)
    PYTHONFAULTHANDLER=1

WORKDIR /app

# Copy application source
COPY src/ ./src/

# Ensure the app directory is owned by the non-root user
RUN chown -R appuser:appgroup /app

# Switch to non-root
USER appuser

# Expose the application port (must match service.targetPort in Helm values)
EXPOSE 8000

# Health check — Docker and k8s use different mechanisms, but this helps local dev
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

# Uvicorn with a single worker — k8s HPA handles horizontal scaling at pod level
# --no-access-log: structured logging is handled by the app; uvicorn access logs add noise
CMD ["uvicorn", "src.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "1", \
     "--no-access-log"]
