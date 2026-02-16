"""Tests for lifecycle management (lifecycle.py).

Uses mocked SandboxController for all E2B operations.
Tests migration flow, safety limits, and cleanup.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from social_agent.control import HealthCheck, HealthStatus, SandboxInfo
from social_agent.lifecycle import LifecycleManager, MigrationResult

# --- Fixtures ---


@pytest.fixture
def mock_controller() -> MagicMock:
    """Mock SandboxController."""
    ctrl = MagicMock()
    ctrl.check_health.return_value = HealthCheck(
        status=HealthStatus.HEALTHY,
        sandbox_id="sb-old",
    )
    ctrl.list_sandboxes.return_value = []
    ctrl.kill.return_value = True
    ctrl.write_file.return_value = None
    ctrl.inject_override.return_value = None
    return ctrl


@pytest.fixture
def lifecycle(mock_controller: MagicMock) -> LifecycleManager:
    """LifecycleManager with mocked controller."""
    return LifecycleManager(
        controller=mock_controller,
        e2b_api_key="test_key",
        migration_threshold_s=300,
        verify_timeout_s=1,  # Short for tests
        max_migrations_per_day=10,
    )


# --- MigrationResult tests ---


class TestMigrationResult:
    """Tests for MigrationResult dataclass."""

    def test_success_result(self) -> None:
        """Successful migration result stores details."""
        result = MigrationResult(
            success=True,
            old_sandbox_id="old-1",
            new_sandbox_id="new-1",
            duration_s=5.0,
        )
        assert result.success is True
        assert result.error == ""

    def test_failure_result(self) -> None:
        """Failed migration result stores error."""
        result = MigrationResult(
            success=False,
            old_sandbox_id="old-1",
            new_sandbox_id="",
            duration_s=0.0,
            error="limit reached",
        )
        assert result.success is False
        assert "limit" in result.error

    def test_frozen(self) -> None:
        """MigrationResult is immutable."""
        result = MigrationResult(
            success=True, old_sandbox_id="", new_sandbox_id="", duration_s=0.0
        )
        with pytest.raises(AttributeError):
            result.success = False  # type: ignore[misc]


# --- Safety limit tests ---


class TestSafetyLimits:
    """Tests for migration safety limits."""

    def test_can_migrate_initially(self, lifecycle: LifecycleManager) -> None:
        """Can migrate when no migrations done today."""
        assert lifecycle.can_migrate is True

    def test_migration_limit_reached(self, lifecycle: LifecycleManager) -> None:
        """Cannot migrate when daily limit reached."""
        lifecycle._migrations_today = 10
        lifecycle._last_migration_date = _today_str()
        assert lifecycle.can_migrate is False

    def test_daily_counter_resets(self, lifecycle: LifecycleManager) -> None:
        """Migration counter resets on new day."""
        lifecycle._migrations_today = 10
        lifecycle._last_migration_date = "2020-01-01"  # Old date
        assert lifecycle.can_migrate is True
        assert lifecycle.migrations_today == 0

    def test_concurrent_sandbox_limit(
        self,
        lifecycle: LifecycleManager,
        mock_controller: MagicMock,
    ) -> None:
        """Cannot create successor when max sandboxes active."""
        mock_controller.list_sandboxes.return_value = [
            SandboxInfo(sandbox_id="sb-1"),
            SandboxInfo(sandbox_id="sb-2"),
        ]
        result = lifecycle.create_successor()
        assert result is None


# --- Should migrate tests ---


class TestShouldMigrate:
    """Tests for migration trigger detection."""

    def test_healthy_sandbox_no_migration(
        self,
        lifecycle: LifecycleManager,
    ) -> None:
        """Healthy sandbox does not trigger migration."""
        assert lifecycle.should_migrate("sb-1") is False

    def test_stuck_sandbox_triggers_migration(
        self,
        lifecycle: LifecycleManager,
        mock_controller: MagicMock,
    ) -> None:
        """Stuck sandbox triggers migration."""
        mock_controller.check_health.return_value = HealthCheck(
            status=HealthStatus.STUCK,
            sandbox_id="sb-1",
        )
        assert lifecycle.should_migrate("sb-1") is True

    def test_dead_sandbox_triggers_migration(
        self,
        lifecycle: LifecycleManager,
        mock_controller: MagicMock,
    ) -> None:
        """Dead sandbox triggers migration."""
        mock_controller.check_health.return_value = HealthCheck(
            status=HealthStatus.DEAD,
            sandbox_id="sb-1",
        )
        assert lifecycle.should_migrate("sb-1") is True

    def test_migration_limit_prevents_trigger(
        self,
        lifecycle: LifecycleManager,
        mock_controller: MagicMock,
    ) -> None:
        """Migration limit prevents trigger even for stuck sandbox."""
        lifecycle._migrations_today = 10
        lifecycle._last_migration_date = _today_str()
        mock_controller.check_health.return_value = HealthCheck(
            status=HealthStatus.STUCK,
            sandbox_id="sb-1",
        )
        assert lifecycle.should_migrate("sb-1") is False


# --- Create successor tests ---


class TestCreateSuccessor:
    """Tests for successor sandbox creation."""

    @patch("social_agent.lifecycle.Sandbox")
    def test_create_success(
        self,
        mock_sandbox_cls: MagicMock,
        lifecycle: LifecycleManager,
    ) -> None:
        """Successfully creates a new sandbox."""
        mock_instance = MagicMock()
        mock_instance.sandbox_id = "sb-new"
        mock_sandbox_cls.create.return_value = mock_instance

        result = lifecycle.create_successor()
        assert result == "sb-new"
        mock_sandbox_cls.create.assert_called_once_with(api_key="test_key")

    @patch("social_agent.lifecycle.Sandbox")
    def test_create_failure(
        self,
        mock_sandbox_cls: MagicMock,
        lifecycle: LifecycleManager,
    ) -> None:
        """Returns None on creation failure."""
        mock_sandbox_cls.create.side_effect = RuntimeError("E2B error")
        result = lifecycle.create_successor()
        assert result is None


# --- Deploy tests ---


class TestDeploySelf:
    """Tests for deploying agent to new sandbox."""

    def test_deploy_writes_commands(
        self,
        lifecycle: LifecycleManager,
        mock_controller: MagicMock,
    ) -> None:
        """Deploy writes command files to sandbox."""
        result = lifecycle.deploy_self(
            "sb-new",
            "https://github.com/org/brain",
            "ghp_token",
        )
        assert result is True
        assert mock_controller.write_file.call_count == 3

    def test_deploy_failure(
        self,
        lifecycle: LifecycleManager,
        mock_controller: MagicMock,
    ) -> None:
        """Deploy returns False on write failure."""
        mock_controller.write_file.side_effect = RuntimeError("write failed")
        result = lifecycle.deploy_self(
            "sb-new",
            "https://github.com/org/brain",
            "ghp_token",
        )
        assert result is False


# --- Verify successor tests ---


class TestVerifySuccessor:
    """Tests for successor health verification."""

    def test_verify_healthy(
        self,
        lifecycle: LifecycleManager,
        mock_controller: MagicMock,
    ) -> None:
        """Returns True when successor is healthy."""
        mock_controller.check_health.return_value = HealthCheck(
            status=HealthStatus.HEALTHY,
            sandbox_id="sb-new",
        )
        result = lifecycle.verify_successor("sb-new", timeout=1)
        assert result is True

    def test_verify_timeout(
        self,
        lifecycle: LifecycleManager,
        mock_controller: MagicMock,
    ) -> None:
        """Returns False when successor never becomes healthy."""
        mock_controller.check_health.return_value = HealthCheck(
            status=HealthStatus.UNKNOWN,
            sandbox_id="sb-new",
        )
        result = lifecycle.verify_successor("sb-new", timeout=1)
        assert result is False


# --- Graceful shutdown tests ---


class TestGracefulShutdown:
    """Tests for graceful shutdown."""

    def test_shutdown_success(
        self,
        lifecycle: LifecycleManager,
        mock_controller: MagicMock,
    ) -> None:
        """Successful shutdown kills sandbox and increments counter."""
        result = lifecycle.graceful_shutdown("sb-old")
        assert result is True
        assert lifecycle.migrations_today == 1
        mock_controller.kill.assert_called_once_with("sb-old")
        mock_controller.inject_override.assert_called_once()

    def test_shutdown_kill_failure(
        self,
        lifecycle: LifecycleManager,
        mock_controller: MagicMock,
    ) -> None:
        """Failed kill returns False, does not increment counter."""
        mock_controller.kill.return_value = False
        result = lifecycle.graceful_shutdown("sb-old")
        assert result is False
        assert lifecycle.migrations_today == 0

    def test_shutdown_override_failure_tolerated(
        self,
        lifecycle: LifecycleManager,
        mock_controller: MagicMock,
    ) -> None:
        """Override write failure doesn't block shutdown."""
        mock_controller.inject_override.side_effect = RuntimeError("fail")
        result = lifecycle.graceful_shutdown("sb-old")
        assert result is True  # Kill still succeeds


