"""Tests for cost tracking (cost.py).

Tests budget enforcement, cost calculations, logging, and daily summaries.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from social_agent.cost import CostEntry, CostTracker

# --- Fixtures ---


@pytest.fixture
def cost_log_path(tmp_path: Path) -> Path:
    """Temporary cost log file path."""
    return tmp_path / "logs" / "cost.jsonl"


@pytest.fixture
def tracker(cost_log_path: Path) -> CostTracker:
    """CostTracker with default settings and log path."""
    return CostTracker(
        cost_log_path=cost_log_path,
        budget_limit_usd=50.0,
        cost_alert_threshold=0.8,
    )


# --- CostEntry tests ---


class TestCostEntry:
    """Tests for CostEntry dataclass."""

    def test_creation(self) -> None:
        """CostEntry stores all fields."""
        entry = CostEntry(
            timestamp="2026-02-16T12:00:00Z",
            source="llm",
            detail="moltbook-decide",
            tokens=500,
            duration_s=0.0,
            cost_usd=0.0002,
        )
        assert entry.source == "llm"
        assert entry.detail == "moltbook-decide"
        assert entry.tokens == 500

    def test_frozen(self) -> None:
        """CostEntry is immutable."""
        entry = CostEntry(
            timestamp="2026-02-16T12:00:00Z",
            source="llm",
            detail="test",
            tokens=0,
            duration_s=0.0,
            cost_usd=0.0,
        )
        with pytest.raises(AttributeError):
            entry.source = "changed"  # type: ignore[misc]


# --- Initial state tests ---


class TestInitialState:
    """Tests for CostTracker initial state."""

    def test_defaults(self) -> None:
        """CostTracker has zero costs initially."""
        tracker = CostTracker()
        assert tracker.total_cost_usd == 0.0
        assert tracker.within_budget is True
        assert tracker.alert_triggered is False

    def test_custom_budget(self) -> None:
        """Custom budget is respected."""
        tracker = CostTracker(budget_limit_usd=10.0)
        assert tracker.budget_remaining_usd == 10.0

    def test_stats_initial(self, tracker: CostTracker) -> None:
        """Initial stats show zeros."""
        stats = tracker.stats
        assert stats["total_llm_calls"] == 0
        assert stats["total_tokens"] == 0
        assert stats["total_e2b_seconds"] == 0.0
        assert stats["total_cost_usd"] == 0.0
        assert stats["within_budget"] is True
        assert stats["alert_triggered"] is False


# --- LLM cost recording tests ---


class TestLLMCostRecording:
    """Tests for recording LLM call costs."""

    def test_record_single_call(self, tracker: CostTracker) -> None:
        """Recording an LLM call updates totals."""
        entry = tracker.record_llm_call("moltbook-decide", tokens_estimated=1000)
        assert entry.source == "llm"
        assert entry.detail == "moltbook-decide"
        assert entry.tokens == 1000
        assert entry.cost_usd > 0

    def test_cost_calculation(self, tracker: CostTracker) -> None:
        """Cost is calculated correctly from tokens."""
        # 1M tokens at default $0.40/1M = $0.40
        tracker.record_llm_call("test", tokens_estimated=1_000_000)
        assert tracker.total_cost_usd == pytest.approx(0.40, abs=0.01)

    def test_multiple_calls_accumulate(self, tracker: CostTracker) -> None:
        """Multiple calls accumulate in totals."""
        tracker.record_llm_call("ns1", tokens_estimated=500)
        tracker.record_llm_call("ns2", tokens_estimated=500)
        assert tracker.stats["total_llm_calls"] == 2
        assert tracker.stats["total_tokens"] == 1000

    def test_zero_tokens(self, tracker: CostTracker) -> None:
        """Zero tokens produces zero cost."""
        entry = tracker.record_llm_call("test", tokens_estimated=0)
        assert entry.cost_usd == 0.0

    def test_negative_tokens_rejected(self, tracker: CostTracker) -> None:
        """Negative tokens raises ValueError."""
        with pytest.raises(ValueError, match="tokens_estimated"):
            tracker.record_llm_call("test", tokens_estimated=-100)


# --- E2B cost recording tests ---


class TestE2BCostRecording:
    """Tests for recording E2B sandbox costs."""

    def test_record_e2b_time(self, tracker: CostTracker) -> None:
        """Recording E2B time updates totals."""
        entry = tracker.record_e2b_time(60.0)
        assert entry.source == "e2b"
        assert entry.detail == "sandbox"
        assert entry.duration_s == 60.0
        assert entry.cost_usd > 0

    def test_e2b_cost_calculation(self, tracker: CostTracker) -> None:
        """E2B cost is calculated correctly."""
        # 1 hour at default $0.16/hour = $0.16
        tracker.record_e2b_time(3600.0)
        assert tracker.total_cost_usd == pytest.approx(0.16, abs=0.01)

    def test_e2b_seconds_accumulate(self, tracker: CostTracker) -> None:
        """Multiple E2B recordings accumulate."""
        tracker.record_e2b_time(30.0)
        tracker.record_e2b_time(30.0)
        assert tracker.stats["total_e2b_seconds"] == 60.0

    def test_zero_seconds(self, tracker: CostTracker) -> None:
        """Zero seconds produces zero cost."""
        entry = tracker.record_e2b_time(0.0)
        assert entry.cost_usd == 0.0

    def test_negative_seconds_rejected(self, tracker: CostTracker) -> None:
        """Negative seconds raises ValueError."""
        with pytest.raises(ValueError, match="seconds"):
            tracker.record_e2b_time(-10.0)


# --- Budget enforcement tests ---


class TestBudgetEnforcement:
    """Tests for budget limits and alerts."""

    def test_within_budget(self, tracker: CostTracker) -> None:
        """Small cost stays within budget."""
        tracker.record_llm_call("test", tokens_estimated=1000)
        assert tracker.within_budget is True

    def test_budget_exceeded(self) -> None:
        """Large cost exceeds budget."""
        tracker = CostTracker(budget_limit_usd=0.001)
        tracker.record_llm_call("test", tokens_estimated=1_000_000)
        assert tracker.within_budget is False

    def test_alert_not_triggered_below_threshold(self, tracker: CostTracker) -> None:
        """Alert not triggered when below threshold."""
        # budget=50, threshold=0.8, alert at $40
        tracker.record_llm_call("test", tokens_estimated=1000)
        assert tracker.alert_triggered is False

    def test_alert_triggered_at_threshold(self) -> None:
        """Alert triggered when cost reaches threshold."""
        tracker = CostTracker(
            budget_limit_usd=1.0,
            cost_alert_threshold=0.5,
        )
        # $0.40/1M tokens * 2M = $0.80 > 50% of $1.00
        tracker.record_llm_call("test", tokens_estimated=2_000_000)
        assert tracker.alert_triggered is True

    def test_budget_remaining(self) -> None:
        """Budget remaining decreases with usage."""
        tracker = CostTracker(budget_limit_usd=10.0)
        tracker.record_llm_call("test", tokens_estimated=1_000_000)
        # $0.40 spent → $9.60 remaining
        assert tracker.budget_remaining_usd == pytest.approx(9.60, abs=0.01)

    def test_budget_remaining_never_negative(self) -> None:
        """Budget remaining floors at zero."""
        tracker = CostTracker(budget_limit_usd=0.001)
        tracker.record_llm_call("test", tokens_estimated=1_000_000)
        assert tracker.budget_remaining_usd == 0.0


# --- Daily summary tests ---


class TestDailySummary:
    """Tests for daily cost summary."""

    def test_empty_summary(self, tracker: CostTracker) -> None:
        """Empty tracker produces zero summary."""
        summary = tracker.daily_summary()
        assert summary["llm_calls"] == 0
        assert summary["llm_tokens"] == 0
        assert summary["e2b_seconds"] == 0.0
        assert summary["total_cost_usd"] == 0.0
        assert summary["budget_used_pct"] == 0.0

    def test_summary_with_usage(self, tracker: CostTracker) -> None:
        """Summary reflects actual usage."""
        tracker.record_llm_call("ns1", tokens_estimated=1000)
        tracker.record_e2b_time(60.0)
        summary = tracker.daily_summary()
        assert summary["llm_calls"] == 1
        assert summary["llm_tokens"] == 1000
        assert summary["e2b_seconds"] == 60.0
        assert summary["total_cost_usd"] > 0

    def test_budget_used_pct(self) -> None:
        """Budget used percentage is calculated correctly."""
        tracker = CostTracker(budget_limit_usd=1.0)
        # Spend $0.40 out of $1.00 = 40%
        tracker.record_llm_call("test", tokens_estimated=1_000_000)
        summary = tracker.daily_summary()
        assert summary["budget_used_pct"] == pytest.approx(40.0, abs=1.0)

    def test_budget_used_pct_zero_budget(self) -> None:
        """Zero budget doesn't cause division by zero."""
        # budget_limit_usd must be positive per validator,
        # but CostTracker accepts any float
        tracker = CostTracker(budget_limit_usd=0.0)
        summary = tracker.daily_summary()
        assert summary["budget_used_pct"] == 0.0


