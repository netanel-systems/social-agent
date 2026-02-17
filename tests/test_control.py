"""Tests for external control plane (control.py).

Tests SandboxController methods with mocked E2B SDK.
Follows boundary pattern: defaults, valid inputs, errors, edge cases.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from social_agent.control import (
    HealthCheck,
    HealthStatus,
    ProcessInfo,
    SandboxController,
    SandboxInfo,
)

# --- Fixtures ---


@pytest.fixture
def controller() -> SandboxController:
    """Controller with explicit API key."""
    return SandboxController(api_key="test-key")


@pytest.fixture
def controller_no_key() -> SandboxController:
    """Controller without API key (uses env var)."""
    return SandboxController()


# --- Kill switch tests ---


class TestKill:
    """Tests for kill() — THE kill switch."""

    @patch("social_agent.control.Sandbox.kill")
    def test_kill_success(self, mock_kill: MagicMock, controller: SandboxController) -> None:
        """Kill returns True when sandbox is killed."""
        mock_kill.return_value = True
        result = controller.kill("sbx_123")
        assert result is True
        mock_kill.assert_called_once_with("sbx_123", api_key="test-key")

    @patch("social_agent.control.Sandbox.kill")
    def test_kill_not_found(self, mock_kill: MagicMock, controller: SandboxController) -> None:
        """Kill returns False when sandbox not found."""
        mock_kill.return_value = False
        result = controller.kill("sbx_gone")
        assert result is False

    @patch("social_agent.control.Sandbox.kill")
    def test_kill_no_api_key(
        self, mock_kill: MagicMock, controller_no_key: SandboxController
    ) -> None:
        """Kill works without explicit API key."""
        mock_kill.return_value = True
        result = controller_no_key.kill("sbx_123")
        assert result is True
        mock_kill.assert_called_once_with("sbx_123")


class TestKillAll:
    """Tests for kill_all() — emergency kill."""

    @patch("social_agent.control.Sandbox.kill")
    @patch("social_agent.control.Sandbox.list")
    def test_kill_all_multiple(
        self, mock_list: MagicMock, mock_kill: MagicMock, controller: SandboxController
    ) -> None:
        """Kill all kills multiple sandboxes."""
        sbx1 = MagicMock()
        sbx1.sandbox_id = "sbx_1"
        sbx1.template_id = "tmpl_1"
        sbx1.started_at = "2026-01-01T00:00:00Z"
        sbx1.metadata = {}
        sbx2 = MagicMock()
        sbx2.sandbox_id = "sbx_2"
        sbx2.template_id = "tmpl_2"
        sbx2.started_at = "2026-01-01T00:00:00Z"
        sbx2.metadata = {}
        mock_paginator = MagicMock()
        mock_paginator.has_next = True

        def _next_multiple() -> list[MagicMock]:
            mock_paginator.has_next = False
            return [sbx1, sbx2]

        mock_paginator.next_items = _next_multiple
        mock_list.return_value = mock_paginator
        mock_kill.return_value = True

        killed = controller.kill_all()
        assert killed == ["sbx_1", "sbx_2"]
        assert mock_kill.call_count == 2

    @patch("social_agent.control.Sandbox.kill")
    @patch("social_agent.control.Sandbox.list")
    def test_kill_all_empty(
        self, mock_list: MagicMock, mock_kill: MagicMock, controller: SandboxController
    ) -> None:
        """Kill all with no sandboxes returns empty list."""
        mock_paginator = MagicMock()
        mock_paginator.has_next = False
        mock_list.return_value = mock_paginator
        killed = controller.kill_all()
        assert killed == []
        mock_kill.assert_not_called()

    @patch("social_agent.control.Sandbox.kill")
    @patch("social_agent.control.Sandbox.list")
    def test_kill_all_partial_failure(
        self, mock_list: MagicMock, mock_kill: MagicMock, controller: SandboxController
    ) -> None:
        """Kill all handles partial failures."""
        sbx1 = MagicMock()
        sbx1.sandbox_id = "sbx_1"
        sbx1.template_id = None
        sbx1.started_at = None
        sbx1.metadata = {}
        sbx2 = MagicMock()
        sbx2.sandbox_id = "sbx_2"
        sbx2.template_id = None
        sbx2.started_at = None
        sbx2.metadata = {}
        mock_paginator = MagicMock()
        mock_paginator.has_next = True

        def _next_partial() -> list[MagicMock]:
            mock_paginator.has_next = False
            return [sbx1, sbx2]

        mock_paginator.next_items = _next_partial
        mock_list.return_value = mock_paginator
        mock_kill.side_effect = [True, False]

        killed = controller.kill_all()
        assert killed == ["sbx_1"]


# --- Observation tests ---


class TestIsAlive:
    """Tests for is_alive()."""

    @patch("social_agent.control.Sandbox.connect")
    def test_alive(self, mock_connect: MagicMock, controller: SandboxController) -> None:
        """Returns True when sandbox is running."""
        mock_sbx = MagicMock()
        mock_sbx.is_running.return_value = True
        mock_connect.return_value = mock_sbx
        assert controller.is_alive("sbx_123") is True

    @patch("social_agent.control.Sandbox.connect")
    def test_not_alive(self, mock_connect: MagicMock, controller: SandboxController) -> None:
        """Returns False when sandbox is not running."""
        mock_sbx = MagicMock()
        mock_sbx.is_running.return_value = False
        mock_connect.return_value = mock_sbx
        assert controller.is_alive("sbx_123") is False

    @patch("social_agent.control.Sandbox.connect")
    def test_connection_error(self, mock_connect: MagicMock, controller: SandboxController) -> None:
        """Returns False when cannot connect."""
        mock_connect.side_effect = Exception("Connection refused")
        assert controller.is_alive("sbx_gone") is False


class TestListSandboxes:
    """Tests for list_sandboxes()."""

    @patch("social_agent.control.Sandbox.list")
    def test_list_multiple(self, mock_list: MagicMock, controller: SandboxController) -> None:
        """Lists multiple sandboxes."""
        sbx1 = MagicMock()
        sbx1.sandbox_id = "sbx_1"
        sbx1.template_id = "tmpl"
        sbx1.started_at = "2026-01-01"
        sbx1.metadata = {"env": "prod"}
        mock_paginator = MagicMock()
        mock_paginator.has_next = True

        def _next_list() -> list[MagicMock]:
            mock_paginator.has_next = False
            return [sbx1]

        mock_paginator.next_items = _next_list
        mock_list.return_value = mock_paginator

        result = controller.list_sandboxes()
        assert len(result) == 1
        assert isinstance(result[0], SandboxInfo)
        assert result[0].sandbox_id == "sbx_1"
        assert result[0].template_id == "tmpl"
        assert result[0].metadata == {"env": "prod"}

    @patch("social_agent.control.Sandbox.list")
    def test_list_empty(self, mock_list: MagicMock, controller: SandboxController) -> None:
        """Returns empty list when no sandboxes."""
        mock_paginator = MagicMock()
        mock_paginator.has_next = False
        mock_list.return_value = mock_paginator
        assert controller.list_sandboxes() == []

    @patch("social_agent.control.Sandbox.list")
    def test_list_multiple_pages(self, mock_list: MagicMock, controller: SandboxController) -> None:
        """Accumulates sandboxes across multiple paginator pages."""
        sbx1 = MagicMock()
        sbx1.sandbox_id = "sbx_1"
        sbx1.template_id = "tmpl"
        sbx1.started_at = "2026-01-01"
        sbx1.metadata = {}
        sbx2 = MagicMock()
        sbx2.sandbox_id = "sbx_2"
        sbx2.template_id = "tmpl"
        sbx2.started_at = "2026-01-02"
        sbx2.metadata = {}

        mock_paginator = MagicMock()
        pages = [[sbx1], [sbx2]]
        page_idx = [0]

        def _next_pages() -> list[MagicMock]:
            items = pages[page_idx[0]]
            page_idx[0] += 1
            if page_idx[0] >= len(pages):
                mock_paginator.has_next = False
            return items

        mock_paginator.has_next = True
        mock_paginator.next_items = _next_pages
        mock_list.return_value = mock_paginator

        result = controller.list_sandboxes()
        assert len(result) == 2
        assert result[0].sandbox_id == "sbx_1"
        assert result[1].sandbox_id == "sbx_2"


# --- File I/O tests ---


class TestFileIO:
    """Tests for read_file() and write_file()."""

    @patch("social_agent.control.Sandbox.connect")
    def test_read_file(self, mock_connect: MagicMock, controller: SandboxController) -> None:
        """Reads file content from sandbox."""
        mock_sbx = MagicMock()
        mock_sbx.files.read.return_value = "file content here"
        mock_connect.return_value = mock_sbx

        result = controller.read_file("sbx_123", "state.json")
        assert result == "file content here"
        mock_sbx.files.read.assert_called_once_with("state.json")

    @patch("social_agent.control.Sandbox.connect")
    def test_write_file(self, mock_connect: MagicMock, controller: SandboxController) -> None:
        """Writes content to sandbox file."""
        mock_sbx = MagicMock()
        mock_connect.return_value = mock_sbx

        controller.write_file("sbx_123", "test.txt", "hello")
        mock_sbx.files.write.assert_called_once_with("test.txt", "hello")


# --- Convenience method tests ---


class TestReadState:
    """Tests for read_state()."""

    @patch("social_agent.control.Sandbox.connect")
    def test_read_state_success(
        self, mock_connect: MagicMock, controller: SandboxController
    ) -> None:
        """Parses state.json correctly."""
        state = {"cycle_count": 42, "posts_today": 3}
        mock_sbx = MagicMock()
        mock_sbx.files.read.return_value = json.dumps(state)
        mock_connect.return_value = mock_sbx

        result = controller.read_state("sbx_123")
        assert result == state

    @patch("social_agent.control.Sandbox.connect")
    def test_read_state_error(self, mock_connect: MagicMock, controller: SandboxController) -> None:
        """Returns empty dict on error."""
        mock_connect.side_effect = Exception("Not found")
        result = controller.read_state("sbx_gone")
        assert result == {}


class TestReadActivity:
    """Tests for read_activity()."""

    @patch("social_agent.control.Sandbox.connect")
    def test_read_activity_success(
        self, mock_connect: MagicMock, controller: SandboxController
    ) -> None:
        """Parses JSONL activity correctly."""
        records = [
            {"action": "READ_FEED", "success": True, "timestamp": "2026-01-01T00:00:00Z"},
            {"action": "REPLY", "success": True, "timestamp": "2026-01-01T00:01:00Z"},
            {"action": "CREATE_POST", "success": False, "timestamp": "2026-01-01T00:02:00Z"},
        ]
        content = "\n".join(json.dumps(r) for r in records)
        mock_sbx = MagicMock()
        mock_sbx.files.read.return_value = content
        mock_connect.return_value = mock_sbx

        result = controller.read_activity("sbx_123", last_n=2)
        assert len(result) == 2
        assert result[0]["action"] == "REPLY"
        assert result[1]["action"] == "CREATE_POST"

    @patch("social_agent.control.Sandbox.connect")
    def test_read_activity_empty(
        self, mock_connect: MagicMock, controller: SandboxController
    ) -> None:
        """Returns empty list when activity log is empty."""
        mock_sbx = MagicMock()
        mock_sbx.files.read.return_value = ""
        mock_connect.return_value = mock_sbx

        result = controller.read_activity("sbx_123")
        assert result == []

    @patch("social_agent.control.Sandbox.connect")
    def test_read_activity_error(
        self, mock_connect: MagicMock, controller: SandboxController
    ) -> None:
        """Returns empty list on connection error."""
        mock_connect.side_effect = Exception("Not found")
        result = controller.read_activity("sbx_gone")
        assert result == []

    @patch("social_agent.control.Sandbox.connect")
    def test_read_activity_malformed_lines(
        self, mock_connect: MagicMock, controller: SandboxController
    ) -> None:
        """Skips malformed JSONL lines."""
        content = '{"action": "READ_FEED"}\nNOT_JSON\n{"action": "REPLY"}'
        mock_sbx = MagicMock()
        mock_sbx.files.read.return_value = content
        mock_connect.return_value = mock_sbx

        result = controller.read_activity("sbx_123", last_n=10)
        assert len(result) == 2

    def test_read_activity_zero_returns_empty(self, controller: SandboxController) -> None:
        """last_n=0 returns empty list without reading."""
        result = controller.read_activity("sbx_123", last_n=0)
        assert result == []

    def test_read_activity_negative_returns_empty(self, controller: SandboxController) -> None:
        """Negative last_n returns empty list."""
        result = controller.read_activity("sbx_123", last_n=-5)
        assert result == []

    @patch("social_agent.control.Sandbox.connect")
    def test_read_activity_capped(
        self, mock_connect: MagicMock, controller: SandboxController
    ) -> None:
        """last_n is capped at max_records."""
        records = [json.dumps({"action": f"ACT_{i}"}) for i in range(5)]
        content = "\n".join(records)
        mock_sbx = MagicMock()
        mock_sbx.files.read.return_value = content
        mock_connect.return_value = mock_sbx

        result = controller.read_activity("sbx_123", last_n=99999, max_records=3)
        assert len(result) == 3


# --- Rule injection tests ---


class TestInjectRule:
    """Tests for inject_rule() and inject_override()."""

    @patch("social_agent.control.Sandbox.connect")
    def test_inject_rule(self, mock_connect: MagicMock, controller: SandboxController) -> None:
        """Appends rule to DOS.md and logs override."""
        mock_sbx = MagicMock()
        mock_sbx.files.read.side_effect = [
            "# Rules\n- Existing rule\n",  # DOS.md read
            "# External Overrides\n\n| Timestamp | Author | Description |\n",  # overrides read
        ]
        mock_connect.return_value = mock_sbx

        controller.inject_rule("sbx_123", "Never post after midnight")

        # Verify DOS.md was written with appended rule
        calls = mock_sbx.files.write.call_args_list
        assert len(calls) == 2  # DOS.md + external_overrides.md
        dos_content = calls[0][0][1]
        assert "- Never post after midnight" in dos_content
        assert "# Rules" in dos_content

    @patch("social_agent.control.Sandbox.connect")
    def test_inject_override(self, mock_connect: MagicMock, controller: SandboxController) -> None:
        """Logs override to external_overrides.md."""
        mock_sbx = MagicMock()
        mock_sbx.files.read.return_value = (
            "# External Overrides\n\n| Timestamp | Author | Description |\n"
        )
        mock_connect.return_value = mock_sbx

        controller.inject_override("sbx_123", "Changed cycle interval")

        mock_sbx.files.write.assert_called_once()
        written = mock_sbx.files.write.call_args[0][1]
        assert "Changed cycle interval" in written
        assert "External Control" in written

    @patch("social_agent.control.Sandbox.connect")
    def test_inject_override_creates_file(
        self, mock_connect: MagicMock, controller: SandboxController
    ) -> None:
        """Creates external_overrides.md if it doesn't exist."""
        mock_sbx = MagicMock()
        mock_sbx.files.read.side_effect = Exception("File not found")
        mock_connect.return_value = mock_sbx

        controller.inject_override("sbx_123", "First override")

        mock_sbx.files.write.assert_called_once()
        written = mock_sbx.files.write.call_args[0][1]
        assert "# External Overrides Log" in written
        assert "First override" in written


