"""Tests for git persistence layer (git_sync.py).

Uses mocked SandboxClient for all git commands.
Tests queue behavior, retry logic, tracker logging, and lifecycle.
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from social_agent.git_sync import GitSync, SyncEntry, SyncResult
from social_agent.sandbox import BashResult

# --- Fixtures ---


@pytest.fixture
def mock_sandbox() -> MagicMock:
    """Mock SandboxClient that succeeds on all git commands."""
    sandbox = MagicMock()
    sandbox.run_bash.return_value = BashResult(
        stdout="",
        stderr="",
        exit_code=0,
    )
    return sandbox


@pytest.fixture
def tracker_path(tmp_path: Path) -> Path:
    """Temporary tracker file path."""
    return tmp_path / "logs" / "git_tracker.jsonl"


@pytest.fixture
def git_sync(mock_sandbox: MagicMock, tracker_path: Path) -> GitSync:
    """GitSync instance with mocked sandbox."""
    return GitSync(
        sandbox=mock_sandbox,
        repo_url="https://github.com/netanel-systems/nathan-brain",
        token="ghp_test_token",
        tracker_path=tracker_path,
        branch="main",
    )


# --- Dataclass tests ---


class TestSyncEntry:
    """Tests for SyncEntry dataclass."""

    def test_creation(self) -> None:
        """SyncEntry stores files and message."""
        entry = SyncEntry(files=["state.json"], message="cycle 1")
        assert entry.files == ["state.json"]
        assert entry.message == "cycle 1"

    def test_frozen(self) -> None:
        """SyncEntry is immutable."""
        entry = SyncEntry(files=["state.json"], message="cycle 1")
        with pytest.raises(AttributeError):
            entry.message = "changed"  # type: ignore[misc]


class TestSyncResult:
    """Tests for SyncResult dataclass."""

    def test_defaults(self) -> None:
        """SyncResult has correct defaults."""
        result = SyncResult(
            timestamp="2026-02-16T12:00:00Z",
            files=["state.json"],
            commit_hash="abc1234",
            status="success",
            duration_ms=42.5,
            message="cycle 1",
        )
        assert result.error == ""
        assert result.attempts == 1

    def test_with_error(self) -> None:
        """SyncResult can store error info."""
        result = SyncResult(
            timestamp="2026-02-16T12:00:00Z",
            files=["state.json"],
            commit_hash="",
            status="failed",
            duration_ms=100.0,
            message="cycle 1",
            error="push rejected",
            attempts=3,
        )
        assert result.error == "push rejected"
        assert result.attempts == 3

    def test_frozen(self) -> None:
        """SyncResult is immutable."""
        result = SyncResult(
            timestamp="2026-02-16T12:00:00Z",
            files=[],
            commit_hash="",
            status="success",
            duration_ms=0,
            message="",
        )
        with pytest.raises(AttributeError):
            result.status = "changed"  # type: ignore[misc]


# --- Lifecycle tests ---


class TestLifecycle:
    """Tests for GitSync start/stop."""

    def test_start_sets_running(self, git_sync: GitSync) -> None:
        """Start marks sync as running."""
        git_sync.start()
        assert git_sync.is_running
        git_sync.stop()

    def test_stop_clears_running(self, git_sync: GitSync) -> None:
        """Stop marks sync as not running."""
        git_sync.start()
        git_sync.stop()
        assert not git_sync.is_running

    def test_double_start_idempotent(self, git_sync: GitSync) -> None:
        """Starting twice is a no-op."""
        git_sync.start()
        thread1 = git_sync._thread
        git_sync.start()
        assert git_sync._thread is thread1
        git_sync.stop()

    def test_stop_when_not_running(self, git_sync: GitSync) -> None:
        """Stopping when not running is safe."""
        git_sync.stop()  # Should not raise


# --- Queue tests ---


class TestQueue:
    """Tests for sync queue behavior."""

    def test_queue_sync_returns_true(self, git_sync: GitSync) -> None:
        """Queuing when running returns True."""
        git_sync.start()
        result = git_sync.queue_sync(["state.json"], "cycle 1")
        assert result is True
        git_sync.stop()

    def test_queue_sync_when_not_running(self, git_sync: GitSync) -> None:
        """Queuing when not running returns False."""
        result = git_sync.queue_sync(["state.json"], "cycle 1")
        assert result is False

    def test_stats_initial(self, git_sync: GitSync) -> None:
        """Initial stats are zero."""
        assert git_sync.stats == {
            "total_syncs": 0,
            "total_failures": 0,
            "queue_size": 0,
        }


# --- Sync processing tests ---


class TestSyncProcessing:
    """Tests for background sync processing."""

    def test_successful_sync(
        self,
        git_sync: GitSync,
        mock_sandbox: MagicMock,
    ) -> None:
        """Successful sync calls git add, commit, push."""
        # Make git diff --cached return non-zero (there ARE changes)
        def side_effect(cmd: str) -> BashResult:
            if "diff --cached --quiet" in cmd:
                return BashResult(stdout="", stderr="", exit_code=1)
            if "rev-parse --short HEAD" in cmd:
                return BashResult(stdout="abc1234\n", stderr="", exit_code=0)
            return BashResult(stdout="", stderr="", exit_code=0)

        mock_sandbox.run_bash.side_effect = side_effect

        git_sync.start()
        git_sync.queue_sync(["state.json"], "cycle 1")
        time.sleep(0.5)  # Let worker process
        git_sync.stop()

        assert git_sync.stats["total_syncs"] == 1
        assert git_sync.stats["total_failures"] == 0

    def test_no_changes_skips_commit(
        self,
        git_sync: GitSync,
        mock_sandbox: MagicMock,
    ) -> None:
        """When no changes staged, skip commit and push."""
        # git diff --cached --quiet returns 0 (no changes)
        mock_sandbox.run_bash.return_value = BashResult(
            stdout="", stderr="", exit_code=0
        )

        git_sync.start()
        git_sync.queue_sync(["state.json"], "no changes")
        time.sleep(0.5)
        git_sync.stop()

        # Still counts as a sync (skipped)
        assert git_sync.stats["total_syncs"] == 1

    def test_failed_sync_retries(
        self,
        git_sync: GitSync,
        mock_sandbox: MagicMock,
    ) -> None:
        """Failed sync retries up to _MAX_RETRIES times."""
        # Always fail on git add
        mock_sandbox.run_bash.return_value = BashResult(
            stdout="", stderr="error: fatal", exit_code=128
        )

        git_sync.start()
        git_sync.queue_sync(["state.json"], "will fail")
        time.sleep(3.0)  # Allow time for retries (3 * _RETRY_DELAY)
        git_sync.stop()

        assert git_sync.stats["total_failures"] == 1
        assert git_sync.stats["total_syncs"] == 0


# --- Tracker logging tests ---


class TestTrackerLogging:
    """Tests for git_tracker.jsonl logging."""

    def test_success_logged(
        self,
        git_sync: GitSync,
        mock_sandbox: MagicMock,
        tracker_path: Path,
    ) -> None:
        """Successful sync is logged to tracker."""
        def side_effect(cmd: str) -> BashResult:
            if "diff --cached --quiet" in cmd:
                return BashResult(stdout="", stderr="", exit_code=1)
            if "rev-parse --short HEAD" in cmd:
                return BashResult(stdout="abc1234\n", stderr="", exit_code=0)
            return BashResult(stdout="", stderr="", exit_code=0)

        mock_sandbox.run_bash.side_effect = side_effect

        git_sync.start()
        git_sync.queue_sync(["state.json"], "tracked cycle")
        time.sleep(0.5)
        git_sync.stop()

        assert tracker_path.exists()
        lines = tracker_path.read_text().strip().split("\n")
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["status"] == "success"
        assert record["commit_hash"] == "abc1234"
        assert record["message"] == "tracked cycle"
        assert "state.json" in record["files"]

    def test_failure_logged(
        self,
        git_sync: GitSync,
        mock_sandbox: MagicMock,
        tracker_path: Path,
    ) -> None:
        """Failed sync is logged with error info."""
        mock_sandbox.run_bash.return_value = BashResult(
            stdout="", stderr="fatal error", exit_code=128
        )

        git_sync.start()
        git_sync.queue_sync(["state.json"], "fail tracked")
        time.sleep(3.0)
        git_sync.stop()

        assert tracker_path.exists()
        lines = tracker_path.read_text().strip().split("\n")
        record = json.loads(lines[0])
        assert record["status"] == "failed"
        assert record["attempts"] == 3
        assert "fatal" in record["error"].lower() or "git add failed" in record["error"]

    def test_no_tracker_path(
        self,
        mock_sandbox: MagicMock,
    ) -> None:
        """GitSync works without tracker_path."""
        sync = GitSync(
            sandbox=mock_sandbox,
            repo_url="https://github.com/org/repo",
            token="tok",
            tracker_path=None,
        )
        sync.start()
        sync.queue_sync(["file.txt"], "no tracker")
        time.sleep(0.5)
        sync.stop()
        # Should not raise


# --- Init repo tests ---


class TestInitRepo:
    """Tests for repository initialization."""

    def test_init_repo_success(
        self,
        git_sync: GitSync,
        mock_sandbox: MagicMock,
    ) -> None:
        """init_repo runs git config and clone commands."""
        result = git_sync.init_repo()
        assert result is True
        # Should have called run_bash at least 3 times
        assert mock_sandbox.run_bash.call_count >= 3

    def test_init_repo_failure(
        self,
        git_sync: GitSync,
        mock_sandbox: MagicMock,
    ) -> None:
        """init_repo returns False on failure."""
        mock_sandbox.run_bash.return_value = BashResult(
            stdout="", stderr="fatal: could not create", exit_code=128
        )
        result = git_sync.init_repo()
        assert result is False


# --- Authenticated URL tests ---


class TestAuthenticatedUrl:
    """Tests for URL authentication."""

    def test_https_url(self, git_sync: GitSync) -> None:
        """HTTPS URL gets token injected."""
        url = git_sync._authenticated_url()
        assert url == "https://ghp_test_token@github.com/netanel-systems/nathan-brain"

    def test_non_https_url(self, mock_sandbox: MagicMock) -> None:
        """Non-HTTPS URL is returned unchanged."""
        sync = GitSync(
            sandbox=mock_sandbox,
            repo_url="git@github.com:org/repo.git",
            token="tok",
        )
        url = sync._authenticated_url()
        assert url == "git@github.com:org/repo.git"
