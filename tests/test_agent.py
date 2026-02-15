"""Tests for social_agent.agent.

All tests use mocked dependencies — no real API calls, no real time.sleep.
Tests verify state machine logic, rate limiting, circuit breaker,
activity logging, state persistence, and content parsing.
"""

from __future__ import annotations

import json
from datetime import UTC
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from social_agent.agent import (
    Action,
    Agent,
    AgentState,
    parse_post_content,
)
from social_agent.moltbook import FeedResult, MoltbookPost, PostResult

if TYPE_CHECKING:
    from pathlib import Path


# --- Fixtures ---


@pytest.fixture
def tmp_dir(tmp_path: Path) -> Path:
    """Temporary directory for state and logs."""
    return tmp_path


@pytest.fixture
def mock_settings() -> MagicMock:
    """Mock Settings with reasonable defaults."""
    settings = MagicMock()
    settings.max_cycles = 500
    settings.max_posts_per_day = 5
    settings.max_replies_per_day = 20
    settings.cycle_interval_seconds = 300
    settings.quality_threshold = 0.7
    settings.circuit_breaker_threshold = 5
    return settings


@pytest.fixture
def mock_brain() -> MagicMock:
    """Mock AgentBrain."""
    return MagicMock()


@pytest.fixture
def mock_moltbook() -> MagicMock:
    """Mock MoltbookClient."""
    return MagicMock()


@pytest.fixture
def mock_notifier() -> MagicMock:
    """Mock TelegramNotifier."""
    return MagicMock()


@pytest.fixture
def agent(
    mock_settings: MagicMock,
    mock_brain: MagicMock,
    mock_moltbook: MagicMock,
    mock_notifier: MagicMock,
    tmp_dir: Path,
) -> Agent:
    """Agent with all mocked dependencies."""
    return Agent(
        settings=mock_settings,
        brain=mock_brain,
        moltbook=mock_moltbook,
        notifier=mock_notifier,
        state_path=tmp_dir / "state.json",
        activity_log_path=tmp_dir / "logs" / "activity.jsonl",
    )


def _brain_result(response: str, score: float = 0.8) -> MagicMock:
    """Create a mock CallResult."""
    result = MagicMock()
    result.response = response
    result.score = score
    result.passed = score >= 0.7
    return result


def _feed_posts(count: int = 3) -> list[MoltbookPost]:
    """Create mock feed posts."""
    return [
        MoltbookPost(
            id=f"post-{i}",
            title=f"Test Post {i}",
            body=f"Body of post {i}",
            submolt="agents",
            author=f"bot-{i}",
            upvotes=i * 5,
        )
        for i in range(count)
    ]


# --- Action enum ---


def test_action_values() -> None:
    """All 5 actions exist with correct values."""
    assert Action.READ_FEED == "READ_FEED"
    assert Action.RESEARCH == "RESEARCH"
    assert Action.REPLY == "REPLY"
    assert Action.CREATE_POST == "CREATE_POST"
    assert Action.ANALYZE == "ANALYZE"
    assert len(Action) == 5


# --- AgentState ---


def test_state_defaults() -> None:
    """Fresh state has zero counters."""
    state = AgentState()
    assert state.posts_today == 0
    assert state.replies_today == 0
    assert state.cycle_count == 0
    assert state.consecutive_failures == 0


def test_state_daily_reset() -> None:
    """Daily counters reset when date changes."""
    state = AgentState(
        posts_today=3,
        replies_today=10,
        last_reset_date="2026-01-01",
    )
    state.reset_daily_counters()
    assert state.posts_today == 0
    assert state.replies_today == 0
    assert state.last_reset_date != "2026-01-01"


def test_state_no_reset_same_day() -> None:
    """Counters preserved on same day."""
    from datetime import datetime

    today = datetime.now(tz=UTC).strftime("%Y-%m-%d")
    state = AgentState(
        posts_today=3,
        replies_today=10,
        last_reset_date=today,
    )
    state.reset_daily_counters()
    assert state.posts_today == 3
    assert state.replies_today == 10


def test_state_json_round_trip() -> None:
    """State serializes and deserializes correctly."""
    state = AgentState(
        posts_today=2,
        replies_today=5,
        cycle_count=42,
        consecutive_failures=1,
    )
    json_str = state.to_json()
    loaded = AgentState.from_json(json_str)
    assert loaded.posts_today == 2
    assert loaded.replies_today == 5
    assert loaded.cycle_count == 42


