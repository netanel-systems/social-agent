"""Dashboard data layer — reads activity logs, state, and brain stats.

Provides aggregated metrics for monitoring the agent's performance.
This module is read-only: it reads from activity.jsonl and state.json,
never modifies them. A future web dashboard or CLI viewer calls this.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

    from social_agent.brain import AgentBrain

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ActionStats:
    """Aggregated stats for a single action type."""

    action: str
    total: int = 0
    successes: int = 0
    failures: int = 0
    avg_quality: float = 0.0

    @property
    def success_rate(self) -> float:
        """Success rate as a percentage (0-100)."""
        if self.total == 0:
            return 0.0
        return (self.successes / self.total) * 100


@dataclass(frozen=True)
class DashboardData:
    """Complete dashboard snapshot. Immutable, safe to serialize."""

    # Agent state
    cycle_count: int = 0
    posts_today: int = 0
    replies_today: int = 0
    consecutive_failures: int = 0

    # Aggregated metrics
    total_actions: int = 0
    total_successes: int = 0
    total_failures: int = 0
    overall_success_rate: float = 0.0
    avg_quality_score: float = 0.0

    # Per-action breakdown
    action_stats: dict[str, ActionStats] = field(default_factory=dict)

    # Brain learning stats (per namespace)
    brain_stats: dict[str, dict[str, Any]] = field(default_factory=dict)

    # Recent activity (last N records)
    recent_activity: list[dict[str, Any]] = field(default_factory=list)


def load_activity_log(
    log_path: Path, *, max_records: int = 1000
) -> list[dict[str, Any]]:
    """Load activity records from JSONL file.

    Args:
        log_path: Path to activity.jsonl.
        max_records: Max records to load (most recent first).

    Returns:
        List of activity records as dicts.
    """
    if not log_path.exists():
        return []

    records: list[dict[str, Any]] = []
    try:
        with open(log_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    logger.warning("Skipping malformed log line")
    except Exception:
        logger.exception("Failed to read activity log: %s", log_path)
        return []

    # Return most recent records (tail of file)
    if len(records) > max_records:
        records = records[-max_records:]
    return records


def compute_action_stats(records: list[dict[str, Any]]) -> dict[str, ActionStats]:
    """Compute per-action statistics from activity records.

    Args:
        records: Activity records from load_activity_log().

    Returns:
        Dict mapping action name to ActionStats.
    """
    action_data: dict[str, dict[str, Any]] = {}

    for record in records:
        action = record.get("action", "UNKNOWN")
        if action not in action_data:
            action_data[action] = {
                "total": 0,
                "successes": 0,
                "failures": 0,
                "quality_scores": [],
            }

        data = action_data[action]
        data["total"] += 1
        if record.get("success"):
            data["successes"] += 1
        else:
            data["failures"] += 1

        score = record.get("quality_score")
        if score is not None:
            data["quality_scores"].append(score)

    result: dict[str, ActionStats] = {}
    for action, data in action_data.items():
        scores = data["quality_scores"]
        avg_quality = sum(scores) / len(scores) if scores else 0.0
        result[action] = ActionStats(
            action=action,
            total=data["total"],
            successes=data["successes"],
            failures=data["failures"],
            avg_quality=avg_quality,
        )

    return result


def build_dashboard(
    *,
    state_path: Path,
    log_path: Path,
    brain: AgentBrain | None = None,
    recent_count: int = 20,
) -> DashboardData:
    """Build a complete dashboard snapshot.

    Reads state, activity log, and brain stats to produce
    an immutable DashboardData object for display.

    Args:
        state_path: Path to state.json.
        log_path: Path to activity.jsonl.
        brain: Optional AgentBrain for learning stats.
        recent_count: Number of recent records to include.

    Returns:
        DashboardData with all aggregated metrics.
    """
    from social_agent.agent import AgentState

    # Load state
    state = AgentState.load(state_path)

    # Load activity records
    records = load_activity_log(log_path)

    # Compute per-action stats
    action_stats = compute_action_stats(records)

    # Overall metrics
    total_actions = sum(s.total for s in action_stats.values())
    total_successes = sum(s.successes for s in action_stats.values())
    total_failures = sum(s.failures for s in action_stats.values())
    overall_success_rate = (
        (total_successes / total_actions * 100) if total_actions > 0 else 0.0
    )

    # Average quality across all scored actions
    all_scores = [
        r["quality_score"]
        for r in records
        if r.get("quality_score") is not None
    ]
    avg_quality = sum(all_scores) / len(all_scores) if all_scores else 0.0

    # Brain stats
    brain_data: dict[str, dict[str, Any]] = {}
    if brain is not None:
        brain_data = brain.all_stats()

    # Recent activity
    recent = records[-recent_count:] if len(records) > recent_count else records
    recent.reverse()  # Most recent first

    return DashboardData(
        cycle_count=state.cycle_count,
        posts_today=state.posts_today,
        replies_today=state.replies_today,
        consecutive_failures=state.consecutive_failures,
        total_actions=total_actions,
        total_successes=total_successes,
        total_failures=total_failures,
        overall_success_rate=overall_success_rate,
        avg_quality_score=avg_quality,
        action_stats=action_stats,
        brain_stats=brain_data,
        recent_activity=recent,
    )


def format_dashboard(data: DashboardData) -> str:
    """Format dashboard data as a human-readable string for CLI display.

    Args:
        data: DashboardData from build_dashboard().

    Returns:
        Formatted string with all metrics.
    """
    lines = [
        "=" * 60,
        "  SOCIAL AGENT DASHBOARD",
        "=" * 60,
        "",
        "--- Agent State ---",
        f"  Cycles completed:      {data.cycle_count}",
        f"  Posts today:            {data.posts_today}",
        f"  Replies today:          {data.replies_today}",
        f"  Consecutive failures:   {data.consecutive_failures}",
        "",
        "--- Overall Metrics ---",
        f"  Total actions:          {data.total_actions}",
        f"  Successes:              {data.total_successes}",
        f"  Failures:               {data.total_failures}",
        f"  Success rate:           {data.overall_success_rate:.1f}%",
        f"  Avg quality score:      {data.avg_quality_score:.2f}",
        "",
    ]

    if data.action_stats:
        lines.append("--- Per-Action Breakdown ---")
        for action, stats in sorted(data.action_stats.items()):
            lines.append(
                f"  {action:<15} "
                f"total={stats.total:>3}  "
                f"ok={stats.successes:>3}  "
                f"fail={stats.failures:>3}  "
                f"rate={stats.success_rate:.0f}%  "
                f"quality={stats.avg_quality:.2f}"
            )
        lines.append("")

    if data.brain_stats:
        lines.append("--- Brain Learning ---")
        for ns, brain_info in sorted(data.brain_stats.items()):
            calls = brain_info.get("total_calls", 0)
            learnings = brain_info.get("total_learnings_stored", 0)
            init = brain_info.get("initialized", False)
            status = "active" if init else "pending"
            lines.append(
                f"  {ns:<22} "
                f"calls={calls:>3}  "
                f"learnings={learnings:>3}  "
                f"[{status}]"
            )
        lines.append("")

    if data.recent_activity:
        lines.append("--- Recent Activity ---")
        for record in data.recent_activity[:10]:
            ts = record.get("timestamp", "?")[:19]
            action = record.get("action", "?")
            success = "OK" if record.get("success") else "FAIL"
            details = record.get("details", "")[:40]
            lines.append(f"  [{ts}] {action:<15} {success:<4} {details}")
        lines.append("")

    lines.append("=" * 60)
    return "\n".join(lines)