# --- Metrics tests ---


class TestMetrics:
    """Tests for get_metrics()."""

    @patch("social_agent.control.Sandbox.get_metrics")
    def test_get_metrics_success(
        self, mock_metrics: MagicMock, controller: SandboxController
    ) -> None:
        """Returns parsed metrics."""
        m1 = MagicMock()
        m1.cpu = 45.2
        m1.memory = 128.0
        m1.disk = 512.0
        mock_metrics.return_value = [m1]

        result = controller.get_metrics("sbx_123")
        assert len(result) == 1
        assert result[0]["cpu"] == 45.2
        assert result[0]["memory"] == 128.0

    @patch("social_agent.control.Sandbox.get_metrics")
    def test_get_metrics_error(
        self, mock_metrics: MagicMock, controller: SandboxController
    ) -> None:
        """Returns empty list on error."""
        mock_metrics.side_effect = Exception("API error")
        result = controller.get_metrics("sbx_gone")
        assert result == []


# --- Timeout tests ---


class TestTimeout:
    """Tests for set_timeout()."""

    @patch("social_agent.control.Sandbox.set_timeout")
    def test_set_timeout(self, mock_timeout: MagicMock, controller: SandboxController) -> None:
        """Sets timeout correctly."""
        controller.set_timeout("sbx_123", 600)
        mock_timeout.assert_called_once_with("sbx_123", 600, api_key="test-key")