def test_state_save_and_load(tmp_dir: Path) -> None:
    """State persists to disk and loads back."""
    path = tmp_dir / "state.json"
    state = AgentState(cycle_count=10, posts_today=1)
    state.save(path)

    loaded = AgentState.load(path)
    assert loaded.cycle_count == 10
    assert loaded.posts_today == 1


def test_state_load_missing_file(tmp_dir: Path) -> None:
    """Missing state file returns defaults."""
    path = tmp_dir / "nonexistent.json"
    state = AgentState.load(path)
    assert state.cycle_count == 0


def test_state_load_corrupted_file(tmp_dir: Path) -> None:
    """Corrupted state file returns defaults."""
    path = tmp_dir / "state.json"
    path.write_text("not json at all")
    state = AgentState.load(path)
    assert state.cycle_count == 0


def test_state_from_json_ignores_unknown_keys() -> None:
    """Unknown keys in JSON are ignored (forward compatibility)."""
    data = json.dumps({"cycle_count": 5, "future_field": "value"})
    state = AgentState.from_json(data)
    assert state.cycle_count == 5


# --- should_continue ---


def test_should_continue_normal(agent: Agent) -> None:
    """Agent continues when no stop conditions met."""
    assert agent.should_continue() is True


def test_should_continue_shutdown(agent: Agent) -> None:
    """Agent stops on shutdown request."""
    agent.request_shutdown()
    assert agent.should_continue() is False


def test_should_continue_max_cycles(agent: Agent) -> None:
    """Agent stops at max cycles."""
    agent._state.cycle_count = 500
    assert agent.should_continue() is False


def test_should_continue_circuit_breaker(agent: Agent) -> None:
    """Agent stops when circuit breaker trips."""
    agent._state.consecutive_failures = 5
    assert agent.should_continue() is False


# --- Decision ---


def test_decide_read_feed(agent: Agent, mock_brain: MagicMock) -> None:
    """Brain response parsed to READ_FEED action."""
    mock_brain.call.return_value = _brain_result("READ_FEED — let's check what's new")
    action = agent._decide()
    assert action == Action.READ_FEED


def test_decide_create_post(agent: Agent, mock_brain: MagicMock) -> None:
    """Brain response parsed to CREATE_POST action."""
    mock_brain.call.return_value = _brain_result("CREATE_POST — time for original content")
    action = agent._decide()
    assert action == Action.CREATE_POST


def test_decide_reply(agent: Agent, mock_brain: MagicMock) -> None:
    """Brain response parsed to REPLY action."""
    mock_brain.call.return_value = _brain_result("REPLY — found a great discussion")
    action = agent._decide()
    assert action == Action.REPLY


def test_decide_analyze(agent: Agent, mock_brain: MagicMock) -> None:
    """Brain response parsed to ANALYZE action."""
    mock_brain.call.return_value = _brain_result("ANALYZE — check our engagement")
    action = agent._decide()
    assert action == Action.ANALYZE


def test_decide_unparseable(agent: Agent, mock_brain: MagicMock) -> None:
    """Unparseable response returns None."""
    mock_brain.call.return_value = _brain_result("I think we should do something")
    action = agent._decide()
    assert action is None


def test_decide_brain_exception(agent: Agent, mock_brain: MagicMock) -> None:
    """Brain exception returns None gracefully."""
    mock_brain.call.side_effect = RuntimeError("LLM error")
    action = agent._decide()
    assert action is None


def test_decision_context_includes_state(agent: Agent) -> None:
    """Decision context includes current state info."""
    agent._state.posts_today = 2
    agent._state.replies_today = 5
    agent._state.cycle_count = 10
    context = agent._build_decision_context()
    assert "Posts today: 2/5" in context
    assert "Replies today: 5/20" in context
    assert "Cycle: 10" in context


def test_decision_context_post_limit(agent: Agent) -> None:
    """Decision context flags when post limit reached."""
    agent._state.posts_today = 5
    context = agent._build_decision_context()
    assert "CONSTRAINT" in context
    assert "CREATE_POST" in context


def test_decision_context_reply_limit(agent: Agent) -> None:
    """Decision context flags when reply limit reached."""
    agent._state.replies_today = 20
    context = agent._build_decision_context()
    assert "CONSTRAINT" in context
    assert "REPLY" in context


def test_decision_context_no_feed(agent: Agent) -> None:
    """Decision context notes when no feed is loaded."""
    context = agent._build_decision_context()
    assert "No feed loaded" in context


# --- READ_FEED ---


