"""Tests for dashboard API server (server.py).

Tests HTTP endpoints with a real running server on localhost.
Uses mocked SandboxController for sandbox operations.
Follows boundary pattern: happy path, auth, errors.
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

if TYPE_CHECKING:
    from pathlib import Path

import pytest

from social_agent.control import HealthCheck, HealthStatus
from social_agent.cost import CostTracker
from social_agent.server import DashboardServer


def _make_request(
    url: str,
    *,
    method: str = "GET",
    data: dict | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict]:
    """Make an HTTP request and return (status_code, json_body)."""
    import urllib.error
    import urllib.request

    req = urllib.request.Request(url, method=method)
    if headers:
        for key, value in headers.items():
            req.add_header(key, value)
    if data is not None:
        req.add_header("Content-Type", "application/json")
        req.data = json.dumps(data).encode("utf-8")

    try:
        with urllib.request.urlopen(req) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return resp.status, body
    except urllib.error.HTTPError as e:
        body = json.loads(e.read().decode("utf-8"))
        return e.code, body


# --- Fixtures ---


@pytest.fixture
def mock_controller() -> MagicMock:
    """Mock SandboxController."""
    ctrl = MagicMock()
    ctrl.check_health.return_value = HealthCheck(
        sandbox_id="sbx_test",
        status=HealthStatus.HEALTHY,
        last_heartbeat="2026-02-16T12:00:00Z",
        current_action="READ_FEED",
        seconds_since_heartbeat=5.0,
    )
    ctrl.read_state.return_value = {
        "cycle_count": 42,
        "posts_today": 3,
    }
    ctrl.read_activity.return_value = [
        {"action": "READ_FEED", "success": True, "timestamp": "2026-02-16T12:00:00Z"},
        {"action": "REPLY", "success": True, "timestamp": "2026-02-16T12:01:00Z"},
    ]
    ctrl.kill.return_value = True
    return ctrl


@pytest.fixture
def tmp_state(tmp_path: Path) -> Path:
    """Create temporary state.json."""
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({
        "cycle_count": 42,
        "posts_today": 3,
        "replies_today": 7,
        "consecutive_failures": 0,
        "last_reset_date": "2026-02-16",
    }))
    return state_path


@pytest.fixture
def tmp_activity(tmp_path: Path) -> Path:
    """Create temporary activity.jsonl."""
    log_path = tmp_path / "logs" / "activity.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    records = [
        {
            "timestamp": "2026-02-16T12:00:00Z",
            "cycle": 1,
            "action": "READ_FEED",
            "success": True,
        },
        {
            "timestamp": "2026-02-16T12:01:00Z",
            "cycle": 2,
            "action": "REPLY",
            "success": True,
            "quality_score": 0.85,
        },
        {
            "timestamp": "2026-02-16T12:02:00Z",
            "cycle": 3,
            "action": "CREATE_POST",
            "success": False,
        },
    ]
    log_path.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    return log_path


@pytest.fixture
def server(
    mock_controller: MagicMock,
    tmp_state: Path,
    tmp_activity: Path,
    tmp_path: Path,
) -> DashboardServer:
    """Running dashboard server with mocked controller."""
    srv = DashboardServer(
        sandbox_id="sbx_test",
        controller=mock_controller,
        state_path=tmp_state,
        activity_log_path=tmp_activity,
        heartbeat_path=tmp_path / "heartbeat.json",
        dashboard_token="test-secret-token",
        port=0,  # Let OS pick a free port
    )
    srv.start()
    # Wait for server to be ready
    time.sleep(0.1)
    yield srv
    srv.stop()


def _base_url(srv: DashboardServer) -> str:
    """Get base URL for server using the public port property."""
    return f"http://127.0.0.1:{srv.port}"


# --- Status endpoint ---


class TestStatus:
    """Tests for GET /api/status."""

    def test_status_returns_health_and_state(
        self, server: DashboardServer
    ) -> None:
        """Status includes health and state info."""
        status, body = _make_request(f"{_base_url(server)}/api/status")
        assert status == 200
        assert body["sandbox_id"] == "sbx_test"
        assert body["health"]["status"] == "healthy"
        assert body["health"]["current_action"] == "READ_FEED"
        assert body["state"]["cycle_count"] == 42


# --- Activity endpoint ---


class TestActivity:
    """Tests for GET /api/activity."""

    def test_activity_returns_records(
        self, server: DashboardServer
    ) -> None:
        """Activity returns recent records."""
        status, body = _make_request(f"{_base_url(server)}/api/activity")
        assert status == 200
        assert body["count"] == 2
        assert len(body["records"]) == 2

    def test_activity_with_limit(
        self, server: DashboardServer, mock_controller: MagicMock
    ) -> None:
        """Activity respects limit parameter."""
        mock_controller.read_activity.return_value = [
            {"action": "READ_FEED", "success": True}
        ]
        status, _body = _make_request(
            f"{_base_url(server)}/api/activity?limit=1"
        )
        assert status == 200
        mock_controller.read_activity.assert_called_with(
            "sbx_test", last_n=1
        )

    def test_activity_invalid_limit(
        self, server: DashboardServer
    ) -> None:
        """Invalid limit falls back to default."""
        status, body = _make_request(
            f"{_base_url(server)}/api/activity?limit=abc"
        )
        assert status == 200
        assert body["limit"] == 50  # default


# --- Stats endpoint ---


class TestStats:
    """Tests for GET /api/stats."""

    def test_stats_returns_aggregates(
        self, server: DashboardServer
    ) -> None:
        """Stats returns aggregated data."""
        status, body = _make_request(f"{_base_url(server)}/api/stats")
        assert status == 200
        assert "total_actions" in body
        assert "success_rate" in body
        assert "dashboard" in body


# --- Heartbeat endpoint ---


class TestHeartbeat:
    """Tests for GET /api/heartbeat."""

    def test_heartbeat_returns_health(
        self, server: DashboardServer
    ) -> None:
        """Heartbeat returns health status."""
        status, body = _make_request(f"{_base_url(server)}/api/heartbeat")
        assert status == 200
        assert body["status"] == "healthy"
        assert body["sandbox_id"] == "sbx_test"
        assert body["current_action"] == "READ_FEED"


# --- Kill endpoint (admin) ---


class TestKill:
    """Tests for POST /api/kill."""

    def test_kill_with_valid_token(
        self, server: DashboardServer
    ) -> None:
        """Kill succeeds with valid admin token."""
        status, body = _make_request(
            f"{_base_url(server)}/api/kill",
            method="POST",
            data={},
            headers={"Authorization": "Bearer test-secret-token"},
        )
        assert status == 200
        assert body["killed"] is True
        assert body["sandbox_id"] == "sbx_test"

    def test_kill_without_token(
        self, server: DashboardServer
    ) -> None:
        """Kill rejected without token."""
        status, body = _make_request(
            f"{_base_url(server)}/api/kill",
            method="POST",
            data={},
        )
        assert status == 401
        assert "Unauthorized" in body["error"]

    def test_kill_with_wrong_token(
        self, server: DashboardServer
    ) -> None:
        """Kill rejected with wrong token."""
        status, _body = _make_request(
            f"{_base_url(server)}/api/kill",
            method="POST",
            data={},
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert status == 401


# --- Inject rule endpoint (admin) ---


class TestInjectRule:
    """Tests for POST /api/inject-rule."""

    def test_inject_rule_success(
        self, server: DashboardServer, mock_controller: MagicMock
    ) -> None:
        """Inject rule succeeds with valid token and rule."""
        status, body = _make_request(
            f"{_base_url(server)}/api/inject-rule",
            method="POST",
            data={"rule": "Never post after midnight"},
            headers={"Authorization": "Bearer test-secret-token"},
        )
        assert status == 200
        assert body["injected"] is True
        assert body["rule"] == "Never post after midnight"
        mock_controller.inject_rule.assert_called_once_with(
            "sbx_test", "Never post after midnight"
        )

    def test_inject_rule_missing_rule(
        self, server: DashboardServer
    ) -> None:
        """Inject rule fails without rule field."""
        status, body = _make_request(
            f"{_base_url(server)}/api/inject-rule",
            method="POST",
            data={},
            headers={"Authorization": "Bearer test-secret-token"},
        )
        assert status == 400
        assert "rule" in body["error"].lower()

    def test_inject_rule_no_auth(
        self, server: DashboardServer
    ) -> None:
        """Inject rule rejected without auth."""
        status, _body = _make_request(
            f"{_base_url(server)}/api/inject-rule",
            method="POST",
            data={"rule": "test"},
        )
        assert status == 401


# --- 404 handling ---


class TestNotFound:
    """Tests for unknown routes."""

    def test_unknown_get(self, server: DashboardServer) -> None:
        """Unknown GET returns 404."""
        status, body = _make_request(f"{_base_url(server)}/api/nonexistent")
        assert status == 404
        assert "Not found" in body["error"]

    def test_unknown_post(self, server: DashboardServer) -> None:
        """Unknown POST returns 404."""
        status, _body = _make_request(
            f"{_base_url(server)}/api/nonexistent",
            method="POST",
            data={},
            headers={"Authorization": "Bearer test-secret-token"},
        )
        assert status == 404


# --- CORS ---


class TestCORS:
    """Tests for CORS headers."""

    def test_cors_headers_on_get(self, server: DashboardServer) -> None:
        """GET responses include CORS headers."""
        import urllib.request

        req = urllib.request.Request(f"{_base_url(server)}/api/status")
        with urllib.request.urlopen(req) as resp:
            assert resp.headers.get("Access-Control-Allow-Origin") == "*"

    def test_options_preflight(self, server: DashboardServer) -> None:
        """OPTIONS returns 204 with CORS headers."""
        import urllib.request

        req = urllib.request.Request(
            f"{_base_url(server)}/api/status",
            method="OPTIONS",
        )
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 204
            assert resp.headers.get("Access-Control-Allow-Origin") == "*"
            assert "POST" in resp.headers.get("Access-Control-Allow-Methods", "")
            assert "Authorization" in resp.headers.get(
                "Access-Control-Allow-Headers", ""
            )


# --- Server lifecycle ---


class TestServerLifecycle:
    """Tests for server start/stop."""

    def test_context_manager(
        self,
        mock_controller: MagicMock,
        tmp_state: Path,
        tmp_activity: Path,
        tmp_path: Path,
    ) -> None:
        """Server works as context manager."""
        srv = DashboardServer(
            sandbox_id="sbx_test",
            controller=mock_controller,
            state_path=tmp_state,
            activity_log_path=tmp_activity,
            heartbeat_path=tmp_path / "heartbeat.json",
            port=0,
        )
        with srv:
            assert srv.is_running
        assert not srv.is_running

    def test_double_start(
        self,
        mock_controller: MagicMock,
        tmp_state: Path,
        tmp_activity: Path,
        tmp_path: Path,
    ) -> None:
        """Starting twice is idempotent."""
        srv = DashboardServer(
            sandbox_id="sbx_test",
            controller=mock_controller,
            state_path=tmp_state,
            activity_log_path=tmp_activity,
            heartbeat_path=tmp_path / "heartbeat.json",
            port=0,
        )
        srv.start()
        thread1 = srv._thread
        srv.start()  # Should not create a new thread
        assert srv._thread is thread1
        srv.stop()

    def test_stop_when_not_running(
        self,
        mock_controller: MagicMock,
        tmp_state: Path,
        tmp_activity: Path,
        tmp_path: Path,
    ) -> None:
        """Stopping when not running is a no-op."""
        srv = DashboardServer(
            sandbox_id="sbx_test",
            controller=mock_controller,
            state_path=tmp_state,
            activity_log_path=tmp_activity,
            heartbeat_path=tmp_path / "heartbeat.json",
            port=0,
        )
        srv.stop()  # Should not raise


# --- Admin auth edge cases ---


class TestAdminAuth:
    """Tests for admin authentication edge cases."""

    def test_no_dashboard_token_configured(
        self,
        mock_controller: MagicMock,
        tmp_state: Path,
        tmp_activity: Path,
        tmp_path: Path,
    ) -> None:
        """Admin endpoints return 403 when no token is configured."""
        srv = DashboardServer(
            sandbox_id="sbx_test",
            controller=mock_controller,
            state_path=tmp_state,
            activity_log_path=tmp_activity,
            heartbeat_path=tmp_path / "heartbeat.json",
            dashboard_token="",  # No token
            port=0,
        )
        with srv:
            time.sleep(0.1)
            status, body = _make_request(
                f"{_base_url(srv)}/api/kill",
                method="POST",
                data={},
                headers={"Authorization": "Bearer anything"},
            )
            assert status == 403
            assert "disabled" in body["error"].lower()


# --- Body size limit ---


class TestBodySizeLimit:
    """Tests for request body size enforcement."""

    def test_oversized_body_rejected(
        self, server: DashboardServer
    ) -> None:
        """Request body exceeding _MAX_BODY_SIZE returns 413."""
        import urllib.error
        import urllib.request

        # Build a payload larger than 64KB
        oversized = {"rule": "x" * 70000}
        raw = json.dumps(oversized).encode("utf-8")

        req = urllib.request.Request(
            f"{_base_url(server)}/api/inject-rule",
            method="POST",
        )
        req.add_header("Authorization", "Bearer test-secret-token")
        req.add_header("Content-Type", "application/json")
        req.data = raw

        try:
            with urllib.request.urlopen(req) as resp:
                status = resp.status
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            status = e.code
            body = json.loads(e.read().decode("utf-8"))

        assert status == 413
        assert "too large" in body["error"].lower()


# --- Port property ---


class TestPortProperty:
    """Tests for port property behavior."""

    def test_port_returns_actual_bound_port(
        self,
        mock_controller: MagicMock,
        tmp_state: Path,
        tmp_activity: Path,
        tmp_path: Path,
    ) -> None:
        """Port property returns OS-assigned port when running with port=0."""
        srv = DashboardServer(
            sandbox_id="sbx_test",
            controller=mock_controller,
            state_path=tmp_state,
            activity_log_path=tmp_activity,
            heartbeat_path=tmp_path / "heartbeat.json",
            port=0,
        )
        # Before start, returns configured port
        assert srv.port == 0

        srv.start()
        try:
            time.sleep(0.1)
            # After start, returns actual bound port (non-zero)
            assert srv.port > 0
            assert srv.port != 0
        finally:
            srv.stop()

        # After stop, returns configured port again
        assert srv.port == 0

    def test_port_returns_configured_when_explicit(
        self,
        mock_controller: MagicMock,
        tmp_state: Path,
        tmp_activity: Path,
        tmp_path: Path,
    ) -> None:
        """Port property returns configured port when not using port=0."""
        srv = DashboardServer(
            sandbox_id="sbx_test",
            controller=mock_controller,
            state_path=tmp_state,
            activity_log_path=tmp_activity,
            heartbeat_path=tmp_path / "heartbeat.json",
            port=9999,
        )
        assert srv.port == 9999


# --- Static file serving ---


def _fetch_raw(
    url: str,
    *,
    method: str = "GET",
) -> tuple[int, str, dict[str, str]]:
    """Fetch a URL and return (status_code, body_text, headers)."""
    import urllib.error
    import urllib.request

    req = urllib.request.Request(url, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            body = resp.read().decode("utf-8")
            headers = {k.lower(): v for k, v in resp.headers.items()}
            return resp.status, body, headers
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        headers = {k.lower(): v for k, v in e.headers.items()}
        return e.code, body, headers


class TestStaticFiles:
    """Tests for static file serving."""

    def test_index_served_at_root(self, server: DashboardServer) -> None:
        """GET / serves index.html."""
        status, body, headers = _fetch_raw(f"{_base_url(server)}/")
        assert status == 200
        assert "text/html" in headers.get("content-type", "")
        assert "Nathan" in body
        assert "<html" in body

    def test_css_served(self, server: DashboardServer) -> None:
        """GET /static/style.css serves the stylesheet."""
        status, body, headers = _fetch_raw(
            f"{_base_url(server)}/static/style.css"
        )
        assert status == 200
        assert "text/css" in headers.get("content-type", "")
        assert "--bg-primary" in body

    def test_js_served(self, server: DashboardServer) -> None:
        """GET /static/dashboard.js serves the JavaScript."""
        status, body, headers = _fetch_raw(
            f"{_base_url(server)}/static/dashboard.js"
        )
        assert status == 200
        # JS MIME type may vary
        content_type = headers.get("content-type", "")
        assert "javascript" in content_type or "text/" in content_type
        assert "Dashboard" in body

    def test_missing_static_returns_404(
        self, server: DashboardServer
    ) -> None:
        """Missing static file returns 404 JSON."""
        status, _body = _make_request(
            f"{_base_url(server)}/static/nonexistent.txt"
        )
        assert status == 404

    def test_path_traversal_blocked(
        self, server: DashboardServer
    ) -> None:
        """Path traversal attempts are rejected."""
        status, _body = _make_request(
            f"{_base_url(server)}/static/../server.py"
        )
        assert status == 404

    def test_cache_header_set(self, server: DashboardServer) -> None:
        """Static files have Cache-Control header."""
        status, _body, headers = _fetch_raw(
            f"{_base_url(server)}/static/style.css"
        )
        assert status == 200
        assert "max-age=" in headers.get("cache-control", "")


# --- Cost endpoint ---


class TestCost:
    """Tests for GET /api/cost."""

    def test_cost_without_tracker(
        self, server: DashboardServer
    ) -> None:
        """Cost returns zeroed data when no CostTracker is configured."""
        # Default server fixture has no cost_tracker
        status, body = _make_request(f"{_base_url(server)}/api/cost")
        assert status == 200
        assert body["configured"] is False
        assert body["total_cost_usd"] == 0.0
        assert body["budget_limit_usd"] == 0.0
        assert body["budget_remaining_usd"] == 0.0
        assert body["within_budget"] is True
        assert body["alert_triggered"] is False
        assert body["summary"] == {}

    def test_cost_with_tracker(
        self,
        mock_controller: MagicMock,
        tmp_state: Path,
        tmp_activity: Path,
        tmp_path: Path,
    ) -> None:
        """Cost returns real data from CostTracker."""
        tracker = CostTracker(
            cost_log_path=tmp_path / "cost.jsonl",
            budget_limit_usd=10.0,
            llm_cost_per_1m_tokens=0.4,
        )
        # Record some usage
        tracker.record_llm_call("test-ns", tokens_estimated=500_000)
        tracker.record_e2b_time(120.0)

        srv = DashboardServer(
            sandbox_id="sbx_test",
            controller=mock_controller,
            cost_tracker=tracker,
            state_path=tmp_state,
            activity_log_path=tmp_activity,
            heartbeat_path=tmp_path / "heartbeat.json",
            dashboard_token="test-secret-token",
            port=0,
        )
        with srv:
            time.sleep(0.1)
            status, body = _make_request(f"{_base_url(srv)}/api/cost")

        assert status == 200
        assert body["configured"] is True
        assert body["total_cost_usd"] > 0
        assert body["budget_limit_usd"] == 10.0
        assert body["budget_remaining_usd"] < 10.0
        assert body["within_budget"] is True
        assert body["alert_triggered"] is False
        assert "llm_calls" in body["summary"]
        assert "llm_tokens" in body["summary"]
        assert "e2b_seconds" in body["summary"]
        assert "budget_used_pct" in body["summary"]

    def test_cost_alert_triggered(
        self,
        mock_controller: MagicMock,
        tmp_state: Path,
        tmp_activity: Path,
        tmp_path: Path,
    ) -> None:
        """Cost shows alert when threshold exceeded."""
        tracker = CostTracker(
            cost_log_path=tmp_path / "cost.jsonl",
            budget_limit_usd=1.0,
            cost_alert_threshold=0.5,
            llm_cost_per_1m_tokens=0.4,
        )
        # Record enough to exceed 50% of $1 budget
        # 0.40/1M tokens × 2M tokens = $0.80 → 80% of budget
        tracker.record_llm_call("test-ns", tokens_estimated=2_000_000)

        srv = DashboardServer(
            sandbox_id="sbx_test",
            controller=mock_controller,
            cost_tracker=tracker,
            state_path=tmp_state,
            activity_log_path=tmp_activity,
            heartbeat_path=tmp_path / "heartbeat.json",
            port=0,
        )
        with srv:
            time.sleep(0.1)
            status, body = _make_request(f"{_base_url(srv)}/api/cost")

        assert status == 200
        assert body["alert_triggered"] is True
        assert body["within_budget"] is True  # Still under $1

    def test_cost_over_budget(
        self,
        mock_controller: MagicMock,
        tmp_state: Path,
        tmp_activity: Path,
        tmp_path: Path,
    ) -> None:
        """Cost shows over budget when limit exceeded."""
        tracker = CostTracker(
            cost_log_path=tmp_path / "cost.jsonl",
            budget_limit_usd=0.01,  # Very small budget
            llm_cost_per_1m_tokens=0.4,
        )
        # Record enough to exceed the budget
        tracker.record_llm_call("test-ns", tokens_estimated=1_000_000)

        srv = DashboardServer(
            sandbox_id="sbx_test",
            controller=mock_controller,
            cost_tracker=tracker,
            state_path=tmp_state,
            activity_log_path=tmp_activity,
            heartbeat_path=tmp_path / "heartbeat.json",
            port=0,
        )
        with srv:
            time.sleep(0.1)
            status, body = _make_request(f"{_base_url(srv)}/api/cost")

        assert status == 200
        assert body["within_budget"] is False
        assert body["budget_remaining_usd"] == 0.0
        assert body["alert_triggered"] is True
