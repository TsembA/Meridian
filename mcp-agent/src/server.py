"""
server.py — MCP server for the Meridian diagnostic agent.

Uses FastMCP (mcp 1.x high-level API) with SSE transport so the pod runs a
real HTTP server on port 8080 inside the cluster — liveness probes pass and
AI clients can connect via kubectl port-forward.

To connect Claude Code (claude CLI) to this server:
  kubectl port-forward svc/meridian-mcp 8080:8080 -n meridian
  claude mcp add meridian --transport sse http://localhost:8080/sse

Security constraints preserved:
  - All tool inputs still go through Pydantic models in tools.py
  - No shell=True anywhere
  - Audit logger records every tool call
  - Server is ClusterIP-only — never exposed to the public internet
"""

import logging

from mcp.server.fastmcp import FastMCP

from .audit import AuditLogger, audit_tool_call
from .config import get_mcp_settings
from .logger import configure_logging
from .tools import (
    DeploymentHistoryInput,
    NodeMetricsInput,
    PodLogsInput,
    PodStatusInput,
    get_active_alerts as _get_active_alerts,
    get_db_connectivity as _get_db_connectivity,
    get_deployment_history as _get_deployment_history,
    get_node_metrics as _get_node_metrics,
    get_pod_status as _get_pod_status,
    get_recent_logs as _get_recent_logs,
)

configure_logging(level=get_mcp_settings().log_level)
logger = logging.getLogger(__name__)
settings = get_mcp_settings()
audit = AuditLogger(log_path=settings.audit_log_path)

mcp = FastMCP("meridian-mcp", host=settings.mcp_host, port=settings.mcp_port)


@mcp.tool()
async def get_pod_status(namespace: str = "meridian") -> str:
    """
    List all pods in a Kubernetes namespace with their phase, readiness, and
    restart counts. Read-only — no mutations performed.
    """
    inputs = PodStatusInput(namespace=namespace)
    with audit_tool_call(audit, "get_pod_status", {"namespace": namespace}):
        result = await _get_pod_status(inputs)
    return str(result)


@mcp.tool()
async def get_recent_logs(
    pod_name: str,
    namespace: str = "meridian",
    tail_lines: int = 50,
    container: str = "",
) -> str:
    """
    Retrieve the last N log lines from a specific pod. Read-only — no
    modifications to the pod or its config. tail_lines must be between 1–500.
    """
    args: dict = {"pod_name": pod_name, "namespace": namespace, "tail_lines": tail_lines}
    if container:
        args["container"] = container
    inputs = PodLogsInput(**args)
    with audit_tool_call(audit, "get_recent_logs", args):
        result = await _get_recent_logs(inputs)
    return str(result)


@mcp.tool()
async def get_active_alerts() -> str:
    """
    Query Alertmanager for currently firing alerts. Returns alert name,
    severity, state, and annotations for each active alert.
    """
    _auth = (settings.grafana_cloud_instance_id, settings.grafana_cloud_api_key) if settings.grafana_cloud_instance_id else None
    with audit_tool_call(audit, "get_active_alerts", {}):
        result = await _get_active_alerts(alertmanager_url=settings.alertmanager_url, auth=_auth)
    return str(result)


@mcp.tool()
async def get_node_metrics(lookback_minutes: int = 5) -> str:
    """
    Query Prometheus for current node CPU usage, memory usage, and disk usage
    percentages. lookback_minutes sets the query window (1–60).
    """
    inputs = NodeMetricsInput(lookback_minutes=lookback_minutes)
    _auth = (settings.grafana_cloud_instance_id, settings.grafana_cloud_api_key) if settings.grafana_cloud_instance_id else None
    with audit_tool_call(audit, "get_node_metrics", {"lookback_minutes": lookback_minutes}):
        result = await _get_node_metrics(inputs=inputs, prometheus_url=settings.prometheus_url, auth=_auth)
    return str(result)


@mcp.tool()
async def get_db_connectivity() -> str:
    """
    Test TCP reachability of the PostgreSQL service. No credentials are used —
    this is a pure connection test (TCP handshake only).
    """
    with audit_tool_call(audit, "get_db_connectivity", {}):
        result = await _get_db_connectivity(db_host=settings.db_host, db_port=settings.db_port)
    return str(result)


@mcp.tool()
async def get_deployment_history(workflow_file: str = "deploy.yml", limit: int = 5) -> str:
    """
    Fetch recent GitHub Actions workflow run results for the Meridian repository.
    Shows run status, conclusion, branch, and commit SHA. limit must be 1–20.
    """
    inputs = DeploymentHistoryInput(workflow_file=workflow_file, limit=limit)
    with audit_tool_call(audit, "get_deployment_history", {"workflow_file": workflow_file, "limit": limit}):
        result = await _get_deployment_history(
            inputs=inputs,
            github_token=settings.github_token,
            repo_owner=settings.github_repo_owner,
            repo_name=settings.github_repo_name,
        )
    return str(result)


if __name__ == "__main__":
    logger.info(
        "Meridian MCP agent starting",
        extra={
            "transport": "sse",
            "host": settings.mcp_host,
            "port": settings.mcp_port,
            "prometheus": settings.prometheus_url,
        },
    )
    mcp.run(transport="sse")