def test_read_feed_success(
    agent: Agent, mock_moltbook: MagicMock
) -> None:
    """READ_FEED loads posts from all submolts."""
    posts = _feed_posts(3)
    mock_moltbook.get_feed.return_value = FeedResult(posts=posts)

    result = agent._act_read_feed()
    assert result.success is True
    assert len(agent.recent_feed) == 12  # 3 posts * 4 submolts
    assert mock_moltbook.get_feed.call_count == 4


def test_read_feed_partial_failure(
    agent: Agent, mock_moltbook: MagicMock
) -> None:
    """READ_FEED handles partial submolt failures."""
    posts = _feed_posts(2)
    mock_moltbook.get_feed.side_effect = [
        FeedResult(posts=posts),
        FeedResult(success=False, error="Server error"),
        FeedResult(posts=posts),
        FeedResult(success=False, error="Timeout"),
    ]

    result = agent._act_read_feed()
    assert result.success is True
    assert len(agent.recent_feed) == 4  # 2 posts * 2 successful submolts


# --- CREATE_POST ---


def test_create_post_success(
    agent: Agent,
    mock_brain: MagicMock,
    mock_moltbook: MagicMock,
) -> None:
    """CREATE_POST generates, quality-checks, and publishes."""
    mock_brain.call.return_value = _brain_result(
        "Title: The Future of AI Agents\nBody:\nAI agents are becoming...", 0.85
    )
    mock_moltbook.create_post.return_value = PostResult(
        post_id="post-1", success=True
    )

    result = agent._act_create_post()
    assert result.success is True
    assert agent._state.posts_today == 1
    mock_moltbook.create_post.assert_called_once()


def test_create_post_quality_gate(
    agent: Agent, mock_brain: MagicMock, mock_moltbook: MagicMock
) -> None:
    """CREATE_POST blocked when quality is below threshold."""
    mock_brain.call.return_value = _brain_result("Title: Bad Post\nBody:\nMeh", 0.5)

    result = agent._act_create_post()
    assert result.success is False
    assert "Quality" in result.details
    assert agent._state.posts_today == 0
    mock_moltbook.create_post.assert_not_called()


def test_create_post_daily_limit(
    agent: Agent, mock_brain: MagicMock, mock_moltbook: MagicMock
) -> None:
    """CREATE_POST blocked when daily limit reached."""
    agent._state.posts_today = 5

    result = agent._act_create_post()
    assert result.success is False
    assert "limit" in result.details
    mock_brain.call.assert_not_called()
    mock_moltbook.create_post.assert_not_called()


def test_create_post_api_failure(
    agent: Agent,
    mock_brain: MagicMock,
    mock_moltbook: MagicMock,
) -> None:
    """CREATE_POST handles Moltbook API failure."""
    mock_brain.call.return_value = _brain_result(
        "Title: Good Post Title Here\nBody:\nContent here", 0.9
    )
    mock_moltbook.create_post.return_value = PostResult(
        success=False, error="Rate limited"
    )

    result = agent._act_create_post()
    assert result.success is False
    assert agent._state.posts_today == 0


# --- REPLY ---


def test_reply_success(
    agent: Agent,
    mock_brain: MagicMock,
    mock_moltbook: MagicMock,
) -> None:
    """REPLY generates reply, quality-checks, and posts."""
    agent._recent_feed = _feed_posts(3)
    mock_brain.call.return_value = _brain_result("Great insight about agents!", 0.8)
    mock_moltbook.reply.return_value = PostResult(
        post_id="comment-1", success=True
    )

    result = agent._act_reply()
    assert result.success is True
    assert agent._state.replies_today == 1
    assert len(agent.recent_feed) == 2  # Feed rotated


def test_reply_quality_gate(
    agent: Agent, mock_brain: MagicMock, mock_moltbook: MagicMock
) -> None:
    """REPLY blocked when quality is below threshold."""
    agent._recent_feed = _feed_posts(1)
    mock_brain.call.return_value = _brain_result("ok", 0.3)

    result = agent._act_reply()
    assert result.success is False
    assert agent._state.replies_today == 0
    mock_moltbook.reply.assert_not_called()


def test_reply_daily_limit(
    agent: Agent, mock_brain: MagicMock
) -> None:
    """REPLY blocked when daily limit reached."""
    agent._state.replies_today = 20
    agent._recent_feed = _feed_posts(1)

    result = agent._act_reply()
    assert result.success is False
    mock_brain.call.assert_not_called()


