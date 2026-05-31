# Dockerfile — Multi-stage build for the Meridian FastAPI link shortener.
#
# Builder : python:3.11-slim-bookworm  (Docker Official Image)
#   Full build toolchain for native extensions; discarded after this stage.
#
# Runtime : gcr.io/distroless/python3-debian12:nonroot  (Google Distroless)
#   Contains ONLY the Python 3.11 interpreter and its direct runtime links —
#   no shell, no package manager, no curl, no apt. Scans clean with Trivy.
#   Maintained by Google; https://github.com/GoogleContainerTools/distroless
#
# Why PYTHONPATH instead of venv symlinks:
#   The builder's venv creates python3.11 → /usr/local/bin/python3.11 (builder path).
#   Distroless has Python at /usr/bin/python3.11 — different prefix, symlink breaks.
#   Bypassing the venv binary entirely: invoke /usr/bin/python3.11 directly and
#   point PYTHONPATH at the venv's site-packages so all pip-installed packages load.
#
# asyncpg note:
#   asyncpg implements the PostgreSQL wire protocol in Cython — it does NOT
#   link against libpq, so no libpq package is required at build or runtime.
#
# Security posture:
#   - Runs as UID 65532 (distroless nonroot) — no root at any point at runtime
#   - readOnlyRootFilesystem compatible (/tmp emptyDir in k8s)
#   - No HEALTHCHECK (no shell) — k8s liveness/readiness probes handle this
#   - Image pinned to SHA digest in CI (deploy.yml)
#   - Trivy scans on every build (security.yml)

# ── Stage 1: dependency builder ───────────────────────────────────────────────
FROM python:3.11-slim-bookworm AS builder

# Apply available Debian security patches, then add build toolchain.
# This stage is discarded — CVEs here never reach the distroless runtime image.
# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

COPY requirements.txt .

RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

# ── Stage 2: distroless runtime ───────────────────────────────────────────────
FROM gcr.io/distroless/python3-debian12:nonroot AS runtime

USER 65532

# PYTHONPATH makes the venv's packages visible to /usr/bin/python3.11.
# PATH is not used — distroless has no shell to read it.
ENV PYTHONPATH="/opt/venv/lib/python3.11/site-packages" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONFAULTHANDLER=1

WORKDIR /app

COPY --from=builder /opt/venv/lib/python3.11/site-packages /opt/venv/lib/python3.11/site-packages
COPY src/ ./src/

EXPOSE 8000

# Use the distroless Python directly — avoids broken venv symlink
# (venv links python3.11 → /usr/local/bin/python3.11, the builder path,
#  but distroless ships Python at /usr/bin/python3.11).
ENTRYPOINT ["/usr/bin/python3.11", "-m", "uvicorn", "src.main:app", \
            "--host", "0.0.0.0", \
            "--port", "8000", \
            "--workers", "1", \
            "--no-access-log"]
