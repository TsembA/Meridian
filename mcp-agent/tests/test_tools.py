"""
test_tools.py — Unit tests for the Meridian MCP agent tools.

All k8s API calls, HTTP requests, and AWS calls are mocked so tests run
without a live cluster, Prometheus, Alertmanager, or GitHub credentials.

Run with: pytest mcp-agent/tests/ -v --asyncio-mode=auto
"""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.tools import (
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


# ── get_pod_status ────────────────────────────────────────────────────────────

class TestGetPodStatus:
    @pytest.mark.asyncio
    async def test_returns_pod_list(self) -> None:
        """get_pod_status returns a dict with 'pods' key."""
        mock_pod = MagicMock()
        mock_pod.metadata.name = "meridian-app-abc123"
        mock_pod.metadata.namespace = "meridian"
        mock_pod.status.phase = "Running"
        mock_pod.status.conditions = [
            MagicMock(type="Ready", status="True")
        ]
        mock_pod.status.container_statuses = [MagicMock(restart_count=0)]
        mock_pod.spec.node_name = "k3s-node"

        mock_pod_list = MagicMock()
        mock_pod_list.items = [mock_pod]

        mock_core_v1 = MagicMock()
        mock_core_v1.list_namespaced_pod.return_value = mock_pod_list

        with patch("src.tools._get_k8s_core_client", return_value=mock_core_v1):
            with patch("asyncio.to_thread", side_effect=lambda f, *args: f(*args) if callable(f) else asyncio.coroutine(lambda: f)()):
                # Use a simpler approach: patch asyncio.to_thread properly
                pass

        # Approach: patch the k8s config and client directly
        with patch("src.tools.k8s_config") as mock_cfg:
            with patch("src.tools.k8s_client") as mock_k8s:
                mock_core = MagicMock()
                mock_core.list_namespaced_pod.return_value = mock_pod_list
                mock_k8s.CoreV1Api.return_value = mock_core
                mock_cfg.load_incluster_config = MagicMock()

                result = await get_pod_status(PodStatusInput(namespace="meridian"))

        assert "pods" in result
        assert result["namespace"] == "meridian"
        assert isinstance(result["total"], int)

    def test_input_validation_invalid_namespace(self) -> None:
        """PodStatusInput rejects namespaces with uppercase letters."""
        with pytest.raises(Exception):  # pydantic ValidationError
            PodStatusInput(namespace="INVALID")

    def test_input_validation_namespace_too_long(self) -> None:
        """PodStatusInput rejects namespaces longer than 63 chars."""
        with pytest.raises(Exception):
            PodStatusInput(namespace="a" * 64)


# ── get_recent_logs ───────────────────────────────────────────────────────────

class TestGetRecentLogs:
    def test_input_validation_tail_lines_max(self) -> None:
        """PodLogsInput clamps tail_lines to 500 max."""
        with pytest.raises(Exception):
            PodLogsInput(pod_name="my-pod", tail_lines=501)

    def test_input_validation_tail_lines_min(self) -> None:
        """PodLogsInput rejects tail_lines < 1."""
        with pytest.raises(Exception):
            PodLogsInput(pod_name="my-pod", tail_lines=0)

    def test_input_validation_pod_name_pattern(self) -> None:
        """PodLogsInput rejects pod names with uppercase letters or invalid chars."""
        with pytest.raises(Exception):
            PodLogsInput(pod_name="INVALID_POD")

    @pytest.mark.asyncio
    async def test_returns_log_lines(self) -> None:
        """get_recent_logs returns a dict with 'logs' as a list of strings."""
        log_content = "2024-01-01T00:00:00Z INFO app started\n2024-01-01T00:00:01Z INFO ready"

        mock_pod_list = MagicMock()
        mock_pod_list.items = []

        with patch("src.tools.k8s_config") as mock_cfg:
            with patch("src.tools.k8s_client") as mock_k8s:
                mock_core = MagicMock()
                mock_core.read_namespaced_pod_log.return_value = log_content
                mock_k8s.CoreV1Api.return_value = mock_core
                mock_cfg.load_incluster_config = MagicMock()

                result = await get_recent_logs(
                    PodLogsInput(pod_name="meridian-app-abc123", namespace="meridian", tail_lines=50)
                )

        assert "logs" in result
        assert isinstance(result["logs"], list)
        assert result["lines_returned"] == 2


# ── get_active_alerts ─────────────────────────────────────────────────────────

class TestGetActiveAlerts:
    @pytest.mark.asyncio
    async def test_returns_alerts_list(self) -> None:
        """get_active_alerts returns a dict with 'alerts' list."""
        mock_response_data = [
            {
                "labels": {"alertname": "MeridianPodNotReady", "severity": "critical", "namespace": "meridian"},
                "annotations": {"summary": "Pod not ready", "description": "Pod foo is down"},
                "status": {"state": "active"},
                "startsAt": "2024-01-01T00:00:00Z",
            }
        ]

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_response = MagicMock()
            mock_response.json.return_value = mock_response_data
            mock_response.raise_for_status = MagicMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            result = await get_active_alerts("http://alertmanager:9093")

        assert "alerts" in result
        assert result["active_alert_count"] == 1
        assert result["alerts"][0]["name"] == "MeridianPodNotReady"
        assert result["alerts"][0]["severity"] == "critical"

    @pytest.mark.asyncio
    async def test_empty_alerts_returns_zero_count(self) -> None:
        """get_active_alerts returns count=0 when no alerts are firing."""
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_response = MagicMock()
            mock_response.json.return_value = []
            mock_response.raise_for_status = MagicMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            result = await get_active_alerts("http://alertmanager:9093")

        assert result["active_alert_count"] == 0
        assert result["alerts"] == []


# ── get_node_metrics ──────────────────────────────────────────────────────────

class TestGetNodeMetrics:
    @pytest.mark.asyncio
    async def test_returns_metric_values(self) -> None:
        """get_node_metrics returns a dict with numeric metric values."""
        def make_prom_response(value: float) -> MagicMock:
            mock = MagicMock()
            mock.json.return_value = {
                "data": {"result": [{"value": ["timestamp", str(value)]}]}
            }
            mock.raise_for_status = MagicMock()
            return mock

        responses = [
            make_prom_response(42.5),   # cpu_usage_percent
            make_prom_response(800 * 1024 * 1024),  # memory_used_bytes
            make_prom_response(1024 * 1024 * 1024), # memory_total_bytes
            make_prom_response(78.1),   # memory_used_percent
            make_prom_response(55.2),   # disk_used_percent
        ]

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(side_effect=responses)
            mock_client_cls.return_value = mock_client

            result = await get_node_metrics(
                NodeMetricsInput(lookback_minutes=5),
                prometheus_url="http://prometheus:9090",
            )

        assert "metrics" in result
        assert result["metrics"]["cpu_usage_percent"] == 42.5
        assert result["metrics"]["memory_used_percent"] == 78.1

    def test_input_lookback_out_of_range(self) -> None:
        """NodeMetricsInput rejects lookback_minutes > 60."""
        with pytest.raises(Exception):
            NodeMetricsInput(lookback_minutes=61)


# ── get_db_connectivity ───────────────────────────────────────────────────────

class TestGetDbConnectivity:
    @pytest.mark.asyncio
    async def test_reachable_returns_true(self) -> None:
        """get_db_connectivity returns reachable=True when TCP handshake succeeds."""
        mock_reader = AsyncMock()
        mock_writer = AsyncMock()
        mock_writer.wait_closed = AsyncMock()

        with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
            with patch("asyncio.wait_for", new_callable=AsyncMock) as mock_wait:
                mock_wait.return_value = (mock_reader, mock_writer)

                result = await get_db_connectivity("postgresql.meridian.svc.cluster.local", 5432)

        assert result["reachable"] is True
        assert result["error"] is None
        assert "no authentication" in result["note"].lower()

    @pytest.mark.asyncio
    async def test_unreachable_returns_false(self) -> None:
        """get_db_connectivity returns reachable=False on connection failure."""
        with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError()):
            result = await get_db_connectivity("unreachable-host", 5432)

        assert result["reachable"] is False
        assert result["error"] is not None
        assert "timed out" in result["error"].lower()