# --- Full migration tests ---


class TestMigrate:
    """Tests for the full migration flow."""

    @patch("social_agent.lifecycle.Sandbox")
    def test_full_migration_success(
        self,
        mock_sandbox_cls: MagicMock,
        lifecycle: LifecycleManager,
        mock_controller: MagicMock,
    ) -> None:
        """Full migration: create → deploy → verify → shutdown."""
        mock_instance = MagicMock()
        mock_instance.sandbox_id = "sb-new"
        mock_sandbox_cls.create.return_value = mock_instance

        mock_controller.check_health.return_value = HealthCheck(
            status=HealthStatus.HEALTHY,
            sandbox_id="sb-new",
        )

        result = lifecycle.migrate("sb-old", "https://github.com/org/brain", "tok")
        assert result.success is True
        assert result.new_sandbox_id == "sb-new"
        assert result.old_sandbox_id == "sb-old"
        assert result.duration_s >= 0

    def test_migration_limit_blocks(
        self,
        lifecycle: LifecycleManager,
    ) -> None:
        """Migration blocked when daily limit reached."""
        lifecycle._migrations_today = 10
        lifecycle._last_migration_date = _today_str()
        result = lifecycle.migrate("sb-old", "url", "tok")
        assert result.success is False
        assert "limit" in result.error

    @patch("social_agent.lifecycle.Sandbox")
    def test_migration_create_failure(
        self,
        mock_sandbox_cls: MagicMock,
        lifecycle: LifecycleManager,
    ) -> None:
        """Migration fails if successor creation fails."""
        mock_sandbox_cls.create.side_effect = RuntimeError("fail")
        result = lifecycle.migrate("sb-old", "url", "tok")
        assert result.success is False
        assert "create" in result.error.lower()

    @patch("social_agent.lifecycle.Sandbox")
    def test_migration_deploy_failure_cleans_up(
        self,
        mock_sandbox_cls: MagicMock,
        lifecycle: LifecycleManager,
        mock_controller: MagicMock,
    ) -> None:
        """Failed deploy kills the successor sandbox."""
        mock_instance = MagicMock()
        mock_instance.sandbox_id = "sb-new"
        mock_sandbox_cls.create.return_value = mock_instance
        mock_controller.write_file.side_effect = RuntimeError("fail")

        result = lifecycle.migrate("sb-old", "url", "tok")
        assert result.success is False
        # Verify the successor was cleaned up
        mock_controller.kill.assert_called_with("sb-new")

    @patch("social_agent.lifecycle.Sandbox")
    def test_migration_verify_failure_cleans_up(
        self,
        mock_sandbox_cls: MagicMock,
        lifecycle: LifecycleManager,
        mock_controller: MagicMock,
    ) -> None:
        """Failed verification kills the successor sandbox."""
        mock_instance = MagicMock()
        mock_instance.sandbox_id = "sb-new"
        mock_sandbox_cls.create.return_value = mock_instance
        mock_controller.check_health.return_value = HealthCheck(
            status=HealthStatus.UNKNOWN,
            sandbox_id="sb-new",
        )

        result = lifecycle.migrate("sb-old", "url", "tok")
        assert result.success is False
        assert "health" in result.error.lower() or "verification" in result.error.lower()

    @patch("social_agent.lifecycle.Sandbox")
    def test_migration_shutdown_failure_still_succeeds(
        self,
        mock_sandbox_cls: MagicMock,
        lifecycle: LifecycleManager,
        mock_controller: MagicMock,
    ) -> None:
        """Migration succeeds even if old sandbox shutdown fails."""
        mock_instance = MagicMock()
        mock_instance.sandbox_id = "sb-new"
        mock_sandbox_cls.create.return_value = mock_instance

        mock_controller.check_health.return_value = HealthCheck(
            status=HealthStatus.HEALTHY,
            sandbox_id="sb-new",
        )
        # Old sandbox kill fails
        mock_controller.kill.return_value = False

        result = lifecycle.migrate("sb-old", "https://github.com/org/brain", "tok")
        # Migration still succeeds (new sandbox is healthy)
        assert result.success is True
        assert result.new_sandbox_id == "sb-new"


