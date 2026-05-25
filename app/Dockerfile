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
# Python version alignment:
#   Debian 12 (Bookworm) ships Python 3.11.  Both builder and runtime use
#   Python 3.11 so the venv symlinks (/opt/venv/bin/python → /usr/bin/python3.11)
#   resolve identically in the final image.
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

# Runs as nonroot (UID 65532) — set by the distroless base; no USER directive needed.
# Update Helm values.yaml → securityContext.runAsUser / runAsGroup / fsGroup → 65532

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONFAULTHANDLER=1

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY src/ ./src/

EXPOSE 8000

# Run uvicorn as a Python module — avoids shebang resolution entirely.
# /opt/venv/bin/python → /usr/bin/python3.11 (present in distroless debian12)
CMD ["/opt/venv/bin/python", "-m", "uvicorn", "src.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "1", \
     "--no-access-log"]