# --- Cost log tests ---


class TestCostLog:
    """Tests for cost.jsonl logging."""

    def test_llm_entry_logged(
        self,
        tracker: CostTracker,
        cost_log_path: Path,
    ) -> None:
        """LLM call is logged to cost.jsonl."""
        tracker.record_llm_call("moltbook-decide", tokens_estimated=500)
        assert cost_log_path.exists()
        lines = cost_log_path.read_text().strip().split("\n")
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["source"] == "llm"
        assert record["detail"] == "moltbook-decide"
        assert record["tokens"] == 500

    def test_e2b_entry_logged(
        self,
        tracker: CostTracker,
        cost_log_path: Path,
    ) -> None:
        """E2B usage is logged to cost.jsonl."""
        tracker.record_e2b_time(30.0)
        assert cost_log_path.exists()
        record = json.loads(cost_log_path.read_text().strip())
        assert record["source"] == "e2b"
        assert record["duration_s"] == 30.0

    def test_multiple_entries_logged(
        self,
        tracker: CostTracker,
        cost_log_path: Path,
    ) -> None:
        """Multiple entries produce multiple lines."""
        tracker.record_llm_call("ns1", tokens_estimated=100)
        tracker.record_llm_call("ns2", tokens_estimated=200)
        tracker.record_e2b_time(10.0)
        lines = cost_log_path.read_text().strip().split("\n")
        assert len(lines) == 3

    def test_no_log_path(self) -> None:
        """Tracker works without a log path."""
        tracker = CostTracker(cost_log_path=None)
        tracker.record_llm_call("test", tokens_estimated=100)
        tracker.record_e2b_time(10.0)
        # Should not raise
        assert tracker.stats["total_llm_calls"] == 1


