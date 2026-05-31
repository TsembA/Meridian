# Dockerfile — Multi-stage build for the Meridian MCP diagnostic agent.
#
# Builder : python:3.11-slim-bookworm  (Docker Official Image)
# Runtime : gcr.io/distroless/python3-debian12:nonroot  (Google Distroless)
#
# Why PYTHONPATH instead of venv symlinks: same reason as app/Dockerfile —
# the venv's python3.11 symlink points to /usr/local/bin (builder path),
# but distroless has Python at /usr/bin/python3.11.

# ── Stage 1: dependency builder ───────────────────────────────────────────────
FROM python:3.11-slim-bookworm AS builder

# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

COPY requirements.txt .

RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

# ── Stage 2: distroless runtime ───────────────────────────────────────────────
FROM gcr.io/distroless/python3-debian12:nonroot AS runtime

USER 65532

ENV PYTHONPATH="/opt/venv/lib/python3.11/site-packages" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONFAULTHANDLER=1

WORKDIR /app

COPY --from=builder /opt/venv/lib/python3.11/site-packages /opt/venv/lib/python3.11/site-packages
COPY src/ ./src/

EXPOSE 8080

ENTRYPOINT ["/usr/bin/python3.11", "-m", "src.server"]
