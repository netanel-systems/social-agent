"""Tests for watchdog check script (scripts/watchdog_check.py).

Uses mocked SandboxController and LifecycleManager for all E2B operations.
Tests all three scenarios: no sandboxes, one sandbox, multiple sandboxes.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from scripts.watchdog_check import (
    WatchdogConfig,
    WatchdogResult,
    _handle_multiple_sandboxes,
    _handle_no_sandboxes,
    _handle_one_sandbox,
    run_watchdog,
)
from social_agent.control import HealthCheck, HealthStatus, SandboxInfo

# --- Fixtures ---


@pytest.fixture
def config() -> WatchdogConfig:
    """Watchdog config for tests."""
    return WatchdogConfig(
        e2b_api_key="test-key",
        brain_repo_url="https://github.com/org/brain",
        github_token="ghp_test",
    )


@pytest.fixture
def mock_controller() -> MagicMock:
    """Mock SandboxController."""
    ctrl = MagicMock()
    ctrl.check_health.return_value = HealthCheck(
        status=HealthStatus.HEALTHY,
        sandbox_id="sb-1",
        seconds_since_heartbeat=10.0,
    )
    ctrl.list_sandboxes.return_value = []
    ctrl.kill.return_value = True
    return ctrl


@pytest.fixture
def mock_lifecycle() -> MagicMock:
    """Mock LifecycleManager."""
    lm = MagicMock()
    lm.create_successor.return_value = "sb-new"
    lm.deploy_self.return_value = True
    lm.cleanup_orphans.return_value = ["sb-orphan"]
    lm.controller = MagicMock()
    return lm


# --- WatchdogResult tests ---


class TestWatchdogResult:
    """Tests for WatchdogResult dataclass."""

    def test_healthy_result(self) -> None:
        """Healthy result stores sandbox ID."""
        result = WatchdogResult(action="healthy", sandbox_id="sb-1")
        assert result.action == "healthy"
        assert result.sandbox_id == "sb-1"
        assert result.killed == []
        assert result.error == ""

    def test_failed_result(self) -> None:
        """Failed result stores error."""
        result = WatchdogResult(action="failed", error="something broke")
        assert result.action == "failed"
        assert "broke" in result.error

    def test_frozen(self) -> None:
        """WatchdogResult is immutable."""
        result = WatchdogResult(action="healthy")
        with pytest.raises(AttributeError):
            result.action = "changed"  # type: ignore[misc]


# --- WatchdogConfig tests ---


class TestWatchdogConfig:
    """Tests for WatchdogConfig."""

    def test_from_env_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Config loads from environment variables."""
        monkeypatch.setenv("E2B_API_KEY", "key1")
        monkeypatch.setenv("BRAIN_REPO_URL", "https://example.com/brain")
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_tok")

        cfg = WatchdogConfig.from_env()
        assert cfg.e2b_api_key == "key1"
        assert cfg.brain_repo_url == "https://example.com/brain"
        assert cfg.github_token == "ghp_tok"

    def test_from_env_missing_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Missing env vars causes SystemExit(2)."""
        monkeypatch.delenv("E2B_API_KEY", raising=False)
        monkeypatch.delenv("BRAIN_REPO_URL", raising=False)
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)

        with pytest.raises(SystemExit) as exc_info:
            WatchdogConfig.from_env()
        assert exc_info.value.code == 2

    def test_default_threshold(self) -> None:
        """Default stuck threshold is 600s."""
        cfg = WatchdogConfig(
            e2b_api_key="k", brain_repo_url="u", github_token="t"
        )
        assert cfg.stuck_threshold_s == 600


# --- No sandboxes tests ---


class TestHandleNoSandboxes:
    """Tests for the 'no sandboxes running' scenario."""

    def test_deploy_success(
        self, mock_lifecycle: MagicMock, config: WatchdogConfig
    ) -> None:
        """Deploys fresh sandbox when none running."""
        result = _handle_no_sandboxes(mock_lifecycle, config)
        assert result.action == "deployed"
        assert result.sandbox_id == "sb-new"
        mock_lifecycle.create_successor.assert_called_once()
        mock_lifecycle.deploy_self.assert_called_once()

    def test_create_failure(
        self, mock_lifecycle: MagicMock, config: WatchdogConfig
    ) -> None:
        """Returns failed when sandbox creation fails."""
        mock_lifecycle.create_successor.return_value = None
        result = _handle_no_sandboxes(mock_lifecycle, config)
        assert result.action == "failed"
        assert "create" in result.error.lower()

    def test_deploy_failure_cleans_up(
        self, mock_lifecycle: MagicMock, config: WatchdogConfig
    ) -> None:
        """Cleans up sandbox when deployment fails."""
        mock_lifecycle.deploy_self.return_value = False
        result = _handle_no_sandboxes(mock_lifecycle, config)
        assert result.action == "failed"
        assert "deploy" in result.error.lower()
        mock_lifecycle.controller.kill.assert_called_once_with("sb-new")


# --- One sandbox tests ---


class TestHandleOneSandbox:
    """Tests for the 'one sandbox running' scenario."""

    def test_healthy_agent(
        self,
        mock_controller: MagicMock,
        mock_lifecycle: MagicMock,
        config: WatchdogConfig,
    ) -> None:
        """Healthy sandbox returns healthy result."""
        result = _handle_one_sandbox(
            mock_controller, mock_lifecycle, config, "sb-1"
        )
        assert result.action == "healthy"
        assert result.sandbox_id == "sb-1"

    def test_stuck_agent_recovered(
        self,
        mock_controller: MagicMock,
        mock_lifecycle: MagicMock,
        config: WatchdogConfig,
    ) -> None:
        """Stuck agent is killed and replaced."""
        mock_controller.check_health.return_value = HealthCheck(
            status=HealthStatus.STUCK,
            sandbox_id="sb-1",
        )
        result = _handle_one_sandbox(
            mock_controller, mock_lifecycle, config, "sb-1"
        )
        assert result.action == "recovered"
        assert result.sandbox_id == "sb-new"
        assert "sb-1" in result.killed
        mock_controller.kill.assert_called_once_with("sb-1")

    def test_dead_agent_recovered(
        self,
        mock_controller: MagicMock,
        mock_lifecycle: MagicMock,
        config: WatchdogConfig,
    ) -> None:
        """Dead agent is killed and replaced."""
        mock_controller.check_health.return_value = HealthCheck(
            status=HealthStatus.DEAD,
            sandbox_id="sb-1",
        )
        result = _handle_one_sandbox(
            mock_controller, mock_lifecycle, config, "sb-1"
        )
        assert result.action == "recovered"
        assert "sb-1" in result.killed

    def test_stuck_create_fails(
        self,
        mock_controller: MagicMock,
        mock_lifecycle: MagicMock,
        config: WatchdogConfig,
    ) -> None:
        """Stuck agent killed but replacement creation fails."""
        mock_controller.check_health.return_value = HealthCheck(
            status=HealthStatus.STUCK,
            sandbox_id="sb-1",
        )
        mock_lifecycle.create_successor.return_value = None
        result = _handle_one_sandbox(
            mock_controller, mock_lifecycle, config, "sb-1"
        )
        assert result.action == "failed"
        assert "sb-1" in result.killed

    def test_stuck_deploy_fails(
        self,
        mock_controller: MagicMock,
        mock_lifecycle: MagicMock,
        config: WatchdogConfig,
    ) -> None:
        """Stuck agent killed but deployment to replacement fails."""
        mock_controller.check_health.return_value = HealthCheck(
            status=HealthStatus.STUCK,
            sandbox_id="sb-1",
        )
        mock_lifecycle.deploy_self.return_value = False
        result = _handle_one_sandbox(
            mock_controller, mock_lifecycle, config, "sb-1"
        )
        assert result.action == "failed"
        assert "deploy" in result.error.lower()
        # New sandbox cleaned up
        mock_lifecycle.controller.kill.assert_called_once_with("sb-new")

    def test_unknown_status_left_alone(
        self,
        mock_controller: MagicMock,
        mock_lifecycle: MagicMock,
        config: WatchdogConfig,
    ) -> None:
        """Unknown health status leaves sandbox running."""
        mock_controller.check_health.return_value = HealthCheck(
            status=HealthStatus.UNKNOWN,
            sandbox_id="sb-1",
            error="cannot read heartbeat",
        )
        result = _handle_one_sandbox(
            mock_controller, mock_lifecycle, config, "sb-1"
        )
        assert result.action == "healthy"
        mock_controller.kill.assert_not_called()


# --- Multiple sandboxes tests ---


class TestHandleMultipleSandboxes:
    """Tests for the 'multiple sandboxes running' scenario."""

    def test_keeps_healthiest(
        self,
        mock_controller: MagicMock,
        mock_lifecycle: MagicMock,
        config: WatchdogConfig,
    ) -> None:
        """Keeps the sandbox with the freshest heartbeat."""
        sandboxes = [
            SandboxInfo(sandbox_id="sb-old"),
            SandboxInfo(sandbox_id="sb-fresh"),
        ]

        def health_side_effect(sandbox_id, **kwargs):
            if sandbox_id == "sb-fresh":
                return HealthCheck(
                    status=HealthStatus.HEALTHY,
                    sandbox_id="sb-fresh",
                    seconds_since_heartbeat=5.0,
                )
            return HealthCheck(
                status=HealthStatus.HEALTHY,
                sandbox_id="sb-old",
                seconds_since_heartbeat=30.0,
            )

        mock_controller.check_health.side_effect = health_side_effect
        mock_lifecycle.cleanup_orphans.return_value = ["sb-old"]

        result = _handle_multiple_sandboxes(
            mock_controller, mock_lifecycle, config, sandboxes
        )
        assert result.action == "cleaned"
        assert result.sandbox_id == "sb-fresh"
        assert "sb-old" in result.killed

    def test_all_unhealthy_redeploys(
        self,
        mock_controller: MagicMock,
        mock_lifecycle: MagicMock,
        config: WatchdogConfig,
    ) -> None:
        """When all sandboxes are unhealthy, kills all and redeploys."""
        sandboxes = [
            SandboxInfo(sandbox_id="sb-1"),
            SandboxInfo(sandbox_id="sb-2"),
        ]

        mock_controller.check_health.return_value = HealthCheck(
            status=HealthStatus.STUCK,
            sandbox_id="sb-1",
        )
        mock_lifecycle.cleanup_orphans.return_value = ["sb-2"]

        result = _handle_multiple_sandboxes(
            mock_controller, mock_lifecycle, config, sandboxes
        )
        assert result.action == "recovered"
        assert result.sandbox_id == "sb-new"
        assert "sb-1" in result.killed

    def test_no_healthy_keeps_first(
        self,
        mock_controller: MagicMock,
        mock_lifecycle: MagicMock,
        config: WatchdogConfig,
    ) -> None:
        """When no sandbox is HEALTHY, keeps the first one."""
        sandboxes = [
            SandboxInfo(sandbox_id="sb-A"),
            SandboxInfo(sandbox_id="sb-B"),
        ]

        # Both UNKNOWN — neither is HEALTHY
        mock_controller.check_health.return_value = HealthCheck(
            status=HealthStatus.UNKNOWN,
            sandbox_id="sb-A",
        )
        mock_lifecycle.cleanup_orphans.return_value = ["sb-B"]

        result = _handle_multiple_sandboxes(
            mock_controller, mock_lifecycle, config, sandboxes
        )
        # UNKNOWN is not STUCK/DEAD, so keeper is left alive
        assert result.action == "cleaned"
        assert result.sandbox_id == "sb-A"


# --- Integration: run_watchdog tests ---


class TestRunWatchdog:
    """Tests for the full run_watchdog function."""

    @patch("scripts.watchdog_check.SandboxController")
    @patch("scripts.watchdog_check.LifecycleManager")
    def test_no_sandboxes_deploys(
        self,
        mock_lm_cls: MagicMock,
        mock_ctrl_cls: MagicMock,
        config: WatchdogConfig,
    ) -> None:
        """run_watchdog deploys when no sandboxes found."""
        mock_ctrl = MagicMock()
        mock_ctrl.list_sandboxes.return_value = []
        mock_ctrl_cls.return_value = mock_ctrl

        mock_lm = MagicMock()
        mock_lm.create_successor.return_value = "sb-new"
        mock_lm.deploy_self.return_value = True
        mock_lm.controller = mock_ctrl
        mock_lm_cls.return_value = mock_lm

        result = run_watchdog(config)
        assert result.action == "deployed"

    @patch("scripts.watchdog_check.SandboxController")
    @patch("scripts.watchdog_check.LifecycleManager")
    def test_healthy_sandbox(
        self,
        mock_lm_cls: MagicMock,
        mock_ctrl_cls: MagicMock,
        config: WatchdogConfig,
    ) -> None:
        """run_watchdog reports healthy for healthy sandbox."""
        mock_ctrl = MagicMock()
        mock_ctrl.list_sandboxes.return_value = [
            SandboxInfo(sandbox_id="sb-1"),
        ]
        mock_ctrl.check_health.return_value = HealthCheck(
            status=HealthStatus.HEALTHY,
            sandbox_id="sb-1",
            seconds_since_heartbeat=5.0,
        )
        mock_ctrl_cls.return_value = mock_ctrl

        mock_lm = MagicMock()
        mock_lm_cls.return_value = mock_lm

        result = run_watchdog(config)
        assert result.action == "healthy"
        assert result.sandbox_id == "sb-1"

    @patch("scripts.watchdog_check.SandboxController")
    @patch("scripts.watchdog_check.LifecycleManager")
    def test_multiple_sandboxes_cleaned(
        self,
        mock_lm_cls: MagicMock,
        mock_ctrl_cls: MagicMock,
        config: WatchdogConfig,
    ) -> None:
        """run_watchdog cleans up multiple sandboxes."""
        mock_ctrl = MagicMock()
        mock_ctrl.list_sandboxes.return_value = [
            SandboxInfo(sandbox_id="sb-1"),
            SandboxInfo(sandbox_id="sb-2"),
        ]
        mock_ctrl.check_health.return_value = HealthCheck(
            status=HealthStatus.HEALTHY,
            sandbox_id="sb-1",
            seconds_since_heartbeat=5.0,
        )
        mock_ctrl_cls.return_value = mock_ctrl

        mock_lm = MagicMock()
        mock_lm.cleanup_orphans.return_value = ["sb-2"]
        mock_lm_cls.return_value = mock_lm

        result = run_watchdog(config)
        assert result.action == "cleaned"
