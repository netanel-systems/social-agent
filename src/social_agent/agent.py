"""Agent loop — autonomous state machine.

Deterministic Python loop. LLM makes content decisions only.
State: DECIDE -> ACT -> LEARN -> WAIT -> REPEAT.

All external actions go through E2B sandbox (via MoltbookClient).
All reasoning goes through netanel-core (via AgentBrain).
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from social_agent.brain import AgentBrain
    from social_agent.config import Settings
    from social_agent.moltbook import MoltbookClient, MoltbookPost
    from social_agent.sandbox import SandboxClient
    from social_agent.telegram import TelegramNotifier

logger = logging.getLogger(__name__)


# --- Enums ---


class Action(StrEnum):
    """Agent actions from the state machine (Architecture Section 3)."""

    READ_FEED = "READ_FEED"
    RESEARCH = "RESEARCH"
    REPLY = "REPLY"
    CREATE_POST = "CREATE_POST"
    ANALYZE = "ANALYZE"


# --- State persistence ---


@dataclass
class AgentState:
    """Persistent agent state. Saved to state.json between cycles.

    Daily counters reset automatically when the date changes.
    """

    posts_today: int = 0
    replies_today: int = 0
    cycle_count: int = 0
    consecutive_failures: int = 0
    last_reset_date: str = ""
    current_sandbox_id: str = ""  # Track active sandbox for dashboard discovery

    def reset_daily_counters(self) -> None:
        """Reset daily counters if the date has changed."""
        today = datetime.now(tz=UTC).strftime("%Y-%m-%d")
        if self.last_reset_date != today:
            self.posts_today = 0
            self.replies_today = 0
            self.last_reset_date = today
            logger.info("Daily counters reset for %s", today)

    def to_json(self) -> str:
        """Serialize state to JSON string."""
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_json(cls, text: str) -> AgentState:
        """Deserialize state from JSON string.

        Ignores unknown keys for forward compatibility.
        """
        data = json.loads(text)
        known_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known_fields}
        return cls(**filtered)

    def save(self, path: Path) -> None:
        """Save state to a JSON file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json())

    @classmethod
    def load(cls, path: Path) -> AgentState:
        """Load state from a JSON file, or return defaults if missing."""
        try:
            if path.exists():
                return cls.from_json(path.read_text())
        except (json.JSONDecodeError, TypeError):
            logger.warning("Corrupted state file, starting fresh: %s", path)
        return cls()


# --- Activity logging ---


@dataclass(frozen=True)
class ActivityRecord:
    """A single activity log entry. Appended to activity.jsonl."""

    timestamp: str
    cycle: int
    action: str
    success: bool
    quality_score: float | None = None
    details: str = ""
    error: str | None = None


# --- Cycle result ---


@dataclass(frozen=True)
class CycleResult:
    """Result of a single agent cycle. Returned by cycle() for monitoring."""

    action: str
    success: bool
    quality_score: float | None = None
    details: str = ""
    error: str | None = None


# --- Main agent ---


