"""
logger.py — Structured JSON logging configuration for the Meridian application.

All log output is newline-delimited JSON so it can be ingested by CloudWatch Logs
Insights, Loki, or any log aggregation system without a parsing pipeline.

Usage:
    from src.logger import configure_logging
    configure_logging(level="INFO")

    logger = logging.getLogger(__name__)
    logger.info("Short URL created", extra={"code": "abc123", "url": "https://..."})
"""

import json
import logging
import sys
import traceback
from datetime import datetime, timezone
from typing import Any


class JSONFormatter(logging.Formatter):
    """Format LogRecord objects as single-line JSON strings."""

    # Fields present on every LogRecord that we don't want in the JSON body
    # (they're either redundant or already promoted to top-level fields)
    _SKIP_FIELDS: frozenset[str] = frozenset(
        {
            "args", "asctime", "created", "exc_info", "exc_text", "filename",
            "funcName", "id", "levelname", "levelno", "lineno", "message",
            "module", "msecs", "msg", "name", "pathname", "process",
            "processName", "relativeCreated", "stack_info", "thread",
            "threadName", "taskName",
        }
    )

    def format(self, record: logging.LogRecord) -> str:
        # Render the message first so %(key)s substitutions are applied
        record.message = record.getMessage()

        entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.message,
            "location": f"{record.pathname}:{record.lineno}",
        }

        # Attach exception details as a structured field, not a raw string
        if record.exc_info and record.exc_info[0] is not None:
            exc_type, exc_value, exc_tb = record.exc_info
            entry["exception"] = {
                "type": exc_type.__name__,
                "message": str(exc_value),
                "traceback": traceback.format_exception(exc_type, exc_value, exc_tb),
            }

        # Attach any extra= fields the caller passed
        for key, value in record.__dict__.items():
            if key not in self._SKIP_FIELDS and not key.startswith("_"):
                entry[key] = value

        return json.dumps(entry, default=str)


def configure_logging(level: str = "INFO") -> None:
    """
    Configure the root logger with the JSON formatter.

    Call once at application startup before any logger is used.
    Re-calling is safe (replaces existing handlers).
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())

    numeric_level = getattr(logging, level.upper(), logging.INFO)

    root = logging.getLogger()
    root.setLevel(numeric_level)
    # Replace existing handlers to avoid duplicate output
    root.handlers = [handler]

    # Reduce noise from verbose third-party libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("asyncpg").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.INFO if level.upper() == "DEBUG" else logging.WARNING
    )
