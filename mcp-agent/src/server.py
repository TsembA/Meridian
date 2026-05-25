"""
server.py — MCP server entry point for the Meridian diagnostic agent.

Registers all six diagnostic tools and starts the MCP server over stdio (for
Claude Desktop / claude CLI integration) or HTTP (for in-cluster access).

Security constraints enforced here:
  - All tool inputs pass through Pydantic models in tools.py before execution
  - No shell=True calls anywhere in this file or tools.py
  - Audit logger records every tool invocation before and after execution
  - Server is ClusterIP-only — not exposed to the public internet
"""

import asyncio
import logging
from typing import Any

import mcp.server.stdio as stdio_transport
from mcp import types
from mcp.server import Server
from mcp.server.models import InitializationOptions

from .audit import AuditLogger, audit_tool_call
from .config import get_mcp_settings
from .logger import configure_logging
from .tools import (
    DeploymentHistoryInput,
    NodeMetricsInput,
    PodLogsInput,
    PodStatusInput,
    get_active_alerts,
    get_db_connectivity,
    get_deployment_history,
    get_node_metrics,
    get_pod_status,
    get_recent_logs,
)

configure_logging(level=get_mcp_settings().log_level)
logger = logging.getLogger(__name__)

settings = get_mcp_settings()
audit = AuditLogger(log_path=settings.audit_log_path)

# ── MCP Server ────────────────────────────────────────────────────────────────

server = Server("meridian-mcp")


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    """Advertise available diagnostic tools to the MCP client."""
    return [
        types.Tool(
            name="get_pod_status",
            description=(
                "List all pods in a Kubernetes namespace with their phase, readiness, "
                "and restart counts. Read-only — no mutations performed."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "namespace": {
                        "type": "string",
                        "description": "Kubernetes namespace to inspect (default: 'meridian')",
                        "default": "meridian",
                    }
                },
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="get_recent_logs",
            description=(
                "Retrieve the last N log lines from a specific pod. "
                "Read-only — no modifications to the pod or its config."
            ),
            inputSchema={
                "type": "object",
                "required": ["pod_name"],
                "properties": {
                    "pod_name": {"type": "string", "description": "Exact pod name"},
                    "namespace": {"type": "string", "default": "meridian"},
                    "tail_lines": {
                        "type": "integer",
                        "description": "Number of log lines to return (1–500)",
                        "default": 50,
                        "minimum": 1,
                        "maximum": 500,
                    },
                    "container": {
                        "type": "string",
                        "description": "Container name (required for multi-container pods)",
                    },
                },
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="get_active_alerts",
            description=(
                "Query Alertmanager for currently firing alerts. "
                "Returns alert name, severity, state, and annotations."
            ),
            inputSchema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="get_node_metrics",
            description=(
                "Query Prometheus for current node CPU usage, memory usage, "
                "and disk usage percentages."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "lookback_minutes": {
                        "type": "integer",
                        "description": "Prometheus query window in minutes (1–60)",
                        "default": 5,
                        "minimum": 1,
                        "maximum": 60,
                    }
                },
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="get_db_connectivity",
            description=(
                "Test TCP reachability of the PostgreSQL service. "
                "No credentials are used — this is a pure connection test."
            ),
            inputSchema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="get_deployment_history",
            description=(
                "Fetch recent GitHub Actions workflow run results for the Meridian repository. "
                "Shows run status, conclusion, branch, and commit SHA."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "workflow_file": {
                        "type": "string",
                        "description": "Workflow filename (e.g. 'deploy.yml')",
                        "default": "deploy.yml",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Number of recent runs to return (1–20)",
                        "default": 5,
                        "minimum": 1,
                        "maximum": 20,
                    },
                },
                "additionalProperties": False,
            },
        ),
    ]


@server.call_tool()
async def call_tool(
    name: str, arguments: dict[str, Any]
) -> list[types.TextContent]:
    """
    Dispatch an MCP tool call to the appropriate handler.

    Every call is:
      1. Validated via Pydantic (in each tool's input model)
      2. Audit-logged before and after execution
      3. Error-wrapped so the MCP client receives a friendly error, not a traceback
    """
    logger.info("Tool call received", extra={"tool": name, "arguments": arguments})

    try:
        result = await _dispatch(name, arguments)
        return [types.TextContent(type="text", text=str(result))]
    except ValueError as exc:
        # Pydantic validation errors — user-facing, safe to expose
        logger.warning("Tool input validation failed", extra={"tool": name, "error": str(exc)})
        return [types.TextContent(type="text", text=f"Input validation error: {exc}")]
    except Exception as exc:
        # Unexpected errors — log full detail, return sanitised message
        logger.exception("Tool call failed", extra={"tool": name})
        return [
            types.TextContent(
                type="text",
                text=f"Tool '{name}' encountered an error: {type(exc).__name__}: {exc}",
            )
        ]


async def _dispatch(name: str, arguments: dict[str, Any]) -> Any:
    """Route tool name to implementation with audit logging."""

    if name == "get_pod_status":
        inputs = PodStatusInput(**arguments)
        with audit_tool_call(audit, name, arguments):
            return await get_pod_status(inputs)

    elif name == "get_recent_logs":
        inputs = PodLogsInput(**arguments)
        with audit_tool_call(audit, name, arguments):
            return await get_recent_logs(inputs)

    elif name == "get_active_alerts":
        with audit_tool_call(audit, name, arguments):
            return await get_active_alerts(alertmanager_url=settings.alertmanager_url)

    elif name == "get_node_metrics":
        inputs = NodeMetricsInput(**arguments)
        with audit_tool_call(audit, name, arguments):
            return await get_node_metrics(
                inputs=inputs,
                prometheus_url=settings.prometheus_url,
            )

    elif name == "get_db_connectivity":
        with audit_tool_call(audit, name, arguments):
            return await get_db_connectivity(
                db_host=settings.db_host,
                db_port=settings.db_port,
            )

    elif name == "get_deployment_history":
        inputs = DeploymentHistoryInput(**arguments)
        with audit_tool_call(audit, name, arguments):
            return await get_deployment_history(
                inputs=inputs,
                github_token=settings.github_token,
                repo_owner=settings.github_repo_owner,
                repo_name=settings.github_repo_name,
            )

    else:
        raise ValueError(f"Unknown tool: '{name}'")


# ── Entry Point ───────────────────────────────────────────────────────────────

async def main() -> None:
    """Start the MCP server over stdio transport."""
    logger.info(
        "Meridian MCP agent starting",
        extra={"prometheus": settings.prometheus_url, "alertmanager": settings.alertmanager_url},
    )

    async with stdio_transport.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="meridian-mcp",
                server_version="1.0.0",
                capabilities=server.get_capabilities(
                    notification_options=None,
                    experimental_capabilities={},
                ),
            ),
        )


if __name__ == "__main__":
    asyncio.run(main())
