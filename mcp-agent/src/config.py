"""
config.py — Configuration for the Meridian MCP diagnostic agent.

Non-secret config (URLs, log level) comes from environment variables set in
the Helm values.yaml. Secrets (GitHub token) come from SSM Parameter Store.
"""

import logging
import os
from functools import lru_cache

import boto3
from botocore.exceptions import ClientError
from pydantic import Field
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)


class MCPSettings(BaseSettings):
    """Settings for the MCP agent server."""

    # ── Non-secret (from env / Helm ConfigMap) ────────────────────────────────
    aws_region: str = Field(default="us-west-1", alias="AWS_REGION")
    ssm_prefix: str = Field(default="/meridian", alias="SSM_PREFIX")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # Internal cluster URLs — no secrets
    prometheus_url: str = Field(
        default="http://kube-prometheus-stack-prometheus.monitoring.svc.cluster.local:9090",
        alias="PROMETHEUS_URL",
    )
    alertmanager_url: str = Field(
        default="http://kube-prometheus-stack-alertmanager.monitoring.svc.cluster.local:9093",
        alias="ALERTMANAGER_URL",
    )

    mcp_host: str = Field(default="0.0.0.0", alias="MCP_HOST")
    mcp_port: int = Field(default=8080, alias="MCP_PORT")
    audit_log_path: str = Field(default="/tmp/audit.jsonl", alias="AUDIT_LOG_PATH")

    # ── Secrets (populated from SSM) ─────────────────────────────────────────
    github_token: str = ""
    github_repo_owner: str = ""
    github_repo_name: str = ""

    # PostgreSQL host for connectivity check (no password needed — just a TCP ping)
    db_host: str = ""
    db_port: int = 5432

    class Config:
        populate_by_name = True
        env_file = None

    def model_post_init(self, __context: object) -> None:
        self._load_from_ssm()

    def _load_from_ssm(self) -> None:
        """Fetch secrets from SSM. Non-fatal if GitHub token is missing."""
        try:
            ssm = boto3.client("ssm", region_name=self.aws_region)
            param_map = {
                f"{self.ssm_prefix}/github/token": "github_token",
                f"{self.ssm_prefix}/github/repo-owner": "github_repo_owner",
                f"{self.ssm_prefix}/github/repo-name": "github_repo_name",
                f"{self.ssm_prefix}/db/host": "db_host",
                f"{self.ssm_prefix}/db/port": "db_port",
            }
            response = ssm.get_parameters(
                Names=list(param_map.keys()),
                WithDecryption=True,
            )
            for param in response["Parameters"]:
                attr = param_map[param["Name"]]
                val = param["Value"]
                object.__setattr__(self, attr, int(val) if attr == "db_port" else val)
                logger.info("Loaded SSM parameter", extra={"name": param["Name"]})

            if response.get("InvalidParameters"):
                logger.warning(
                    "Some SSM parameters not found",
                    extra={"missing": response["InvalidParameters"]},
                )
        except ClientError as exc:
            # Non-fatal: MCP agent can still answer most queries without GitHub token
            logger.warning("SSM fetch failed — some tools may be unavailable", extra={"error": str(exc)})


@lru_cache(maxsize=1)
def get_mcp_settings() -> MCPSettings:
    """Cached MCP settings singleton."""
    return MCPSettings()
