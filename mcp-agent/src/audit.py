"""
audit.py — Audit logging for MCP tool invocations.

Every call to an MCP tool is recorded as a structured JSON entry in the audit log.
This provides an immutable trail of what the AI agent queried and when.

Log format (one JSON object per line):
    {
        "timestamp": "2024-01-15T10:30:00.000000+00:00",
        "event": "mcp_tool_invoked",
        "tool": "get_pod_status",
        "inputs": {"namespace": "meridian"},       # sanitised — no secrets
        "outcome": "success",
        "duration_ms": 42,
        "error": null
    }
"""

import json
import logging
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator, Optional

logger = logging.getLogger(__name__)


class AuditLogger:
    """
    Writes structured JSON audit entries to a file and the Python logger.

    The file path must be on a writable volume (emptyDir in k8s).
    Failures to write the audit log are logged but do not raise — the tool
    response is still returned to the caller.
    """

    def __init__(self, log_path: str) -> None:
        self._path = Path(log_path)
        # Ensure parent directory exists
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.warning("Cannot create audit log directory", extra={"error": str(exc)})

    def record(
        self,
        tool: str,
        inputs: dict[str, Any],
        outcome: str,
        duration_ms: float,
        error: Optional[str] = None,
    ) -> None:
        """Write one audit entry."""
        entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": "mcp_tool_invoked",
            "tool": tool,
            "inputs": self._sanitise(inputs),
            "outcome": outcome,
            "duration_ms": round(duration_ms, 2),
            "error": error,
        }

        line = json.dumps(entry, default=str)

        # Always emit to the structured application logger (captured by k8s log driver)
        logger.info("MCP tool invoked", extra=entry)

        # Also append to the audit file (persistent within the pod lifetime)
        try:
            with self._path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError as exc:
            logger.warning(
                "Audit file write failed",
                extra={"path": str(self._path), "error": str(exc)},
            )

    @staticmethod
    def _sanitise(inputs: dict[str, Any]) -> dict[str, Any]:
        """
        Remove any key that looks like it might contain a credential.

        The MCP agent should never receive secrets as tool inputs (Pydantic validation
        prevents it), but this is a defence-in-depth guard.
        """
        sensitive_keywords = {"password", "secret", "token", "key", "credential", "auth"}
        return {
            k: "***REDACTED***" if any(kw in k.lower() for kw in sensitive_keywords) else v
            for k, v in inputs.items()
        }


@contextmanager
def audit_tool_call(
    audit_logger: AuditLogger,
    tool: str,
    inputs: dict[str, Any],
) -> Generator[None, None, None]:
    """
    Context manager that records the outcome of an MCP tool call.

    Usage:
        with audit_tool_call(audit, "get_pod_status", {"namespace": "meridian"}):
            result = await fetch_pod_status(...)

    On success: records outcome="success" with elapsed time.
    On exception: records outcome="error" with the exception message, then re-raises.
    """
    start = time.monotonic()
    try:
        yield
        duration = (time.monotonic() - start) * 1000
        audit_logger.record(tool=tool, inputs=inputs, outcome="success", duration_ms=duration)
    except Exception as exc:
        duration = (time.monotonic() - start) * 1000
        audit_logger.record(
            tool=tool,
            inputs=inputs,
            outcome="error",
            duration_ms=duration,
            error=str(exc),
        )
        raise