# --- Cleanup tests ---


class TestCleanupOrphans:
    """Tests for orphan sandbox cleanup."""

    def test_cleanup_kills_others(
        self,
        lifecycle: LifecycleManager,
        mock_controller: MagicMock,
    ) -> None:
        """Cleanup kills all sandboxes except the keeper."""
        mock_controller.list_sandboxes.return_value = [
            SandboxInfo(sandbox_id="sb-keep"),
            SandboxInfo(sandbox_id="sb-orphan-1"),
            SandboxInfo(sandbox_id="sb-orphan-2"),
        ]
        killed = lifecycle.cleanup_orphans("sb-keep")
        assert len(killed) == 2
        assert "sb-keep" not in killed

    def test_cleanup_empty(
        self,
        lifecycle: LifecycleManager,
        mock_controller: MagicMock,
    ) -> None:
        """Cleanup with no sandboxes returns empty."""
        mock_controller.list_sandboxes.return_value = []
        killed = lifecycle.cleanup_orphans("sb-keep")
        assert killed == []

    def test_cleanup_kill_failure(
        self,
        lifecycle: LifecycleManager,
        mock_controller: MagicMock,
    ) -> None:
        """Failed kill not included in result."""
        mock_controller.list_sandboxes.return_value = [
            SandboxInfo(sandbox_id="sb-keep"),
            SandboxInfo(sandbox_id="sb-orphan"),
        ]
        mock_controller.kill.return_value = False
        killed = lifecycle.cleanup_orphans("sb-keep")
        assert killed == []


# --- Helper ---


def _today_str() -> str:
    """Get today's date string."""
    from datetime import UTC, datetime

    return datetime.now(tz=UTC).strftime("%Y-%m-%d")