def test_reply_no_feed(agent: Agent, mock_brain: MagicMock) -> None:
    """REPLY fails when no feed is loaded."""
    result = agent._act_reply()
    assert result.success is False
    assert "feed" in result.details.lower()
    mock_brain.call.assert_not_called()


def test_reply_api_failure(
    agent: Agent,
    mock_brain: MagicMock,
    mock_moltbook: MagicMock,
) -> None:
    """REPLY handles Moltbook API failure."""
    agent._recent_feed = _feed_posts(1)
    mock_brain.call.return_value = _brain_result("Good reply content", 0.85)
    mock_moltbook.reply.return_value = PostResult(
        success=False, error="Post not found"
    )

    result = agent._act_reply()
    assert result.success is False
    assert agent._state.replies_today == 0


# --- ANALYZE ---


def test_analyze_success(
    agent: Agent, mock_brain: MagicMock
) -> None:
    """ANALYZE always succeeds (learning happens in brain)."""
    mock_brain.call.return_value = _brain_result("Top insights: ...", 0.75)

    result = agent._act_analyze()
    assert result.success is True
    assert result.quality_score == 0.75


# --- Full cycle ---


def test_cycle_decide_and_act(
    agent: Agent,
    mock_brain: MagicMock,
    mock_moltbook: MagicMock,
) -> None:
    """Full cycle: decide READ_FEED, execute, return result."""
    # Decision returns READ_FEED
    mock_brain.call.return_value = _brain_result("READ_FEED — check what's trending")
    mock_moltbook.get_feed.return_value = FeedResult(posts=_feed_posts(2))

    result = agent.cycle()
    assert result.action == "READ_FEED"
    assert result.success is True
    assert agent._state.cycle_count == 1


def test_cycle_decision_failure(
    agent: Agent, mock_brain: MagicMock
) -> None:
    """Cycle handles decision failure gracefully."""
    mock_brain.call.return_value = _brain_result("I'm confused")

    result = agent.cycle()
    assert result.success is False
    assert result.action == "DECIDE"
    assert agent._state.consecutive_failures == 1


def test_cycle_resets_failures_on_success(
    agent: Agent,
    mock_brain: MagicMock,
    mock_moltbook: MagicMock,
) -> None:
    """Successful cycle resets consecutive failure count."""
    agent._state.consecutive_failures = 3
    mock_brain.call.return_value = _brain_result("READ_FEED — let's see")
    mock_moltbook.get_feed.return_value = FeedResult(posts=[])

    agent.cycle()
    assert agent._state.consecutive_failures == 0


def test_cycle_increments_failures(
    agent: Agent, mock_brain: MagicMock
) -> None:
    """Failed cycle increments consecutive failure count."""
    agent._state.consecutive_failures = 2
    mock_brain.call.side_effect = RuntimeError("LLM crashed")

    agent.cycle()
    assert agent._state.consecutive_failures == 3


def test_cycle_saves_state(
    agent: Agent,
    mock_brain: MagicMock,
    mock_moltbook: MagicMock,
) -> None:
    """State is saved to disk after each cycle."""
    mock_brain.call.return_value = _brain_result("READ_FEED")
    mock_moltbook.get_feed.return_value = FeedResult(posts=[])

    agent.cycle()

    loaded = AgentState.load(agent._state_path)
    assert loaded.cycle_count == 1


# --- Activity logging ---


def test_activity_log_written(
    agent: Agent,
    mock_brain: MagicMock,
    mock_moltbook: MagicMock,
    tmp_dir: Path,
) -> None:
    """Activity records are appended to the log file."""
    mock_brain.call.return_value = _brain_result("READ_FEED")
    mock_moltbook.get_feed.return_value = FeedResult(posts=[])

    agent.cycle()

    log_path = tmp_dir / "logs" / "activity.jsonl"
    assert log_path.exists()
    lines = log_path.read_text().strip().splitlines()
    assert len(lines) >= 1
    record = json.loads(lines[0])
    assert record["action"] == "READ_FEED"
    assert record["success"] is True


# --- parse_post_content ---


def test_parse_titled_format() -> None:
    """Parses 'Title: ...\nBody: ...' format."""
    title, body = parse_post_content(
        "Title: The Future of AI\nBody:\nAI agents are transforming..."
    )
    assert title == "The Future of AI"
    assert "AI agents" in body


def test_parse_short_title_padded() -> None:
    """Short titles are padded to meet 10-char minimum."""
    title, body = parse_post_content("Title: Hi\nBody:\nContent here")
    assert len(title) >= 10


