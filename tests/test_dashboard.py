"""Tests for social_agent.dashboard — dashboard data layer."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from social_agent.dashboard import (
    ActionStats,
    DashboardData,
    build_dashboard,
    compute_action_stats,
    format_dashboard,
    load_activity_log,
)

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# ActionStats
# ---------------------------------------------------------------------------


class TestActionStats:
    """Tests for ActionStats dataclass."""

    def test_success_rate_zero_total(self) -> None:
        stats = ActionStats(action="READ_FEED", total=0, successes=0, failures=0)
        assert stats.success_rate == 0.0

    def test_success_rate_all_success(self) -> None:
        stats = ActionStats(action="CREATE_POST", total=10, successes=10, failures=0)
        assert stats.success_rate == 100.0

    def test_success_rate_partial(self) -> None:
        stats = ActionStats(action="REPLY", total=10, successes=7, failures=3)
        assert stats.success_rate == pytest.approx(70.0)

    def test_frozen(self) -> None:
        stats = ActionStats(action="ANALYZE", total=5)
        with pytest.raises(AttributeError):
            stats.total = 10  # type: ignore[misc]

    def test_default_avg_quality(self) -> None:
        stats = ActionStats(action="READ_FEED", total=1, successes=1)
        assert stats.avg_quality == 0.0


# ---------------------------------------------------------------------------
# DashboardData
# ---------------------------------------------------------------------------


class TestDashboardData:
    """Tests for DashboardData dataclass."""

    def test_defaults(self) -> None:
        data = DashboardData()
        assert data.cycle_count == 0
        assert data.total_actions == 0
        assert data.action_stats == {}
        assert data.brain_stats == {}
        assert data.recent_activity == []

    def test_frozen(self) -> None:
        data = DashboardData()
        with pytest.raises(AttributeError):
            data.cycle_count = 5  # type: ignore[misc]


# ---------------------------------------------------------------------------
# load_activity_log
# ---------------------------------------------------------------------------


class TestLoadActivityLog:
    """Tests for loading JSONL activity logs."""

    def test_missing_file(self, tmp_path: Path) -> None:
        result = load_activity_log(tmp_path / "nonexistent.jsonl")
        assert result == []

    def test_empty_file(self, tmp_path: Path) -> None:
        log_file = tmp_path / "activity.jsonl"
        log_file.write_text("")
        result = load_activity_log(log_file)
        assert result == []

    def test_single_record(self, tmp_path: Path) -> None:
        log_file = tmp_path / "activity.jsonl"
        record = {"action": "READ_FEED", "success": True, "quality_score": 0.8}
        log_file.write_text(json.dumps(record) + "\n")
        result = load_activity_log(log_file)
        assert len(result) == 1
        assert result[0]["action"] == "READ_FEED"

    def test_multiple_records(self, tmp_path: Path) -> None:
        log_file = tmp_path / "activity.jsonl"
        records = [
            {"action": "READ_FEED", "success": True},
            {"action": "CREATE_POST", "success": True, "quality_score": 0.9},
            {"action": "REPLY", "success": False},
        ]
        log_file.write_text("\n".join(json.dumps(r) for r in records) + "\n")
        result = load_activity_log(log_file)
        assert len(result) == 3

    def test_max_records_truncation(self, tmp_path: Path) -> None:
        log_file = tmp_path / "activity.jsonl"
        records = [{"action": f"ACTION_{i}", "success": True} for i in range(50)]
        log_file.write_text("\n".join(json.dumps(r) for r in records) + "\n")
        result = load_activity_log(log_file, max_records=10)
        assert len(result) == 10
        # Should keep most recent (tail)
        assert result[0]["action"] == "ACTION_40"
        assert result[-1]["action"] == "ACTION_49"

    def test_malformed_line_skipped(self, tmp_path: Path) -> None:
        log_file = tmp_path / "activity.jsonl"
        lines = [
            json.dumps({"action": "READ_FEED", "success": True}),
            "NOT VALID JSON {{{",
            json.dumps({"action": "REPLY", "success": False}),
        ]
        log_file.write_text("\n".join(lines) + "\n")
        result = load_activity_log(log_file)
        assert len(result) == 2

    def test_blank_lines_skipped(self, tmp_path: Path) -> None:
        log_file = tmp_path / "activity.jsonl"
        record = json.dumps({"action": "READ_FEED", "success": True})
        log_file.write_text(f"\n\n{record}\n\n")
        result = load_activity_log(log_file)
        assert len(result) == 1

    def test_permission_error_returns_empty(self, tmp_path: Path) -> None:
        log_file = tmp_path / "activity.jsonl"
        log_file.write_text(json.dumps({"action": "X"}) + "\n")
        with patch("builtins.open", side_effect=PermissionError("denied")):
            result = load_activity_log(log_file)
        assert result == []


# ---------------------------------------------------------------------------
# compute_action_stats
# ---------------------------------------------------------------------------


class TestComputeActionStats:
    """Tests for per-action statistics computation."""

    def test_empty_records(self) -> None:
        result = compute_action_stats([])
        assert result == {}

    def test_single_action_type(self) -> None:
        records = [
            {"action": "READ_FEED", "success": True, "quality_score": 0.8},
            {"action": "READ_FEED", "success": True, "quality_score": 0.9},
            {"action": "READ_FEED", "success": False},
        ]
        result = compute_action_stats(records)
        assert "READ_FEED" in result
        stats = result["READ_FEED"]
        assert stats.total == 3
        assert stats.successes == 2
        assert stats.failures == 1
        assert stats.avg_quality == pytest.approx(0.85)

    def test_multiple_action_types(self) -> None:
        records = [
            {"action": "READ_FEED", "success": True},
            {"action": "CREATE_POST", "success": True},
            {"action": "REPLY", "success": False},
        ]
        result = compute_action_stats(records)
        assert len(result) == 3
        assert result["READ_FEED"].total == 1
        assert result["CREATE_POST"].successes == 1
        assert result["REPLY"].failures == 1

    def test_missing_action_key(self) -> None:
        records = [{"success": True}]
        result = compute_action_stats(records)
        assert "UNKNOWN" in result

    def test_no_quality_scores(self) -> None:
        records = [{"action": "ANALYZE", "success": True}]
        result = compute_action_stats(records)
        assert result["ANALYZE"].avg_quality == 0.0

    def test_quality_average(self) -> None:
        records = [
            {"action": "CREATE_POST", "success": True, "quality_score": 0.6},
            {"action": "CREATE_POST", "success": True, "quality_score": 0.8},
            {"action": "CREATE_POST", "success": True, "quality_score": 1.0},
        ]
        result = compute_action_stats(records)
        assert result["CREATE_POST"].avg_quality == pytest.approx(0.8)


# ---------------------------------------------------------------------------
# build_dashboard
# ---------------------------------------------------------------------------


class TestBuildDashboard:
    """Tests for building the full dashboard snapshot."""

    def _make_state_file(self, tmp_path: Path) -> Path:
        """Create a minimal state.json for testing."""
        state_path = tmp_path / "state.json"
        state = {
            "posts_today": 3,
            "replies_today": 7,
            "cycle_count": 42,
            "consecutive_failures": 1,
            "last_reset_date": "2026-02-15",
        }
        state_path.write_text(json.dumps(state))
        return state_path

    def _make_log_file(
        self, tmp_path: Path, records: list[dict] | None = None
    ) -> Path:
        """Create an activity.jsonl for testing."""
        log_path = tmp_path / "activity.jsonl"
        if records is None:
            records = []
        log_path.write_text("\n".join(json.dumps(r) for r in records) + "\n")
        return log_path

    def test_empty_log(self, tmp_path: Path) -> None:
        state_path = self._make_state_file(tmp_path)
        log_path = tmp_path / "empty.jsonl"
        # File doesn't exist — should still work
        data = build_dashboard(state_path=state_path, log_path=log_path)
        assert data.cycle_count == 42
        assert data.posts_today == 3
        assert data.total_actions == 0
        assert data.overall_success_rate == 0.0

    def test_with_records(self, tmp_path: Path) -> None:
        state_path = self._make_state_file(tmp_path)
        records = [
            {"action": "READ_FEED", "success": True, "quality_score": 0.8},
            {"action": "CREATE_POST", "success": True, "quality_score": 0.9},
            {"action": "REPLY", "success": False},
        ]
        log_path = self._make_log_file(tmp_path, records)
        data = build_dashboard(state_path=state_path, log_path=log_path)
        assert data.total_actions == 3
        assert data.total_successes == 2
        assert data.total_failures == 1
        assert data.overall_success_rate == pytest.approx(66.666, rel=0.01)
        assert data.avg_quality_score == pytest.approx(0.85)
        assert len(data.action_stats) == 3

    def test_recent_activity_limited(self, tmp_path: Path) -> None:
        state_path = self._make_state_file(tmp_path)
        records = [{"action": f"A_{i}", "success": True} for i in range(50)]
        log_path = self._make_log_file(tmp_path, records)
        data = build_dashboard(
            state_path=state_path, log_path=log_path, recent_count=5
        )
        assert len(data.recent_activity) == 5
        # Most recent first (reversed)
        assert data.recent_activity[0]["action"] == "A_49"

    def test_brain_stats_included(self, tmp_path: Path) -> None:
        state_path = self._make_state_file(tmp_path)
        log_path = self._make_log_file(tmp_path)
        brain = MagicMock()
        brain.all_stats.return_value = {
            "moltbook-decide": {"total_calls": 10, "initialized": True},
        }
        data = build_dashboard(
            state_path=state_path, log_path=log_path, brain=brain
        )
        assert "moltbook-decide" in data.brain_stats
        assert data.brain_stats["moltbook-decide"]["total_calls"] == 10

    def test_no_brain(self, tmp_path: Path) -> None:
        state_path = self._make_state_file(tmp_path)
        log_path = self._make_log_file(tmp_path)
        data = build_dashboard(state_path=state_path, log_path=log_path, brain=None)
        assert data.brain_stats == {}

    def test_missing_state_file(self, tmp_path: Path) -> None:
        state_path = tmp_path / "nonexistent_state.json"
        log_path = self._make_log_file(tmp_path)
        # AgentState.load should handle missing file (returns defaults)
        data = build_dashboard(state_path=state_path, log_path=log_path)
        assert data.cycle_count == 0
        assert data.posts_today == 0


# ---------------------------------------------------------------------------
# format_dashboard
# ---------------------------------------------------------------------------


class TestFormatDashboard:
    """Tests for CLI formatting of dashboard data."""

    def test_empty_dashboard(self) -> None:
        data = DashboardData()
        output = format_dashboard(data)
        assert "SOCIAL AGENT DASHBOARD" in output
        assert "Cycles completed:      0" in output
        assert "Total actions:          0" in output

    def test_with_action_stats(self) -> None:
        data = DashboardData(
            total_actions=10,
            action_stats={
                "READ_FEED": ActionStats(
                    action="READ_FEED", total=5, successes=4, failures=1,
                    avg_quality=0.82,
                ),
            },
        )
        output = format_dashboard(data)
        assert "Per-Action Breakdown" in output
        assert "READ_FEED" in output
        assert "total=  5" in output

    def test_with_brain_stats(self) -> None:
        data = DashboardData(
            brain_stats={
                "moltbook-decide": {
                    "total_calls": 15,
                    "total_learnings_stored": 3,
                    "initialized": True,
                },
            },
        )
        output = format_dashboard(data)
        assert "Brain Learning" in output
        assert "moltbook-decide" in output
        assert "calls= 15" in output
        assert "[active]" in output

    def test_with_recent_activity(self) -> None:
        data = DashboardData(
            recent_activity=[
                {
                    "timestamp": "2026-02-15T10:30:00.000Z",
                    "action": "CREATE_POST",
                    "success": True,
                    "details": "Posted about AI agents",
                },
                {
                    "timestamp": "2026-02-15T10:25:00.000Z",
                    "action": "READ_FEED",
                    "success": False,
                    "details": "Timeout",
                },
            ],
        )
        output = format_dashboard(data)
        assert "Recent Activity" in output
        assert "CREATE_POST" in output
        assert "OK" in output
        assert "FAIL" in output

    def test_recent_activity_truncated_to_ten(self) -> None:
        records = [
            {"timestamp": f"2026-02-15T{i:02d}:00:00", "action": f"A_{i}", "success": True}
            for i in range(15)
        ]
        data = DashboardData(recent_activity=records)
        output = format_dashboard(data)
        # format_dashboard shows at most 10 recent
        assert "A_0" in output
        assert "A_9" in output
        assert "A_10" not in output

    def test_brain_stats_pending_status(self) -> None:
        data = DashboardData(
            brain_stats={
                "moltbook-content": {
                    "total_calls": 0,
                    "total_learnings_stored": 0,
                    "initialized": False,
                },
            },
        )
        output = format_dashboard(data)
        assert "[pending]" in output

    def test_output_is_string(self) -> None:
        data = DashboardData()
        output = format_dashboard(data)
        assert isinstance(output, str)

    def test_separator_lines(self) -> None:
        data = DashboardData()
        output = format_dashboard(data)
        lines = output.split("\n")
        assert lines[0] == "=" * 60
        assert lines[-1] == "=" * 60
