"""Tests for social_agent.moltbook.

All tests use mocked SandboxClient — no real E2B or Moltbook calls.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from social_agent.moltbook import (
    MoltbookClient,
    MoltbookPost,
    _build_http_code,
    _parse_response,
)
from social_agent.sandbox import ExecutionResult

# --- Fixtures ---


@pytest.fixture
def mock_sandbox() -> MagicMock:
    """Mock SandboxClient."""
    return MagicMock()


@pytest.fixture
def client(mock_sandbox: MagicMock) -> MoltbookClient:
    """MoltbookClient with mocked sandbox."""
    return MoltbookClient(sandbox=mock_sandbox, api_key="test_api_key")


def _sandbox_success(data: dict[str, object]) -> ExecutionResult:
    """Create a successful sandbox result with JSON output."""
    return ExecutionResult(
        stdout=[json.dumps(data)],
        success=True,
    )


def _sandbox_error(error: str) -> ExecutionResult:
    """Create a failed sandbox result."""
    return ExecutionResult(success=False, error=error)


# --- _build_http_code ---


def test_build_http_code_get() -> None:
    """GET request code includes URL, headers, and params."""
    code = _build_http_code("get", "/test", "key123", params={"limit": 5})
    assert "httpx.get(" in code
    assert "/test" in code
    assert "Bearer key123" in code
    assert "'limit': 5" in code


def test_build_http_code_post_with_body() -> None:
    """POST request code includes JSON body."""
    code = _build_http_code("post", "/test", "key123", body={"title": "hi"})
    assert "httpx.post(" in code
    assert "'title': 'hi'" in code


def test_build_http_code_has_error_handling() -> None:
    """Generated code handles exceptions."""
    code = _build_http_code("get", "/test", "key123")
    assert "except Exception" in code
    assert '"error"' in code


# --- _parse_response ---


def test_parse_response_valid_json() -> None:
    """Parses valid JSON output."""
    result = _parse_response('{"status": 200, "body": {"id": "1"}}')
    assert result["status"] == 200


def test_parse_response_multiline() -> None:
    """Parses JSON from last line when there's extra output."""
    result = _parse_response('Installing...\nDone\n{"status": 200, "body": []}')
    assert result["status"] == 200


def test_parse_response_none() -> None:
    """Returns error for None input."""
    result = _parse_response(None)
    assert "error" in result


def test_parse_response_no_json() -> None:
    """Returns error when no JSON found."""
    result = _parse_response("just plain text")
    assert "error" in result


def test_parse_response_invalid_json() -> None:
    """Returns error for invalid JSON."""
    result = _parse_response("{broken json")
    assert "error" in result


# --- check_status ---


def test_check_status_claimed(
    client: MoltbookClient, mock_sandbox: MagicMock
) -> None:
    """Returns claimed status when agent is verified."""
    mock_sandbox.execute_code.return_value = _sandbox_success({
        "status": 200,
        "body": {"status": "claimed", "name": "NathanSystems"},
    })
    result = client.check_status()
    assert result["status"] == "claimed"


def test_check_status_pending(
    client: MoltbookClient, mock_sandbox: MagicMock
) -> None:
    """Returns pending_claim status when not yet verified."""
    mock_sandbox.execute_code.return_value = _sandbox_success({
        "status": 200,
        "body": {"status": "pending_claim"},
    })
    result = client.check_status()
    assert result["status"] == "pending_claim"


def test_check_status_sandbox_error(
    client: MoltbookClient, mock_sandbox: MagicMock
) -> None:
    """Returns unknown status on sandbox error."""
    mock_sandbox.execute_code.return_value = _sandbox_error("sandbox crashed")
    result = client.check_status()
    assert result["status"] == "unknown"
    assert "error" in result


# --- register ---


