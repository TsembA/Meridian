# Dockerfile — Multi-stage build for the Meridian MCP diagnostic agent.
#
# Builder : python:3.11-slim-bookworm  (Docker Official Image)
# Runtime : gcr.io/distroless/python3-debian12:nonroot  (Google Distroless)
#
# All mcp-agent dependencies (mcp, kubernetes, httpx, pydantic, boto3) are
# pure Python — no native C extensions, so no extra build tools needed.
#
# Runs as UID 65532 (distroless nonroot). Update Helm values:
#   securityContext.runAsUser / runAsGroup / fsGroup → 65532

# ── Stage 1: dependency builder ───────────────────────────────────────────────
FROM python:3.11-slim-bookworm AS builder

# Apply available Debian security patches in the builder layer.
# This stage is discarded — CVEs here never reach the distroless runtime image.
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

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONFAULTHANDLER=1

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY src/ ./src/

EXPOSE 8080

CMD ["/opt/venv/bin/python", "-m", "src.server"]