def test_parse_long_title_truncated() -> None:
    """Long titles are truncated to 120 chars."""
    long_title = "A" * 200
    title, body = parse_post_content(f"Title: {long_title}\nBody:\nContent")
    assert len(title) <= 120
    assert title.endswith("...")


def test_parse_plain_text() -> None:
    """Parses plain text (first line = title, rest = body)."""
    title, body = parse_post_content(
        "My Great Post Title\nFirst paragraph.\nSecond paragraph."
    )
    assert title == "My Great Post Title"
    assert "First paragraph" in body


def test_parse_empty() -> None:
    """Empty input returns empty strings."""
    title, body = parse_post_content("")
    assert title == ""
    assert body == ""


def test_parse_single_line() -> None:
    """Single line becomes title, no body."""
    title, body = parse_post_content("Just a title")
    assert title != ""
    assert body == ""


# --- Run loop ---


@patch.object(Agent, "_wait")
def test_run_stops_at_max_cycles(
    mock_wait: MagicMock,
    mock_settings: MagicMock,
    mock_brain: MagicMock,
    mock_moltbook: MagicMock,
    mock_notifier: MagicMock,
    tmp_dir: Path,
) -> None:
    """run() stops when max_cycles is reached."""
    mock_settings.max_cycles = 3
    mock_brain.call.return_value = _brain_result("READ_FEED")
    mock_moltbook.get_feed.return_value = FeedResult(posts=[])

    agent = Agent(
        settings=mock_settings,
        brain=mock_brain,
        moltbook=mock_moltbook,
        notifier=mock_notifier,
        state_path=tmp_dir / "state.json",
        activity_log_path=tmp_dir / "logs" / "activity.jsonl",
    )
    agent.run()

    assert agent._state.cycle_count == 3


@patch.object(Agent, "_wait")
def test_run_stops_on_circuit_breaker(
    mock_wait: MagicMock,
    mock_settings: MagicMock,
    mock_brain: MagicMock,
    mock_moltbook: MagicMock,
    mock_notifier: MagicMock,
    tmp_dir: Path,
) -> None:
    """run() stops when circuit breaker trips."""
    mock_settings.max_cycles = 100
    mock_settings.circuit_breaker_threshold = 3
    mock_brain.call.return_value = _brain_result("I don't know what to do")

    agent = Agent(
        settings=mock_settings,
        brain=mock_brain,
        moltbook=mock_moltbook,
        notifier=mock_notifier,
        state_path=tmp_dir / "state.json",
        activity_log_path=tmp_dir / "logs" / "activity.jsonl",
    )
    agent.run()

    assert agent._state.consecutive_failures >= 3
    assert agent._state.cycle_count < 100


@patch.object(Agent, "_wait")
def test_run_stops_on_shutdown_request(
    mock_wait: MagicMock,
    mock_settings: MagicMock,
    mock_brain: MagicMock,
    mock_moltbook: MagicMock,
    mock_notifier: MagicMock,
    tmp_dir: Path,
) -> None:
    """run() stops on shutdown request."""
    mock_settings.max_cycles = 100
    call_count = 0

    def decide_then_shutdown(namespace: str, task: str) -> MagicMock:
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            agent.request_shutdown()
        return _brain_result("READ_FEED")

    mock_brain.call.side_effect = decide_then_shutdown
    mock_moltbook.get_feed.return_value = FeedResult(posts=[])

    agent = Agent(
        settings=mock_settings,
        brain=mock_brain,
        moltbook=mock_moltbook,
        notifier=mock_notifier,
        state_path=tmp_dir / "state.json",
        activity_log_path=tmp_dir / "logs" / "activity.jsonl",
    )
    agent.run()

    assert agent._state.cycle_count <= 3


# --- Exception handling ---


def test_action_exception_caught(
    agent: Agent, mock_brain: MagicMock
) -> None:
    """Action exceptions are caught and returned as failed result."""
    mock_brain.call.side_effect = [
        _brain_result("ANALYZE"),  # decide
        RuntimeError("boom"),  # analyze
    ]

    result = agent.cycle()
    assert result.success is False
    assert result.error is not None


# --- RESEARCH ---


def test_research_no_sandbox(agent: Agent) -> None:
    """RESEARCH fails gracefully without a sandbox."""
    # Default agent fixture has no sandbox
    result = agent._act_research()
    assert result.success is False
    assert "No sandbox" in result.details