def test_register_success(
    client: MoltbookClient, mock_sandbox: MagicMock
) -> None:
    """Successful registration returns api_key and claim_url."""
    mock_sandbox.execute_code.return_value = _sandbox_success({
        "status": 201,
        "body": {"api_key": "new_key", "claim_url": "https://claim.url"},
    })
    result = client.register("Nathan", "Self-learning agent")
    assert result.success is True
    assert result.api_key == "new_key"
    assert result.claim_url == "https://claim.url"


def test_register_sandbox_failure(
    client: MoltbookClient, mock_sandbox: MagicMock
) -> None:
    """Registration fails gracefully on sandbox error."""
    mock_sandbox.execute_code.return_value = _sandbox_error("sandbox crashed")
    result = client.register("Nathan", "Agent")
    assert result.success is False
    assert "sandbox crashed" in (result.error or "")


def test_register_http_error(
    client: MoltbookClient, mock_sandbox: MagicMock
) -> None:
    """Registration reports HTTP errors."""
    mock_sandbox.execute_code.return_value = _sandbox_success({
        "status": 409, "body": "Agent already exists"
    })
    result = client.register("Nathan", "Agent")
    assert result.success is False
    assert "409" in (result.error or "")


# --- get_feed ---


def test_get_feed_success(
    client: MoltbookClient, mock_sandbox: MagicMock
) -> None:
    """Successful feed returns list of MoltbookPost."""
    mock_sandbox.execute_code.return_value = _sandbox_success({
        "status": 200,
        "body": [
            {"id": "1", "title": "Hello", "body": "World", "author": "bot1", "upvotes": 5},
            {"id": "2", "title": "Test", "body": "Post", "author": "bot2", "upvotes": 3},
        ],
    })
    result = client.get_feed("agents", limit=10)
    assert result.success is True
    assert len(result.posts) == 2
    assert isinstance(result.posts[0], MoltbookPost)
    assert result.posts[0].title == "Hello"
    assert result.posts[0].upvotes == 5
    assert result.posts[0].submolt == "agents"


def test_get_feed_global(
    client: MoltbookClient, mock_sandbox: MagicMock
) -> None:
    """Global feed (no submolt) returns posts."""
    mock_sandbox.execute_code.return_value = _sandbox_success({
        "status": 200,
        "body": [
            {"id": "1", "title": "Hello", "body": "World", "author": "bot1"},
        ],
    })
    result = client.get_feed(limit=5)
    assert result.success is True
    assert len(result.posts) == 1
    assert result.posts[0].submolt == ""


def test_get_feed_empty(
    client: MoltbookClient, mock_sandbox: MagicMock
) -> None:
    """Empty feed returns empty list."""
    mock_sandbox.execute_code.return_value = _sandbox_success({
        "status": 200, "body": []
    })
    result = client.get_feed("agents")
    assert result.success is True
    assert result.posts == []


def test_get_feed_http_error(
    client: MoltbookClient, mock_sandbox: MagicMock
) -> None:
    """Feed reports HTTP errors."""
    mock_sandbox.execute_code.return_value = _sandbox_success({
        "status": 500, "body": "Internal Server Error"
    })
    result = client.get_feed("agents")
    assert result.success is False
    assert "500" in (result.error or "")


# --- create_post ---


def test_create_post_success(
    client: MoltbookClient, mock_sandbox: MagicMock
) -> None:
    """Successful post creation returns post ID."""
    mock_sandbox.execute_code.return_value = _sandbox_success({
        "status": 201, "body": {"id": "post-42"}
    })
    result = client.create_post("AI Agents Are Here", "Content body", "agents")
    assert result.success is True
    assert result.post_id == "post-42"


def test_create_post_title_too_short(
    client: MoltbookClient, mock_sandbox: MagicMock
) -> None:
    """Title < 10 chars rejected locally (no API call)."""
    result = client.create_post("Short", "Body", "agents")
    assert result.success is False
    assert "10-120" in (result.error or "")
    mock_sandbox.execute_code.assert_not_called()


def test_create_post_title_too_long(
    client: MoltbookClient, mock_sandbox: MagicMock
) -> None:
    """Title > 120 chars rejected locally."""
    result = client.create_post("X" * 121, "Body", "agents")
    assert result.success is False
    assert "10-120" in (result.error or "")
    mock_sandbox.execute_code.assert_not_called()