# ── get_deployment_history ────────────────────────────────────────────────────

class TestGetDeploymentHistory:
    @pytest.mark.asyncio
    async def test_returns_runs(self) -> None:
        """get_deployment_history returns a list of workflow runs."""
        mock_api_response = {
            "total_count": 2,
            "workflow_runs": [
                {
                    "id": 111,
                    "status": "completed",
                    "conclusion": "success",
                    "head_branch": "main",
                    "head_sha": "abc1234567890",
                    "event": "push",
                    "created_at": "2024-01-01T00:00:00Z",
                    "updated_at": "2024-01-01T00:05:00Z",
                    "html_url": "https://github.com/org/repo/actions/runs/111",
                }
            ],
        }

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_response = MagicMock()
            mock_response.json.return_value = mock_api_response
            mock_response.raise_for_status = MagicMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            result = await get_deployment_history(
                inputs=DeploymentHistoryInput(workflow_file="deploy.yml", limit=5),
                github_token="ghp_testtoken",
                repo_owner="myorg",
                repo_name="meridian",
            )

        assert "runs" in result
        assert result["runs"][0]["conclusion"] == "success"
        assert result["runs"][0]["commit_sha"] == "abc12345"  # truncated to 8

    @pytest.mark.asyncio
    async def test_no_token_returns_error(self) -> None:
        """get_deployment_history returns an error dict when no token is configured."""
        result = await get_deployment_history(
            inputs=DeploymentHistoryInput(),
            github_token="",
            repo_owner="org",
            repo_name="repo",
        )
        assert "error" in result

    def test_input_workflow_file_pattern(self) -> None:
        """DeploymentHistoryInput rejects workflow filenames with path traversal."""
        with pytest.raises(Exception):
            DeploymentHistoryInput(workflow_file="../evil.yml")

    def test_input_limit_max(self) -> None:
        """DeploymentHistoryInput rejects limit > 20."""
        with pytest.raises(Exception):
            DeploymentHistoryInput(limit=21)


