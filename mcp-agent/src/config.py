"""
config.py — Configuration for the Meridian MCP diagnostic agent.

Non-secret config (URLs, log level) comes from environment variables set in
the Helm values.yaml. Secrets are injected at deploy time via a k8s Secret
(meridian-mcp-secrets) and arrive as environment variables — no AWS calls at
runtime, consistent with the IMDS hop-limit=1 constraint.
"""

import logging
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)


class MCPSettings(BaseSettings):
    """Settings for the MCP agent server."""

    # ── Non-secret (from env / Helm values) ──────────────────────────────────
    aws_region: str = Field(default="us-west-1", alias="AWS_REGION")
    ssm_prefix: str = Field(default="/meridian", alias="SSM_PREFIX")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    prometheus_url: str = Field(
        default="https://prometheus-prod-67-prod-us-west-0.grafana.net/api/prom",
        alias="PROMETHEUS_URL",
    )
    alertmanager_url: str = Field(
        default="https://alertmanager-prod-67-prod-us-west-0.grafana.net",
        alias="ALERTMANAGER_URL",
    )
    grafana_cloud_instance_id: str = Field(default="", alias="GRAFANA_CLOUD_INSTANCE_ID")
    grafana_cloud_api_key: str = Field(default="", alias="GRAFANA_CLOUD_API_KEY")

    mcp_host: str = Field(default="0.0.0.0", alias="MCP_HOST")
    mcp_port: int = Field(default=8080, alias="MCP_PORT")
    audit_log_path: str = Field(default="/tmp/audit.jsonl", alias="AUDIT_LOG_PATH")

    # ── Secrets (injected by CI into meridian-mcp-secrets k8s Secret) ────────
    github_token: str = Field(default="", alias="GITHUB_TOKEN")
    github_repo_owner: str = Field(default="", alias="GITHUB_REPO_OWNER")
    github_repo_name: str = Field(default="", alias="GITHUB_REPO_NAME")

    # PostgreSQL host for connectivity check (no password needed — TCP ping only)
    db_host: str = Field(default="", alias="DB_HOST")
    db_port: int = Field(default=5432, alias="DB_PORT")

    class Config:
        populate_by_name = True
        env_file = None


@lru_cache(maxsize=1)
def get_mcp_settings() -> MCPSettings:
    """Cached MCP settings singleton."""
    return MCPSettings()
