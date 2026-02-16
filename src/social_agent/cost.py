"""Cost tracking for LLM calls and E2B sandbox time.

Tracks estimated token usage and sandbox duration to provide
budget awareness and prevent runaway costs. Uses conservative
estimates — better to overestimate than underestimate.

Pricing is configurable but defaults to gpt-4o-mini + E2B rates.
This is for budget awareness, not billing accuracy.

Usage:
    tracker = CostTracker(cost_log_path=Path("logs/cost.jsonl"))
    tracker.record_llm_call("moltbook-decide", tokens_estimated=500)
    tracker.record_e2b_time(30.0)
    if not tracker.within_budget:
        logger.warning("Budget exceeded!")
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger("social_agent.cost")

# Default pricing (per 1M tokens / per hour).
# gpt-4o-mini: $0.15/1M input, $0.60/1M output.
# Blended estimate: assume ~60% input, ~40% output → ~$0.33/1M.
# We round up to $0.40/1M for safety margin.
_DEFAULT_LLM_COST_PER_1M_TOKENS = 0.40
# E2B sandbox: ~$0.16/hour (Hobby tier).
_DEFAULT_E2B_COST_PER_HOUR = 0.16


@dataclass(frozen=True)
class CostEntry:
    """A single cost event logged to cost.jsonl."""

    timestamp: str
    source: str  # "llm" or "e2b"
    detail: str  # namespace or "sandbox"
    tokens: int
    duration_s: float
    cost_usd: float


@dataclass
class CostTracker:
    """Tracks estimated costs for LLM calls and E2B sandbox time.

    Maintains running totals and logs each cost event to a JSONL file.
    Provides budget checking with configurable limits and alert thresholds.

    Args:
        cost_log_path: Path to cost.jsonl log file (None to disable logging).
        budget_limit_usd: Maximum budget in USD.
        cost_alert_threshold: Fraction of budget that triggers an alert (0.0-1.0).
        llm_cost_per_1m_tokens: LLM cost per 1M tokens (blended in/out).
        e2b_cost_per_hour: E2B sandbox cost per hour.
    """

    cost_log_path: Path | None = None
    budget_limit_usd: float = 50.0
    cost_alert_threshold: float = 0.8
    llm_cost_per_1m_tokens: float = _DEFAULT_LLM_COST_PER_1M_TOKENS
    e2b_cost_per_hour: float = _DEFAULT_E2B_COST_PER_HOUR

    # Running totals (not constructor args)
    _total_llm_calls: int = field(default=0, init=False, repr=False)
    _total_tokens: int = field(default=0, init=False, repr=False)
    _total_e2b_seconds: float = field(default=0.0, init=False, repr=False)
    _total_cost_usd: float = field(default=0.0, init=False, repr=False)

    @property
    def total_cost_usd(self) -> float:
        """Total estimated cost in USD."""
        return round(self._total_cost_usd, 6)

    @property
    def within_budget(self) -> bool:
        """Check if total cost is within budget limit."""
        return self._total_cost_usd <= self.budget_limit_usd

    @property
    def alert_triggered(self) -> bool:
        """Check if cost has exceeded the alert threshold."""
        return self._total_cost_usd >= (
            self.budget_limit_usd * self.cost_alert_threshold
        )

    @property
    def budget_remaining_usd(self) -> float:
        """Remaining budget in USD."""
        return round(max(0.0, self.budget_limit_usd - self._total_cost_usd), 6)

    @property
    def stats(self) -> dict[str, object]:
        """Return cost statistics summary."""
        return {
            "total_llm_calls": self._total_llm_calls,
            "total_tokens": self._total_tokens,
            "total_e2b_seconds": round(self._total_e2b_seconds, 1),
            "total_cost_usd": self.total_cost_usd,
            "budget_limit_usd": self.budget_limit_usd,
            "budget_remaining_usd": self.budget_remaining_usd,
            "within_budget": self.within_budget,
            "alert_triggered": self.alert_triggered,
        }

    def record_llm_call(
        self,
        namespace: str,
        tokens_estimated: int,
    ) -> CostEntry:
        """Record an LLM call and its estimated cost.

        Args:
            namespace: The brain namespace (e.g. "moltbook-decide").
            tokens_estimated: Estimated token count from CallResult.metadata.

        Returns:
            The logged CostEntry.
        """
        cost = (tokens_estimated / 1_000_000) * self.llm_cost_per_1m_tokens

        self._total_llm_calls += 1
        self._total_tokens += tokens_estimated
        self._total_cost_usd += cost

        entry = CostEntry(
            timestamp=self._now_iso(),
            source="llm",
            detail=namespace,
            tokens=tokens_estimated,
            duration_s=0.0,
            cost_usd=round(cost, 8),
        )
        self._log_entry(entry)
        return entry

    def record_e2b_time(self, seconds: float) -> CostEntry:
        """Record E2B sandbox usage time and its estimated cost.

        Args:
            seconds: Duration of sandbox usage in seconds.

        Returns:
            The logged CostEntry.
        """
        cost = (seconds / 3600) * self.e2b_cost_per_hour

        self._total_e2b_seconds += seconds
        self._total_cost_usd += cost

        entry = CostEntry(
            timestamp=self._now_iso(),
            source="e2b",
            detail="sandbox",
            tokens=0,
            duration_s=round(seconds, 2),
            cost_usd=round(cost, 8),
        )
        self._log_entry(entry)
        return entry

    def daily_summary(self) -> dict[str, object]:
        """Return a summary suitable for logging or dashboard display."""
        llm_cost = (self._total_tokens / 1_000_000) * self.llm_cost_per_1m_tokens
        e2b_cost = (self._total_e2b_seconds / 3600) * self.e2b_cost_per_hour
        return {
            "llm_calls": self._total_llm_calls,
            "llm_tokens": self._total_tokens,
            "llm_cost_usd": round(llm_cost, 6),
            "e2b_seconds": round(self._total_e2b_seconds, 1),
            "e2b_cost_usd": round(e2b_cost, 6),
            "total_cost_usd": self.total_cost_usd,
            "budget_limit_usd": self.budget_limit_usd,
            "budget_remaining_usd": self.budget_remaining_usd,
            "budget_used_pct": round(
                (self._total_cost_usd / self.budget_limit_usd) * 100, 1
            )
            if self.budget_limit_usd > 0
            else 0.0,
        }

    # --- Internal ---

    def _log_entry(self, entry: CostEntry) -> None:
        """Append a cost entry to cost.jsonl."""
        if self.cost_log_path is None:
            return

        try:
            self.cost_log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.cost_log_path.open("a") as f:
                f.write(json.dumps(asdict(entry), default=str) + "\n")
        except Exception:
            logger.exception("Failed to log cost entry")

    @staticmethod
    def _now_iso() -> str:
        """Return current UTC time as ISO string."""
        from datetime import UTC, datetime

        return datetime.now(tz=UTC).isoformat()
