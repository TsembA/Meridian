"""
tools.py — MCP tool implementations for the Meridian diagnostic agent.

All tools are READ-ONLY. No tool can create, update, delete, or patch any resource.
Inputs are validated with Pydantic before any external call is made.
shell=True is NEVER used — all subprocess calls are forbidden; we use HTTP clients
and the kubernetes Python client instead.

Tools:
    get_pod_status         — List pods and their readiness/phase in a namespace
    get_recent_logs        — Retrieve the last N lines from a named pod
    get_active_alerts      — Query Alertmanager for currently firing alerts
    get_node_metrics       — Query Prometheus for node CPU and memory metrics
    get_db_connectivity    — TCP reachability check to PostgreSQL (no credentials used)
    get_deployment_history — Fetch recent GitHub Actions workflow runs via API
"""

import asyncio
import logging
import socket
from typing import Any, Optional

import httpx
from kubernetes import client as k8s_client, config as k8s_config
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

# ── Input Models (Pydantic validation — no raw string execution) ──────────────

class PodStatusInput(BaseModel):
    """Inputs for get_pod_status."""
    namespace: str = Field(
        default="meridian",
        min_length=1,
        max_length=63,
        pattern=r"^[a-z0-9][a-z0-9\-]*[a-z0-9]$",
        description="Kubernetes namespace to inspect",
    )


class PodLogsInput(BaseModel):
    """Inputs for get_recent_logs."""
    pod_name: str = Field(
        ...,
        min_length=1,
        max_length=253,
        # RFC 1123 DNS subdomain — valid k8s pod name format
        pattern=r"^[a-z0-9][a-z0-9\-\.]*[a-z0-9]$",
        description="Name of the pod to retrieve logs from",
    )
    namespace: str = Field(
        default="meridian",
        min_length=1,
        max_length=63,
        pattern=r"^[a-z0-9][a-z0-9\-]*[a-z0-9]$",
    )
    tail_lines: int = Field(
        default=50,
        ge=1,
        le=500,
        description="Number of log lines to return (1–500)",
    )
    container: Optional[str] = Field(
        default=None,
        max_length=63,
        description="Container name (required for multi-container pods)",
    )


class NodeMetricsInput(BaseModel):
    """Inputs for get_node_metrics."""
    lookback_minutes: int = Field(
        default=5,
        ge=1,
        le=60,
        description="Query window in minutes for Prometheus metrics (1–60)",
    )


class DeploymentHistoryInput(BaseModel):
    """Inputs for get_deployment_history."""
    workflow_file: str = Field(
        default="deploy.yml",
        min_length=1,
        max_length=100,
        pattern=r"^[\w\-\.]+\.yml$",
        description="Workflow filename to query (e.g. 'deploy.yml')",
    )
    limit: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Maximum number of recent runs to return",
    )


# ── k8s Client initialisation ─────────────────────────────────────────────────

def _get_k8s_core_client() -> k8s_client.CoreV1Api:
    """
    Initialise the k8s client from in-cluster config (service account token).
    Falls back to KUBECONFIG for local development.
    """
    try:
        k8s_config.load_incluster_config()
    except k8s_config.ConfigException:
        # Fallback for local dev — uses ~/.kube/config
        k8s_config.load_kube_config()
    return k8s_client.CoreV1Api()


# ── Tool Implementations ───────────────────────────────────────────────────────