# --- Process control tests ---


class TestProcessControl:
    """Tests for kill_process() and list_processes()."""

    @patch("social_agent.control.Sandbox.connect")
    def test_kill_process(self, mock_connect: MagicMock, controller: SandboxController) -> None:
        """Kills a process by PID."""
        mock_sbx = MagicMock()
        mock_connect.return_value = mock_sbx

        controller.kill_process("sbx_123", 42)
        mock_sbx.commands.kill.assert_called_once_with(42)

    @patch("social_agent.control.Sandbox.connect")
    def test_list_processes(self, mock_connect: MagicMock, controller: SandboxController) -> None:
        """Lists processes from sandbox."""
        p1 = MagicMock()
        p1.pid = 1
        p1.cmd = "python"
        p2 = MagicMock()
        p2.pid = 42
        p2.cmd = "node"
        mock_sbx = MagicMock()
        mock_sbx.commands.list.return_value = [p1, p2]
        mock_connect.return_value = mock_sbx

        result = controller.list_processes("sbx_123")
        assert len(result) == 2
        assert isinstance(result[0], ProcessInfo)
        assert result[0].pid == 1
        assert result[0].cmd == "python"

    @patch("social_agent.control.Sandbox.connect")
    def test_list_processes_error(
        self, mock_connect: MagicMock, controller: SandboxController
    ) -> None:
        """Returns empty list on error."""
        mock_connect.side_effect = Exception("Not found")
        result = controller.list_processes("sbx_gone")
        assert result == []