# ── Audit Logger ──────────────────────────────────────────────────────────────

class TestAuditLogger:
    def test_sanitise_redacts_sensitive_keys(self, tmp_path: Any) -> None:
        """AuditLogger._sanitise redacts keys containing 'password' or 'token'."""
        from src.audit import AuditLogger

        audit = AuditLogger(str(tmp_path / "audit.jsonl"))
        result = audit._sanitise({  # type: ignore[attr-defined]
            "namespace": "meridian",
            "password": "supersecret",
            "github_token": "ghp_abc",
            "tail_lines": 50,
        })

        assert result["namespace"] == "meridian"
        assert result["password"] == "***REDACTED***"
        assert result["github_token"] == "***REDACTED***"
        assert result["tail_lines"] == 50

    def test_audit_record_writes_to_file(self, tmp_path: Any) -> None:
        """AuditLogger.record appends a JSON line to the audit file."""
        import json
        from src.audit import AuditLogger

        log_path = tmp_path / "audit.jsonl"
        audit = AuditLogger(str(log_path))
        audit.record(
            tool="get_pod_status",
            inputs={"namespace": "meridian"},
            outcome="success",
            duration_ms=42.0,
        )

        lines = log_path.read_text().strip().splitlines()
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["tool"] == "get_pod_status"
        assert entry["outcome"] == "success"
        assert entry["event"] == "mcp_tool_invoked"
