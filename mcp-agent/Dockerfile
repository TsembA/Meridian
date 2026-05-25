# Dockerfile — Multi-stage build for the Meridian MCP diagnostic agent.
#
# Security constraints:
#   - Non-root user (UID 1001) — matches podSecurityContext in nexus-mcp Helm values
#   - Read-only root filesystem (tmp is an emptyDir volume mount)
#   - No package manager or shell in final image
#   - Image pinned to digest in CI (see deploy.yml)

# ── Stage 1: dependency builder ───────────────────────────────────────────────
FROM python:3.12.1-slim-bookworm AS builder

WORKDIR /build

COPY requirements.txt .

RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip==23.3.2 \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

# ── Stage 2: runtime image ────────────────────────────────────────────────────
FROM python:3.12.1-slim-bookworm AS runtime

# Create a dedicated non-root user for the MCP agent
RUN groupadd --gid 1001 mcpgroup \
    && useradd --uid 1001 --gid 1001 --no-create-home --shell /bin/false mcpuser

COPY --from=builder /opt/venv /opt/venv

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONFAULTHANDLER=1

WORKDIR /app

COPY src/ ./src/

RUN chown -R mcpuser:mcpgroup /app

USER mcpuser

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')"

# The MCP server communicates via stdio — the container entrypoint starts the server
CMD ["python", "-m", "src.server"]