async def get_pod_status(inputs: PodStatusInput) -> dict[str, Any]:
    """
    List all pods in `namespace` with their phase and readiness conditions.

    Returns a dict with 'pods' key containing a list of pod summaries.
    Raises ValueError if the namespace is inaccessible.
    """
    # Run the synchronous k8s client call in a thread pool to not block the event loop
    core_v1 = await asyncio.to_thread(_get_k8s_core_client)

    def _fetch() -> k8s_client.V1PodList:
        return core_v1.list_namespaced_pod(namespace=inputs.namespace)

    pod_list: k8s_client.V1PodList = await asyncio.to_thread(_fetch)

    pods = []
    for pod in pod_list.items:
        ready = False
        if pod.status and pod.status.conditions:
            ready = any(
                c.type == "Ready" and c.status == "True"
                for c in pod.status.conditions
            )
        pods.append(
            {
                "name": pod.metadata.name,
                "namespace": pod.metadata.namespace,
                "phase": pod.status.phase if pod.status else "Unknown",
                "ready": ready,
                "restart_count": sum(
                    cs.restart_count or 0
                    for cs in (pod.status.container_statuses or [])
                ),
                "node": pod.spec.node_name if pod.spec else None,
            }
        )

    logger.info("Fetched pod status", extra={"namespace": inputs.namespace, "count": len(pods)})
    return {"namespace": inputs.namespace, "pods": pods, "total": len(pods)}


async def get_recent_logs(inputs: PodLogsInput) -> dict[str, Any]:
    """
    Retrieve the last `tail_lines` lines from a pod's log.

    Returns a dict with 'lines' containing the log text split into a list.
    The k8s API enforces the line limit — no string manipulation on our side.
    """
    core_v1 = await asyncio.to_thread(_get_k8s_core_client)

    def _fetch() -> str:
        kwargs: dict[str, Any] = {
            "name": inputs.pod_name,
            "namespace": inputs.namespace,
            "tail_lines": inputs.tail_lines,
            "timestamps": True,
        }
        if inputs.container:
            kwargs["container"] = inputs.container
        return core_v1.read_namespaced_pod_log(**kwargs)

    log_text: str = await asyncio.to_thread(_fetch)
    lines = log_text.splitlines()

    logger.info(
        "Fetched pod logs",
        extra={
            "pod": inputs.pod_name,
            "namespace": inputs.namespace,
            "lines_returned": len(lines),
        },
    )
    return {
        "pod": inputs.pod_name,
        "namespace": inputs.namespace,
        "container": inputs.container,
        "tail_lines_requested": inputs.tail_lines,
        "lines_returned": len(lines),
        "logs": lines,
    }


async def get_active_alerts(
    alertmanager_url: str,
    auth: tuple[str, str] | None = None,
) -> dict[str, Any]:
    """
    Query Alertmanager's /api/v2/alerts endpoint for currently firing alerts.

    Only returns alerts that are active (not silenced or inhibited).
    Uses httpx with a 10-second timeout — never blocks indefinitely.
    auth is (username, password) for basic auth (Grafana Cloud Mimir alertmanager).
    """
    url = f"{alertmanager_url.rstrip('/')}/api/v2/alerts"

    async with httpx.AsyncClient(timeout=10.0, auth=auth) as client:
        response = await client.get(url, params={"active": "true", "silenced": "false"})
        response.raise_for_status()
        raw_alerts: list[dict] = response.json()

    # Extract the fields most useful for diagnosis — not the full verbose payload
    alerts = [
        {
            "name": a.get("labels", {}).get("alertname", "unknown"),
            "severity": a.get("labels", {}).get("severity", "unknown"),
            "namespace": a.get("labels", {}).get("namespace"),
            "state": a.get("status", {}).get("state"),
            "started_at": a.get("startsAt"),
            "summary": a.get("annotations", {}).get("summary"),
            "description": a.get("annotations", {}).get("description"),
        }
        for a in raw_alerts
    ]

    logger.info("Fetched active alerts", extra={"count": len(alerts)})
    return {"active_alert_count": len(alerts), "alerts": alerts}


