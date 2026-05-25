"""
config.py — Application configuration loader.

All secrets (DB password, Redis password, secret key) are fetched from
AWS SSM Parameter Store at startup via boto3. This module is the single
point of truth for runtime configuration — no .env files, no hardcoded values.

Design notes:
  - `get_settings()` is cached with `@lru_cache` so SSM is called only once per process.
  - Pydantic Settings handles non-secret config (AWS region, log level) from env vars.
  - SSM fetch failures are fatal at startup — better to crash clearly than run misconfigured.
"""

import logging
import os
from functools import lru_cache
from typing import Optional

import boto3
from botocore.exceptions import ClientError, NoCredentialsError
from pydantic import Field
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """
    Application settings.

    Non-secret values come from environment variables (set in Helm ConfigMap).
    Secret values are populated by `_load_from_ssm()` at instantiation time.
    """

    # ── Non-secret config (from env / ConfigMap) ──────────────────────────────
    aws_region: str = Field(default="us-west-1", alias="AWS_REGION")
    ssm_prefix: str = Field(default="/meridian", alias="SSM_PREFIX")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    app_version: str = Field(default="1.0.0", alias="APP_VERSION")
    debug: bool = Field(default=False, alias="DEBUG")

    # ── Secrets (populated from SSM) ─────────────────────────────────────────
    db_host: Optional[str] = None
    db_port: int = 5432
    db_name: Optional[str] = None
    db_user: Optional[str] = None
    db_password: Optional[str] = None

    redis_host: Optional[str] = None
    redis_port: int = 6379

    secret_key: Optional[str] = None
    app_base_url: Optional[str] = None

    class Config:
        # Allow both env var names and Python attribute names
        populate_by_name = True
        # Read from environment variables only (not .env files)
        env_file = None

    def model_post_init(self, __context: object) -> None:
        """Fetch secrets from SSM immediately after Pydantic validation."""
        self._load_from_ssm()

    def _load_from_ssm(self) -> None:
        """
        Fetch all /meridian/* parameters from SSM Parameter Store in a single
        batch call (GetParameters is more efficient than individual GetParameter).

        Raises RuntimeError if any required secret is missing.
        """
        try:
            ssm = boto3.client("ssm", region_name=self.aws_region)
        except NoCredentialsError as exc:
            raise RuntimeError(
                "No AWS credentials available — ensure the EC2 instance profile is attached"
            ) from exc

        # Map SSM parameter name → Settings attribute name
        param_map: dict[str, str] = {
            f"{self.ssm_prefix}/db/host": "db_host",
            f"{self.ssm_prefix}/db/port": "db_port",
            f"{self.ssm_prefix}/db/name": "db_name",
            f"{self.ssm_prefix}/db/user": "db_user",
            f"{self.ssm_prefix}/db/password": "db_password",
            f"{self.ssm_prefix}/redis/host": "redis_host",
            f"{self.ssm_prefix}/redis/port": "redis_port",
            f"{self.ssm_prefix}/app/secret-key": "secret_key",
            f"{self.ssm_prefix}/app/base-url": "app_base_url",
        }

        try:
            response = ssm.get_parameters(
                Names=list(param_map.keys()),
                WithDecryption=True,  # Required for SecureString parameters
            )
        except ClientError as exc:
            raise RuntimeError(f"SSM GetParameters failed: {exc}") from exc

        # Populate attributes from the response
        for param in response["Parameters"]:
            attr = param_map[param["Name"]]
            raw_value = param["Value"]

            # Coerce port numbers to int
            if attr in ("db_port", "redis_port"):
                object.__setattr__(self, attr, int(raw_value))
            else:
                object.__setattr__(self, attr, raw_value)

            logger.info("Loaded SSM parameter", extra={"name": param["Name"]})

        # Log missing parameters (non-fatal warning — some may have defaults)
        if response.get("InvalidParameters"):
            logger.warning(
                "SSM parameters not found — using defaults",
                extra={"missing": response["InvalidParameters"]},
            )

        # Fail hard if genuinely required secrets are absent
        required = ["db_host", "db_name", "db_user", "db_password", "secret_key"]
        missing = [r for r in required if not getattr(self, r)]
        if missing:
            raise RuntimeError(
                f"Required SSM parameters not found: {missing}. "
                f"Run the runbook to populate: aws ssm put-parameter ..."
            )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Return the cached Settings singleton.

    SSM is fetched exactly once per process — subsequent calls return the cached instance.
    Use `get_settings.cache_clear()` in tests to force re-initialisation.
    """
    return Settings()