# --- Health check tests ---


class TestCheckHealth:
    """Tests for check_health() — heartbeat-based health monitoring."""

    @patch("social_agent.control.Sandbox.connect")
    def test_healthy(self, mock_connect: MagicMock, controller: SandboxController) -> None:
        """HEALTHY when heartbeat is recent."""
        now = datetime.now(UTC)
        heartbeat = {
            "timestamp": now.isoformat(),
            "current_action": "READ_FEED",
            "cycle_count": 10,
            "sandbox_id": "sbx_123",
        }
        mock_sbx = MagicMock()
        mock_sbx.files.read.return_value = json.dumps(heartbeat)
        mock_connect.return_value = mock_sbx

        result = controller.check_health("sbx_123")
        assert isinstance(result, HealthCheck)
        assert result.status == HealthStatus.HEALTHY
        assert result.current_action == "READ_FEED"
        assert result.seconds_since_heartbeat is not None
        assert result.seconds_since_heartbeat < 5

    @patch("social_agent.control.Sandbox.connect")
    def test_stuck(self, mock_connect: MagicMock, controller: SandboxController) -> None:
        """STUCK when heartbeat is between thresholds."""
        old_time = datetime.now(UTC) - timedelta(seconds=120)
        heartbeat = {
            "timestamp": old_time.isoformat(),
            "current_action": "RESEARCH",
        }
        mock_sbx = MagicMock()
        mock_sbx.files.read.return_value = json.dumps(heartbeat)
        mock_connect.return_value = mock_sbx

        result = controller.check_health("sbx_123")
        assert result.status == HealthStatus.STUCK
        assert result.seconds_since_heartbeat is not None
        assert result.seconds_since_heartbeat >= 60

    @patch("social_agent.control.Sandbox.connect")
    def test_dead_old_heartbeat(
        self, mock_connect: MagicMock, controller: SandboxController
    ) -> None:
        """DEAD when heartbeat is very old."""
        old_time = datetime.now(UTC) - timedelta(seconds=700)
        heartbeat = {"timestamp": old_time.isoformat()}
        mock_sbx = MagicMock()
        mock_sbx.files.read.return_value = json.dumps(heartbeat)
        mock_connect.return_value = mock_sbx

        result = controller.check_health("sbx_123")
        assert result.status == HealthStatus.DEAD

    @patch("social_agent.control.Sandbox.connect")
    def test_dead_cannot_connect(
        self, mock_connect: MagicMock, controller: SandboxController
    ) -> None:
        """DEAD when sandbox is not running and can't connect."""
        mock_connect.side_effect = Exception("Connection refused")

        result = controller.check_health("sbx_gone")
        assert result.status == HealthStatus.DEAD
        assert result.error is not None

    @patch("social_agent.control.Sandbox.connect")
    def test_unknown_no_timestamp(
        self, mock_connect: MagicMock, controller: SandboxController
    ) -> None:
        """UNKNOWN when heartbeat has no timestamp."""
        heartbeat = {"current_action": "STARTING", "timestamp": None}
        mock_sbx = MagicMock()
        mock_sbx.files.read.return_value = json.dumps(heartbeat)
        mock_connect.return_value = mock_sbx

        result = controller.check_health("sbx_123")
        assert result.status == HealthStatus.UNKNOWN
        assert "no timestamp" in result.error.lower()

    @patch("social_agent.control.Sandbox.connect")
    def test_custom_thresholds(
        self, mock_connect: MagicMock, controller: SandboxController
    ) -> None:
        """Custom thresholds work correctly."""
        # 30 seconds ago — healthy with default thresholds, stuck with custom
        recent = datetime.now(UTC) - timedelta(seconds=30)
        heartbeat = {"timestamp": recent.isoformat(), "current_action": "REPLY"}
        mock_sbx = MagicMock()
        mock_sbx.files.read.return_value = json.dumps(heartbeat)
        mock_connect.return_value = mock_sbx

        # With tight thresholds: 30s > 10s = stuck
        result = controller.check_health(
            "sbx_123", healthy_threshold=10.0, stuck_threshold=300.0
        )
        assert result.status == HealthStatus.STUCK