def test_create_post_title_boundary(
    client: MoltbookClient, mock_sandbox: MagicMock
) -> None:
    """Title at exactly 10 and 120 chars accepted."""
    mock_sandbox.execute_code.return_value = _sandbox_success({
        "status": 201, "body": {"id": "1"}
    })
    # 10 chars
    result_10 = client.create_post("A" * 10, "Body", "agents")
    assert result_10.success is True
    # 120 chars
    result_120 = client.create_post("B" * 120, "Body", "agents")
    assert result_120.success is True


def test_create_post_rate_limited(
    client: MoltbookClient, mock_sandbox: MagicMock
) -> None:
    """Rate limit (429) reported as error."""
    mock_sandbox.execute_code.return_value = _sandbox_success({
        "status": 429, "body": "Rate limited"
    })
    result = client.create_post("Valid Title Here", "Body", "agents")
    assert result.success is False
    assert "429" in (result.error or "")


# --- reply ---


def test_reply_success(
    client: MoltbookClient, mock_sandbox: MagicMock
) -> None:
    """Successful reply returns comment ID."""
    mock_sandbox.execute_code.return_value = _sandbox_success({
        "status": 201, "body": {"id": "comment-7"}
    })
    result = client.reply("post-42", "Great insight!")
    assert result.success is True
    assert result.post_id == "comment-7"


def test_reply_not_found(
    client: MoltbookClient, mock_sandbox: MagicMock
) -> None:
    """Reply to non-existent post reports error."""
    mock_sandbox.execute_code.return_value = _sandbox_success({
        "status": 404, "body": "Post not found"
    })
    result = client.reply("nonexistent", "Reply text")
    assert result.success is False
    assert "404" in (result.error or "")


# --- get_engagement ---


def test_get_engagement_success(
    client: MoltbookClient, mock_sandbox: MagicMock
) -> None:
    """Successful engagement returns stats."""
    mock_sandbox.execute_code.return_value = _sandbox_success({
        "status": 200,
        "body": {"upvotes": 10, "downvotes": 2, "comments": 5, "views": 100},
    })
    result = client.get_engagement("post-42")
    assert result.success is True
    assert result.upvotes == 10
    assert result.downvotes == 2
    assert result.comments == 5
    assert result.views == 100


def test_get_engagement_not_found(
    client: MoltbookClient, mock_sandbox: MagicMock
) -> None:
    """Engagement for non-existent post reports error."""
    mock_sandbox.execute_code.return_value = _sandbox_success({
        "status": 404, "body": "Not found"
    })
    result = client.get_engagement("bad-id")
    assert result.success is False


# --- heartbeat ---


def test_heartbeat_success(
    client: MoltbookClient, mock_sandbox: MagicMock
) -> None:
    """Successful heartbeat."""
    mock_sandbox.execute_code.return_value = _sandbox_success({
        "status": 200, "body": "ok"
    })
    result = client.heartbeat()
    assert result.success is True


def test_heartbeat_failure(
    client: MoltbookClient, mock_sandbox: MagicMock
) -> None:
    """Failed heartbeat reports error."""
    mock_sandbox.execute_code.return_value = _sandbox_success({
        "status": 503, "body": "Service unavailable"
    })
    result = client.heartbeat()
    assert result.success is False
    assert "503" in (result.error or "")


# --- Auth header ---


def test_auth_header_in_generated_code(mock_sandbox: MagicMock) -> None:
    """API key is included in generated code as Bearer token."""
    client = MoltbookClient(sandbox=mock_sandbox, api_key="secret_key_123")
    mock_sandbox.execute_code.return_value = _sandbox_success({
        "status": 200, "body": []
    })
    client.get_feed("agents")

    call_args = mock_sandbox.execute_code.call_args[0][0]
    assert "Bearer secret_key_123" in call_args