class Agent:
    """Autonomous agent. State machine: DECIDE -> ACT -> LEARN -> REPEAT.

    The outer loop is deterministic Python. The LLM only makes content
    decisions (what to post, what to reply, when to analyze).

    Usage::

        agent = Agent(
            settings=settings,
            brain=brain,
            moltbook=moltbook,
            notifier=notifier,
        )
        agent.run()  # Runs until max_cycles, circuit breaker, or Ctrl+C

    For testing, use ``cycle()`` directly to run a single cycle.
    """

    def __init__(
        self,
        settings: Settings,
        brain: AgentBrain,
        moltbook: MoltbookClient,
        notifier: TelegramNotifier,
        *,
        sandbox: SandboxClient | None = None,
        state_path: Path | None = None,
        activity_log_path: Path | None = None,
        heartbeat_path: Path | None = None,
        sandbox_id: str = "",
    ) -> None:
        from pathlib import Path as _Path

        self._settings = settings
        self._brain = brain
        self._moltbook = moltbook
        self._notifier = notifier
        self._sandbox = sandbox
        self._state_path = state_path or _Path("state.json")
        self._activity_log_path = activity_log_path or _Path("logs/activity.jsonl")
        self._heartbeat_path = heartbeat_path or _Path("heartbeat.json")
        self._sandbox_id = sandbox_id
        self._state = AgentState.load(self._state_path)
        self._state.consecutive_failures = 0  # Fresh start — stale failures from a dead sandbox must not carry over
        self._shutdown_requested = False
        self._recent_feed: list[MoltbookPost] = []
        self._research_context: str = ""

        self._activity_log_path.parent.mkdir(parents=True, exist_ok=True)
        self._heartbeat_path.parent.mkdir(parents=True, exist_ok=True)

        # Update state with current sandbox_id for dashboard discovery
        if self._sandbox_id and self._state.current_sandbox_id != self._sandbox_id:
            self._state.current_sandbox_id = self._sandbox_id
            self._state.save(self._state_path)
            logger.info("Updated sandbox_id in state: %s", self._sandbox_id)

            # Push to nathan-brain if git sync enabled
            if settings.git_sync_enabled and settings.brain_repo_url:
                from social_agent.git_push import push_state

                brain_path = _Path("~/nathan-brain").expanduser()
                push_state(brain_path, f"agent startup: sandbox_id={self._sandbox_id}")

    @property
    def state(self) -> AgentState:
        """Current agent state (read-only access for monitoring)."""
        return self._state

    @property
    def recent_feed(self) -> list[MoltbookPost]:
        """Recently loaded feed posts."""
        return list(self._recent_feed)

    def request_shutdown(self) -> None:
        """Request graceful shutdown after current cycle completes."""
        self._shutdown_requested = True
        logger.info("Shutdown requested")

    def should_continue(self) -> bool:
        """Check if the agent should run another cycle.

        Returns False when:
        - Shutdown was requested (Ctrl+C or request_shutdown())
        - Max cycles reached (bounded loops — JPL Rule 1)
        - Circuit breaker tripped (consecutive failures)
        """
        if self._shutdown_requested:
            logger.info("Shutdown requested")
            return False
        if self._state.cycle_count >= self._settings.max_cycles:
            logger.info("Max cycles reached (%d)", self._settings.max_cycles)
            return False
        if (
            self._state.consecutive_failures
            >= self._settings.circuit_breaker_threshold
        ):
            logger.warning(
                "Circuit breaker: %d consecutive failures",
                self._state.consecutive_failures,
            )
            return False
        return True

    def cycle(self) -> CycleResult:
        """Run a single agent cycle: DECIDE -> ACT.

        This is the testable entry point. ``run()`` calls this in a loop.
        Learning happens automatically inside brain.call() via netanel-core.

        Returns:
            CycleResult with action taken, success, and details.
        """
        self._state.cycle_count += 1
        self._state.reset_daily_counters()
        logger.info("=== Cycle %d ===", self._state.cycle_count)

        # Heartbeat: signal we're alive before deciding
        self._write_heartbeat("DECIDING")

        # DECIDE
        action = self._decide()
        if action is None:
            self._state.consecutive_failures += 1
            self._log_activity("DECIDE", success=False, details="Could not parse action")
            self._notify("Decision failed — could not parse action", "warning")
            self._write_heartbeat("IDLE")
            self._state.save(self._state_path)
            return CycleResult(
                action="DECIDE",
                success=False,
                details="Could not parse action",
            )

        # Heartbeat: signal what action we're taking
        self._write_heartbeat(action.value)

        # ACT (learning happens inside brain.call via netanel-core)
        result = self._act(action)

        if result.success:
            self._state.consecutive_failures = 0
        else:
            self._state.consecutive_failures += 1

        # Heartbeat: signal action complete
        self._write_heartbeat("IDLE")
        self._state.save(self._state_path)
        return result

    def run(self) -> None:
        """Run the agent loop until stopped.

        Stops on: max_cycles, circuit breaker, shutdown request.
        Saves state after every cycle for crash recovery.
        """
        self._notify("Agent started", "info")

        while self.should_continue():
            self.cycle()
            if self.should_continue():
                self._wait()

        self._notify(
            f"Agent stopped after {self._state.cycle_count} cycles",
            "info",
        )
        self._state.save(self._state_path)

    # --- Decision ---

    def _decide(self) -> Action | None:
        """Ask the brain what action to take.

        Builds context from current state and asks moltbook-decide namespace.
        Parses the action name from the LLM response.
        """
        context = self._build_decision_context()
        try:
            result = self._brain.call("moltbook-decide", context)
        except Exception:
            logger.exception("Brain decision call failed")
            return None

        response_upper = result.response.strip().upper()
        for action in Action:
            if action.value in response_upper:
                logger.info(
                    "Decision: %s (score: %.2f)", action.value, result.score
                )
                return action

        logger.warning(
            "Could not parse action from: %s", result.response[:100]
        )
        return None

    def _build_decision_context(self) -> str:
        """Build context string for the decision namespace."""
        parts = [
            f"Cycle: {self._state.cycle_count}",
            f"Posts today: {self._state.posts_today}/{self._settings.max_posts_per_day}",
            f"Replies today: {self._state.replies_today}/{self._settings.max_replies_per_day}",
            f"Feed posts loaded: {len(self._recent_feed)}",
            f"Research context available: {'YES' if self._research_context else 'NO'}",
        ]
        if self._state.posts_today >= self._settings.max_posts_per_day:
            parts.append("CONSTRAINT: Daily post limit reached. Cannot CREATE_POST.")
        if self._state.replies_today >= self._settings.max_replies_per_day:
            parts.append("CONSTRAINT: Daily reply limit reached. Cannot REPLY.")
        if not self._recent_feed:
            parts.append("NOTE: No feed loaded yet. Consider READ_FEED first.")
        if not self._research_context:
            parts.append("NOTE: No research done yet. Consider RESEARCH before CREATE_POST.")
        elif self._state.posts_today == 0 and self._state.cycle_count > 3:
            parts.append(
                "HINT: Research is available and no post created today. Strongly consider CREATE_POST."
            )
        return "\n".join(parts)

    # --- Action handlers ---

    _SUBMOLTS = ("agents", "aitools", "infrastructure", "general")

    def _act(self, action: Action) -> CycleResult:
        """Dispatch to the correct action handler."""
        handlers: dict[Action, Callable[[], CycleResult]] = {
            Action.READ_FEED: self._act_read_feed,
            Action.RESEARCH: self._act_research,
            Action.REPLY: self._act_reply,
            Action.CREATE_POST: self._act_create_post,
            Action.ANALYZE: self._act_analyze,
        }
        handler = handlers.get(action)
        if handler is None:
            return CycleResult(
                action=action.value, success=False, error="No handler"
            )

        try:
            return handler()
        except Exception as exc:
            logger.exception("Action %s raised", action.value)
            self._log_activity(
                action.value, success=False, error=str(exc)
            )
            return CycleResult(
                action=action.value, success=False, error=str(exc)
            )

    def _act_read_feed(self) -> CycleResult:
        """Read posts from all submolts."""
        all_posts: list[MoltbookPost] = []
        for submolt in self._SUBMOLTS:
            result = self._moltbook.get_feed(submolt, limit=5)
            if result.success:
                all_posts.extend(result.posts)
            else:
                logger.warning("Feed read failed for %s: %s", submolt, result.error)

        self._recent_feed = all_posts
        details = f"Loaded {len(all_posts)} posts from {len(self._SUBMOLTS)} submolts"
        self._log_activity("READ_FEED", success=True, details=details)
        self._notify(details, "info")
        return CycleResult(action="READ_FEED", success=True, details=details)

    # Max search results and snippet length for research.
    _MAX_SEARCH_RESULTS = 5
    _MAX_SNIPPET_LENGTH = 500

    def _act_research(self) -> CycleResult:
        """Research a topic using web search in the sandbox."""
        if self._sandbox is None:
            details = "No sandbox available for research"
            self._log_activity("RESEARCH", success=False, details=details)
            return CycleResult(action="RESEARCH", success=False, details=details)

        # Ask brain for a search query
        feed_topics = ""
        if self._recent_feed:
            feed_topics = "\n".join(f"- {p.title}" for p in self._recent_feed[:5])
        context = "Generate a research query."
        if feed_topics:
            context += f"\n\nRecent feed topics:\n{feed_topics}"
        if self._research_context:
            context += f"\n\nPrevious research (avoid duplicates):\n{self._research_context[:200]}"

        result = self._brain.call("moltbook-research", context)
        query = self._parse_research_query(result.response)
        if not query:
            details = "Could not parse search query from brain"
            self._log_activity("RESEARCH", success=False, details=details)
            return CycleResult(action="RESEARCH", success=False, details=details)

        # Run web search in sandbox
        search_results = self._sandbox_web_search(query)
        if not search_results:
            details = f"No results for: {query}"
            self._log_activity("RESEARCH", success=False, details=details)
            return CycleResult(action="RESEARCH", success=False, details=details)

        # Store research context for future posts/replies
        self._research_context = (
            f"Research on: {query}\n\n"
            + "\n\n".join(
                f"**{r['title']}**\n{r['body'][:self._MAX_SNIPPET_LENGTH]}"
                for r in search_results
            )
        )

        details = f"Researched: {query} ({len(search_results)} results)"
        self._log_activity(
            "RESEARCH", success=True, quality_score=result.score, details=details
        )
        self._notify(details, "info")
        return CycleResult(
            action="RESEARCH",
            success=True,
            quality_score=result.score,
            details=details,
        )

    @staticmethod
    def _parse_research_query(response: str) -> str:
        """Extract search query from brain's research response."""
        for line in response.strip().splitlines():
            stripped = line.strip()
            if stripped.upper().startswith("QUERY:"):
                return stripped.split(":", 1)[1].strip().strip('"')
        # Fallback: use first non-empty line
        for line in response.strip().splitlines():
            if line.strip():
                return line.strip()[:100]
        return ""

    def _sandbox_web_search(self, query: str) -> list[dict[str, str]]:
        """Run a DuckDuckGo search inside the E2B sandbox.

        Returns list of dicts with 'title', 'body', 'url' keys.
        Bounded to _MAX_SEARCH_RESULTS. All execution in sandbox.
        """
        if self._sandbox is None:
            return []

        # Build search code — safe: query is embedded as repr()
        search_code = (
            "from duckduckgo_search import DDGS\n"
            "import json\n"
            "results = []\n"
            "try:\n"
            "    with DDGS() as ddgs:\n"
            f"        for r in ddgs.text({query!r}, max_results={self._MAX_SEARCH_RESULTS}):\n"
            "            results.append({\n"
            '                "title": r.get("title", ""),\n'
            '                "body": r.get("body", ""),\n'
            '                "url": r.get("href", ""),\n'
            "            })\n"
            "except Exception as e:\n"
            '    results = [{"title": "Search error", "body": str(e), "url": ""}]\n'
            "print(json.dumps(results))\n"
        )

        result = self._sandbox.execute_code(search_code)
        if not result.success or not result.stdout:
            logger.warning("Sandbox search failed: %s", result.error)
            return []

        try:
            parsed = json.loads(result.stdout[-1])
            if isinstance(parsed, list):
                return parsed  # type: ignore[return-value]
        except (json.JSONDecodeError, IndexError):
            logger.warning("Could not parse search results")
        return []

    def _act_create_post(self) -> CycleResult:
        """Generate and publish an original post."""
        if self._state.posts_today >= self._settings.max_posts_per_day:
            details = "Daily post limit reached"
            self._log_activity("CREATE_POST", success=False, details=details)
            return CycleResult(action="CREATE_POST", success=False, details=details)

        # Generate content via brain
        context = "Write an original post about AI agents or technology."
        if self._research_context:
            context += f"\n\nResearch context:\n{self._research_context}"
        if self._recent_feed:
            trending = "\n".join(f"- {p.title}" for p in self._recent_feed[:5])
            context += f"\n\nTrending topics:\n{trending}"

        result = self._brain.call("moltbook-content", context)

        # Quality gate
        if result.score < self._settings.quality_threshold:
            details = f"Quality {result.score:.2f} < {self._settings.quality_threshold}"
            self._log_activity(
                "CREATE_POST",
                success=False,
                quality_score=result.score,
                details=details,
            )
            return CycleResult(
                action="CREATE_POST",
                success=False,
                quality_score=result.score,
                details=details,
            )

        # Parse title and body
        title, body = parse_post_content(result.response)
        if not title or not body:
            details = "Could not parse title/body from response"
            self._log_activity("CREATE_POST", success=False, details=details)
            return CycleResult(action="CREATE_POST", success=False, details=details)

        # Publish
        post_result = self._moltbook.create_post(title, body, "agents")
        if not post_result.success:
            self._log_activity(
                "CREATE_POST", success=False, error=post_result.error
            )
            return CycleResult(
                action="CREATE_POST",
                success=False,
                error=post_result.error,
            )

        self._state.posts_today += 1
        details = f"Posted: {title}"
        self._log_activity(
            "CREATE_POST",
            success=True,
            quality_score=result.score,
            details=details,
        )
        self._notify(f"Posted: {title}", "success")
        return CycleResult(
            action="CREATE_POST",
            success=True,
            quality_score=result.score,
            details=details,
        )

    def _act_reply(self) -> CycleResult:
        """Generate and post a reply to a feed post."""
        if self._state.replies_today >= self._settings.max_replies_per_day:
            details = "Daily reply limit reached"
            self._log_activity("REPLY", success=False, details=details)
            return CycleResult(action="REPLY", success=False, details=details)

        if not self._recent_feed:
            details = "No feed loaded — run READ_FEED first"
            self._log_activity("REPLY", success=False, details=details)
            return CycleResult(action="REPLY", success=False, details=details)

        # Pick first post and rotate immediately — whether success or fail, we
        # never retry the same post.  This prevents consecutive_failures from
        # accumulating on a single low-quality post.
        post = self._recent_feed[0]
        self._recent_feed = self._recent_feed[1:]
        context = (
            f"Reply to this post:\n"
            f"Title: {post.title}\n"
            f"Author: {post.author}\n"
            f"Body: {post.body}\n"
            f"Upvotes: {post.upvotes}"
        )
        if self._research_context:
            context += f"\n\nResearch context (use if relevant):\n{self._research_context}"

        result = self._brain.call("moltbook-reply", context)

        # Quality gate
        if result.score < self._settings.quality_threshold:
            details = f"Quality {result.score:.2f} < {self._settings.quality_threshold}"
            self._log_activity(
                "REPLY",
                success=False,
                quality_score=result.score,
                details=details,
            )
            return CycleResult(
                action="REPLY",
                success=False,
                quality_score=result.score,
                details=details,
            )

        # Post reply
        reply_result = self._moltbook.reply(post.id, result.response)
        if not reply_result.success:
            self._log_activity("REPLY", success=False, error=reply_result.error)
            return CycleResult(
                action="REPLY", success=False, error=reply_result.error
            )

        self._state.replies_today += 1
        details = f"Replied to: {post.title[:50]}"
        self._log_activity(
            "REPLY",
            success=True,
            quality_score=result.score,
            details=details,
        )
        self._notify(details, "success")
        return CycleResult(
            action="REPLY",
            success=True,
            quality_score=result.score,
            details=details,
        )

    def _act_analyze(self) -> CycleResult:
        """Analyze engagement data for learning."""
        context = (
            "Analyze engagement trends for our recent posts. "
            "Provide actionable insights for improving content strategy."
        )
        result = self._brain.call("moltbook-analyze", context)
        details = "Analysis completed"
        self._log_activity(
            "ANALYZE",
            success=True,
            quality_score=result.score,
            details=details,
        )
        self._notify("Engagement analysis completed", "info")
        return CycleResult(
            action="ANALYZE",
            success=True,
            quality_score=result.score,
            details=details,
        )

    # --- Heartbeat ---

    def _write_heartbeat(self, current_action: str) -> None:
        """Write heartbeat.json for external health monitoring.

        Called at cycle start (DECIDING), before action, and after action (IDLE).
        External control reads this to determine HEALTHY/STUCK/DEAD status.
        See ARCHITECTURE.md Section 7.3.
        """
        # Use live sandbox_id when available (forward-compatible with migration)
        sandbox_id = (
            self._sandbox.sandbox_id
            if self._sandbox is not None
            else self._sandbox_id
        )
        heartbeat = {
            "timestamp": datetime.now(tz=UTC).isoformat(),
            "current_action": current_action,
            "action_started_at": datetime.now(tz=UTC).isoformat(),
            "cycle_count": self._state.cycle_count,
            "sandbox_id": sandbox_id,
        }
        try:
            self._heartbeat_path.write_text(json.dumps(heartbeat, indent=2))
        except Exception:
            logger.exception("Failed to write heartbeat")

    # --- Utilities ---

    def _notify(self, message: str, level: str) -> None:
        """Send a Telegram notification. Never crashes the agent."""
        from social_agent.telegram import Level as TgLevel

        level_map = {
            "info": TgLevel.INFO,
            "success": TgLevel.SUCCESS,
            "warning": TgLevel.WARNING,
            "error": TgLevel.ERROR,
        }
        self._notifier.notify(message, level_map.get(level, TgLevel.INFO))

    def _log_activity(
        self,
        action: str,
        *,
        success: bool,
        quality_score: float | None = None,
        details: str = "",
        error: str | None = None,
    ) -> None:
        """Append an activity record to the log file."""
        record = ActivityRecord(
            timestamp=datetime.now(tz=UTC).isoformat(),
            cycle=self._state.cycle_count,
            action=action,
            success=success,
            quality_score=quality_score,
            details=details,
            error=error,
        )
        try:
            with open(self._activity_log_path, "a") as f:
                f.write(json.dumps(asdict(record)) + "\n")
        except Exception:
            logger.exception("Failed to write activity log")

    def _wait(self) -> None:
        """Wait between cycles. Uses time.sleep (overridable in tests)."""
        interval = self._settings.cycle_interval_seconds
        logger.info("Waiting %d seconds...", interval)
        time.sleep(interval)


# --- Post content parser (module-level for testability) ---


def parse_post_content(response: str) -> tuple[str, str]:
    """Parse title and body from LLM-generated post content.

    Handles formats:
    - "Title: ...\nBody: ..."
    - "Title: ...\n\n<body text>"
    - First line as title, rest as body

    Returns:
        Tuple of (title, body). Empty strings if parsing fails.
    """
    lines = response.strip().splitlines()
    if not lines:
        return "", ""

    title = ""
    body_lines: list[str] = []
    collecting_body = False

    for line in lines:
        stripped = line.strip()
        if stripped.lower().startswith("title:"):
            title = stripped.split(":", 1)[1].strip().strip('"')
        elif stripped.lower().startswith("body:"):
            rest = stripped.split(":", 1)[1].strip()
            if rest:
                body_lines.append(rest)
            collecting_body = True
        elif collecting_body or title:
            body_lines.append(line)
        elif not title:
            title = stripped

    body = "\n".join(body_lines).strip()

    # Enforce Moltbook title bounds (10-120 chars)
    if title and len(title) < 10:
        title = f"{title} — AI Insights"
    if title and len(title) > 120:
        title = title[:117] + "..."

    return title, body