async def get_node_metrics(
    inputs: NodeMetricsInput,
    prometheus_url: str,
    auth: tuple[str, str] | None = None,
) -> dict[str, Any]:
    """
    Query Prometheus for node CPU and memory metrics over the last N minutes.

    Uses instant queries (not range queries) to return the current state.
    CPU is expressed as a percentage; memory as used/total bytes and percentage.
    """
    window = f"{inputs.lookback_minutes}m"
    queries = {
        "cpu_usage_percent": (
            f"100 - (avg(rate(node_cpu_seconds_total{{mode='idle'}}[{window}])) * 100)"
        ),
        "memory_used_bytes": "node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes",
        "memory_total_bytes": "node_memory_MemTotal_bytes",
        "memory_used_percent": (
            "(1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) * 100"
        ),
        "disk_used_percent": (
            "(1 - (node_filesystem_avail_bytes{fstype!~'tmpfs|overlay',mountpoint='/'}"
            " / node_filesystem_size_bytes{fstype!~'tmpfs|overlay',mountpoint='/'})) * 100"
        ),
    }

    results: dict[str, Any] = {"lookback_minutes": inputs.lookback_minutes, "metrics": {}}

    base = f"{prometheus_url.rstrip('/')}/api/v1/query"

    async with httpx.AsyncClient(timeout=10.0, auth=auth) as client:
        for metric_name, promql in queries.items():
            resp = await client.get(base, params={"query": promql})
            resp.raise_for_status()
            data = resp.json()

            # Extract scalar value from instant query result
            result_data = data.get("data", {}).get("result", [])
            value = float(result_data[0]["value"][1]) if result_data else None
            results["metrics"][metric_name] = round(value, 2) if value is not None else None

    logger.info("Fetched node metrics", extra={"window": window})
    return results


async def get_db_connectivity(db_host: str, db_port: int = 5432) -> dict[str, Any]:
    """
    Test TCP reachability of the PostgreSQL service.

    This is a pure connectivity check — no credentials are used or exposed.
    Returns reachable=True if the TCP handshake succeeds within 5 seconds.
    """
    reachable = False
    error_message: Optional[str] = None

    try:
        # asyncio open_connection is non-blocking and doesn't execute any SQL
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(db_host, db_port),
            timeout=5.0,
        )
        reachable = True
        writer.close()
        await writer.wait_closed()
    except asyncio.TimeoutError:
        error_message = f"TCP connection to {db_host}:{db_port} timed out after 5 seconds"
    except OSError as exc:
        error_message = f"TCP connection to {db_host}:{db_port} failed: {exc}"

    logger.info(
        "DB connectivity check",
        extra={"host": db_host, "port": db_port, "reachable": reachable},
    )
    return {
        "host": db_host,
        "port": db_port,
        "reachable": reachable,
        "error": error_message,
        # Explicitly note no credentials are used — important for audit trail
        "note": "TCP-only check — no authentication or SQL executed",
    }


async def get_deployment_history(
    inputs: DeploymentHistoryInput,
    github_token: str,
    repo_owner: str,
    repo_name: str,
) -> dict[str, Any]:
    """
    Fetch recent GitHub Actions workflow runs for the specified workflow file.

    Uses the GitHub REST API with a read-only PAT (repo:read scope).
    Returns run status, conclusion, branch, and commit SHA for each run.
    """
    if not github_token:
        return {"error": "GitHub token not configured — set /meridian/github/token in SSM"}

    url = (
        f"https://api.github.com/repos/{repo_owner}/{repo_name}"
        f"/actions/workflows/{inputs.workflow_file}/runs"
    )

    headers = {
        "Authorization": f"Bearer {github_token}",
        "Accept": "application/vnd.github.v3+json",
        # Identify ourselves to GitHub for rate limit attribution
        "X-GitHub-Api-Version": "2022-11-28",
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(url, headers=headers, params={"per_page": inputs.limit})
        response.raise_for_status()
        data = response.json()

    runs = [
        {
            "run_id": r["id"],
            "status": r["status"],           # queued / in_progress / completed
            "conclusion": r["conclusion"],   # success / failure / cancelled / null
            "branch": r["head_branch"],
            "commit_sha": r["head_sha"][:8] if r.get("head_sha") else None,
            "trigger": r["event"],
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
            "url": r["html_url"],
        }
        for r in data.get("workflow_runs", [])
    ]

    logger.info(
        "Fetched deployment history",
        extra={"workflow": inputs.workflow_file, "runs_returned": len(runs)},
    )
    return {
        "workflow": inputs.workflow_file,
        "repository": f"{repo_owner}/{repo_name}",
        "runs": runs,
        "total_count": data.get("total_count", len(runs)),
    }
