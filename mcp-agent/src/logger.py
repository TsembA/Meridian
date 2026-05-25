"""
logger.py — Structured JSON logging for the MCP agent (shared with app/src/logger.py pattern).
"""

import json
import logging
import sys
import traceback
from datetime import datetime, timezone
from typing import Any


class JSONFormatter(logging.Formatter):
    _SKIP_FIELDS: frozenset[str] = frozenset(
        {"args","asctime","created","exc_info","exc_text","filename","funcName",
         "id","levelname","levelno","lineno","message","module","msecs","msg",
         "name","pathname","process","processName","relativeCreated","stack_info",
         "thread","threadName","taskName"}
    )

    def format(self, record: logging.LogRecord) -> str:
        record.message = record.getMessage()
        entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.message,
            "location": f"{record.pathname}:{record.lineno}",
        }
        if record.exc_info and record.exc_info[0] is not None:
            exc_type, exc_value, exc_tb = record.exc_info
            entry["exception"] = {
                "type": exc_type.__name__,
                "message": str(exc_value),
                "traceback": traceback.format_exception(exc_type, exc_value, exc_tb),
            }
        for key, value in record.__dict__.items():
            if key not in self._SKIP_FIELDS and not key.startswith("_"):
                entry[key] = value
        return json.dumps(entry, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(numeric_level)
    root.handlers = [handler]
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("kubernetes").setLevel(logging.WARNING)