def test_research_success(
    mock_settings: MagicMock,
    mock_brain: MagicMock,
    mock_moltbook: MagicMock,
    mock_notifier: MagicMock,
    tmp_dir: Path,
) -> None:
    """RESEARCH calls brain for query, runs sandbox search, stores context."""
    from social_agent.sandbox import ExecutionResult

    mock_sandbox = MagicMock()
    mock_sandbox.execute_code.return_value = ExecutionResult(
        stdout=['[{"title": "AI Agents 2026", "body": "New developments...", "url": "https://example.com"}]'],
        success=True,
    )
    mock_brain.call.return_value = _brain_result(
        "QUERY: AI agent frameworks 2026\nTOPIC: Agent Frameworks\nRATIONALE: Hot topic"
    )

    agent = Agent(
        settings=mock_settings,
        brain=mock_brain,
        moltbook=mock_moltbook,
        notifier=mock_notifier,
        sandbox=mock_sandbox,
        state_path=tmp_dir / "state.json",
        activity_log_path=tmp_dir / "logs" / "activity.jsonl",
    )

    result = agent._act_research()
    assert result.success is True
    assert "AI agent frameworks 2026" in result.details
    assert "AI Agents 2026" in agent._research_context
    mock_sandbox.execute_code.assert_called_once()


def test_research_empty_results(
    mock_settings: MagicMock,
    mock_brain: MagicMock,
    mock_moltbook: MagicMock,
    mock_notifier: MagicMock,
    tmp_dir: Path,
) -> None:
    """RESEARCH handles empty search results."""
    from social_agent.sandbox import ExecutionResult

    mock_sandbox = MagicMock()
    mock_sandbox.execute_code.return_value = ExecutionResult(
        stdout=["[]"], success=True,
    )
    mock_brain.call.return_value = _brain_result(
        "QUERY: obscure topic nobody knows\nTOPIC: Unknown\nRATIONALE: test"
    )

    agent = Agent(
        settings=mock_settings,
        brain=mock_brain,
        moltbook=mock_moltbook,
        notifier=mock_notifier,
        sandbox=mock_sandbox,
        state_path=tmp_dir / "state.json",
        activity_log_path=tmp_dir / "logs" / "activity.jsonl",
    )

    result = agent._act_research()
    assert result.success is False
    assert "No results" in result.details


def test_research_sandbox_failure(
    mock_settings: MagicMock,
    mock_brain: MagicMock,
    mock_moltbook: MagicMock,
    mock_notifier: MagicMock,
    tmp_dir: Path,
) -> None:
    """RESEARCH handles sandbox execution failure."""
    from social_agent.sandbox import ExecutionResult

    mock_sandbox = MagicMock()
    mock_sandbox.execute_code.return_value = ExecutionResult(
        success=False, error="sandbox crashed",
    )
    mock_brain.call.return_value = _brain_result(
        "QUERY: AI agents\nTOPIC: AI\nRATIONALE: test"
    )

    agent = Agent(
        settings=mock_settings,
        brain=mock_brain,
        moltbook=mock_moltbook,
        notifier=mock_notifier,
        sandbox=mock_sandbox,
        state_path=tmp_dir / "state.json",
        activity_log_path=tmp_dir / "logs" / "activity.jsonl",
    )

    result = agent._act_research()
    assert result.success is False


def test_parse_research_query() -> None:
    """Parse search query from brain response."""
    query = Agent._parse_research_query(
        "QUERY: AI agent frameworks 2026\nTOPIC: Agents\nRATIONALE: trending"
    )
    assert query == "AI agent frameworks 2026"


def test_parse_research_query_fallback() -> None:
    """Fallback to first line when no QUERY: prefix."""
    query = Agent._parse_research_query("some random text about AI")
    assert query == "some random text about AI"


def test_research_context_in_decision(
    mock_settings: MagicMock,
    mock_brain: MagicMock,
    mock_moltbook: MagicMock,
    mock_notifier: MagicMock,
    tmp_dir: Path,
) -> None:
    """Decision context includes research availability."""
    agent = Agent(
        settings=mock_settings,
        brain=mock_brain,
        moltbook=mock_moltbook,
        notifier=mock_notifier,
        state_path=tmp_dir / "state.json",
        activity_log_path=tmp_dir / "logs" / "activity.jsonl",
    )

    # No research
    context = agent._build_decision_context()
    assert "Research context available: NO" in context
    assert "No research done" in context

    # With research
    agent._research_context = "Some research about AI agents"
    context = agent._build_decision_context()
    assert "Research context available: YES" in context