# --- Dataclass tests ---


class TestDataclasses:
    """Test dataclass defaults and construction."""

    def test_health_check_defaults(self) -> None:
        """HealthCheck has correct defaults."""
        hc = HealthCheck(sandbox_id="sbx_1", status=HealthStatus.HEALTHY)
        assert hc.sandbox_id == "sbx_1"
        assert hc.status == HealthStatus.HEALTHY
        assert hc.last_heartbeat is None
        assert hc.current_action is None
        assert hc.seconds_since_heartbeat is None
        assert hc.error is None

    def test_health_check_full(self) -> None:
        """HealthCheck with all fields."""
        hc = HealthCheck(
            sandbox_id="sbx_1",
            status=HealthStatus.STUCK,
            last_heartbeat="2026-01-01T00:00:00Z",
            current_action="REPLY",
            seconds_since_heartbeat=120.5,
            error="Heartbeat delayed",
        )
        assert hc.seconds_since_heartbeat == 120.5

    def test_sandbox_info_defaults(self) -> None:
        """SandboxInfo has correct defaults."""
        si = SandboxInfo(sandbox_id="sbx_1")
        assert si.template_id is None
        assert si.started_at is None
        assert si.metadata == {}

    def test_process_info(self) -> None:
        """ProcessInfo construction."""
        pi = ProcessInfo(pid=42, cmd="python")
        assert pi.pid == 42
        assert pi.cmd == "python"

    def test_process_info_no_cmd(self) -> None:
        """ProcessInfo without cmd."""
        pi = ProcessInfo(pid=1)
        assert pi.cmd is None

    def test_health_status_values(self) -> None:
        """HealthStatus enum has correct values."""
        assert HealthStatus.HEALTHY == "healthy"
        assert HealthStatus.STUCK == "stuck"
        assert HealthStatus.DEAD == "dead"
        assert HealthStatus.UNKNOWN == "unknown"