# --- Mixed cost tests ---


class TestMixedCosts:
    """Tests for combined LLM + E2B costs."""

    def test_total_combines_both(self, tracker: CostTracker) -> None:
        """Total cost includes both LLM and E2B."""
        tracker.record_llm_call("test", tokens_estimated=1_000_000)
        llm_cost = tracker.total_cost_usd
        tracker.record_e2b_time(3600.0)
        total = tracker.total_cost_usd
        assert total > llm_cost

    def test_stats_after_mixed(self, tracker: CostTracker) -> None:
        """Stats correctly reflect mixed usage."""
        tracker.record_llm_call("ns1", tokens_estimated=500)
        tracker.record_e2b_time(30.0)
        stats = tracker.stats
        assert stats["total_llm_calls"] == 1
        assert stats["total_tokens"] == 500
        assert stats["total_e2b_seconds"] == 30.0
        assert stats["total_cost_usd"] > 0


# --- Custom pricing tests ---


class TestCustomPricing:
    """Tests for custom pricing configuration."""

    def test_custom_llm_pricing(self) -> None:
        """Custom LLM pricing is used in calculations."""
        tracker = CostTracker(llm_cost_per_1m_tokens=1.0)
        tracker.record_llm_call("test", tokens_estimated=1_000_000)
        assert tracker.total_cost_usd == pytest.approx(1.0, abs=0.01)

    def test_custom_e2b_pricing(self) -> None:
        """Custom E2B pricing is used in calculations."""
        tracker = CostTracker(e2b_cost_per_hour=1.0)
        tracker.record_e2b_time(3600.0)
        assert tracker.total_cost_usd == pytest.approx(1.0, abs=0.01)
