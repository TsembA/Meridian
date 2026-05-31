"""
config.py — Application configuration.

All config (including secrets) is read from environment variables.
Secrets are injected as a Kubernetes Secret by the CI pipeline during deploy —
sourced from AWS SSM Parameter Store at deploy time. The app never calls AWS at runtime.
"""

import logging
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    # ── Non-secret config (from ConfigMap) ───────────────────────────────────
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    app_version: str = Field(default="1.0.0", alias="APP_VERSION")
    debug: bool = Field(default=False, alias="DEBUG")

    # ── Secrets (from Kubernetes Secret, populated by CI from SSM) ───────────
    db_host: str = Field(alias="DB_HOST")
    db_port: int = Field(default=5432, alias="DB_PORT")
    db_name: str = Field(alias="DB_NAME")
    db_user: str = Field(alias="DB_USER")
    db_password: str = Field(alias="DB_PASSWORD")

    redis_host: str = Field(alias="REDIS_HOST")
    redis_port: int = Field(default=6379, alias="REDIS_PORT")

    secret_key: str = Field(alias="SECRET_KEY")
    app_base_url: str = Field(alias="APP_BASE_URL")

    class Config:
        populate_by_name = True
        env_file = None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached Settings singleton."""
    return Settings()