# --- API key handling ---


class TestApiKeyHandling:
    """Tests for API key passing."""

    def test_api_params_with_key(self, controller: SandboxController) -> None:
        """API params include key when provided."""
        params = controller._api_params()
        assert params == {"api_key": "test-key"}

    def test_api_params_without_key(self, controller_no_key: SandboxController) -> None:
        """API params empty when no key provided."""
        params = controller_no_key._api_params()
        assert params == {}


# --- run_command tests ---


class TestRunCommand:
    """Tests for run_command() — executes shell commands inside a sandbox."""

    @patch("social_agent.control.Sandbox.connect")
    def test_success_returns_stdout(
        self, mock_connect: MagicMock, controller: SandboxController
    ) -> None:
        """Returns stdout string on exit_code 0."""
        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.stdout = "hello from sandbox\n"
        mock_result.stderr = ""
        mock_sbx = MagicMock()
        mock_sbx.commands.run.return_value = mock_result
        mock_connect.return_value = mock_sbx

        out = controller.run_command("sbx_123", "echo hello")
        assert out == "hello from sandbox\n"
        mock_sbx.commands.run.assert_called_once_with("echo hello", timeout=60, envs={})

    @patch("social_agent.control.Sandbox.connect")
    def test_failure_raises_runtime_error(
        self, mock_connect: MagicMock, controller: SandboxController
    ) -> None:
        """Raises RuntimeError when exit_code is non-zero."""
        mock_result = MagicMock()
        mock_result.exit_code = 1
        mock_result.stderr = "command not found"
        mock_sbx = MagicMock()
        mock_sbx.commands.run.return_value = mock_result
        mock_connect.return_value = mock_sbx

        with pytest.raises(RuntimeError, match="exit 1"):
            controller.run_command("sbx_123", "bad_cmd")

    @patch("social_agent.control.Sandbox.connect")
    def test_envs_passed_to_sdk(
        self, mock_connect: MagicMock, controller: SandboxController
    ) -> None:
        """envs dict is forwarded to commands.run()."""
        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.stdout = ""
        mock_sbx = MagicMock()
        mock_sbx.commands.run.return_value = mock_result
        mock_connect.return_value = mock_sbx

        controller.run_command(
            "sbx_123", "printenv FOO", envs={"FOO": "bar", "KEY": "val"}
        )
        mock_sbx.commands.run.assert_called_once_with(
            "printenv FOO", timeout=60, envs={"FOO": "bar", "KEY": "val"}
        )

    @patch("social_agent.control.Sandbox.connect")
    def test_none_envs_defaults_to_empty_dict(
        self, mock_connect: MagicMock, controller: SandboxController
    ) -> None:
        """envs=None is treated as empty dict."""
        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.stdout = ""
        mock_sbx = MagicMock()
        mock_sbx.commands.run.return_value = mock_result
        mock_connect.return_value = mock_sbx

        controller.run_command("sbx_123", "ls", envs=None)
        mock_sbx.commands.run.assert_called_once_with("ls", timeout=60, envs={})

    @patch("social_agent.control.Sandbox.connect")
    def test_custom_timeout_passed_to_sdk(
        self, mock_connect: MagicMock, controller: SandboxController
    ) -> None:
        """Custom timeout is forwarded to commands.run()."""
        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.stdout = ""
        mock_sbx = MagicMock()
        mock_sbx.commands.run.return_value = mock_result
        mock_connect.return_value = mock_sbx

        controller.run_command("sbx_123", "sleep 5", timeout=120)
        mock_sbx.commands.run.assert_called_once_with("sleep 5", timeout=120, envs={})

    @patch("social_agent.control.Sandbox.connect")
    def test_uses_api_key(
        self, mock_connect: MagicMock, controller: SandboxController
    ) -> None:
        """Connects to sandbox with the configured API key."""
        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.stdout = ""
        mock_sbx = MagicMock()
        mock_sbx.commands.run.return_value = mock_result
        mock_connect.return_value = mock_sbx

        controller.run_command("sbx_123", "pwd")
        mock_connect.assert_called_once_with("sbx_123", api_key="test-key")
