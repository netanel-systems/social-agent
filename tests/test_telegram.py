"""Tests for social_agent.telegram.

All tests use mocked httpx — no real Telegram API calls.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from pydantic import SecretStr

from social_agent.telegram import Level, TelegramNotifier, _escape_markdown

# --- _escape_markdown ---


def test_escape_plain_text() -> None:
    """Plain text passes through unchanged."""
    assert _escape_markdown("hello world") == "hello world"


def test_escape_special_chars() -> None:
    """Special MarkdownV2 characters are escaped."""
    assert _escape_markdown("hello_world") == "hello\\_world"
    assert _escape_markdown("*bold*") == "\\*bold\\*"
    assert _escape_markdown("test.end") == "test\\.end"


def test_escape_multiple_chars() -> None:
    """Multiple special characters in one string."""
    result = _escape_markdown("v1.0 (beta) [test]")
    assert "\\." in result
    assert "\\(" in result
    assert "\\)" in result
    assert "\\[" in result
    assert "\\]" in result


# --- TelegramNotifier disabled ---


def test_disabled_when_no_token() -> None:
    """Notifier is disabled without bot_token."""
    notifier = TelegramNotifier(bot_token=None, chat_id="123")
    assert notifier.enabled is False


def test_disabled_when_no_chat_id() -> None:
    """Notifier is disabled without chat_id."""
    notifier = TelegramNotifier(bot_token=SecretStr("token"), chat_id=None)
    assert notifier.enabled is False


def test_disabled_notify_returns_false() -> None:
    """notify() returns False when disabled."""
    notifier = TelegramNotifier(bot_token=None, chat_id=None)
    assert notifier.notify("test message") is False


def test_disabled_notify_does_not_crash() -> None:
    """notify() on disabled notifier never raises."""
    notifier = TelegramNotifier()
    notifier.notify("anything", Level.ERROR)  # Should not raise


# --- TelegramNotifier enabled ---


def test_enabled_when_both_set() -> None:
    """Notifier is enabled with both token and chat_id."""
    notifier = TelegramNotifier(
        bot_token=SecretStr("test_token"),
        chat_id="12345",
    )
    assert notifier.enabled is True


@patch("social_agent.telegram.httpx")
def test_notify_info(mock_httpx: MagicMock) -> None:
    """INFO notification sends with info prefix."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_httpx.post.return_value = mock_response

    notifier = TelegramNotifier(
        bot_token=SecretStr("bot_token"),
        chat_id="12345",
    )
    result = notifier.notify("Agent started", Level.INFO)

    assert result is True
    mock_httpx.post.assert_called_once()
    call_kwargs = mock_httpx.post.call_args
    body = call_kwargs.kwargs["json"] if "json" in call_kwargs.kwargs else call_kwargs[1]["json"]
    assert body["chat_id"] == "12345"
    assert body["parse_mode"] == "MarkdownV2"
    assert "INFO" in body["text"]


@patch("social_agent.telegram.httpx")
def test_notify_success_level(mock_httpx: MagicMock) -> None:
    """SUCCESS notification includes success prefix."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_httpx.post.return_value = mock_response

    notifier = TelegramNotifier(
        bot_token=SecretStr("token"),
        chat_id="123",
    )
    result = notifier.notify("Post created", Level.SUCCESS)
    assert result is True


@patch("social_agent.telegram.httpx")
def test_notify_warning_level(mock_httpx: MagicMock) -> None:
    """WARNING notification works."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_httpx.post.return_value = mock_response

    notifier = TelegramNotifier(
        bot_token=SecretStr("token"),
        chat_id="123",
    )
    result = notifier.notify("Rate limited", Level.WARNING)
    assert result is True


@patch("social_agent.telegram.httpx")
def test_notify_error_level(mock_httpx: MagicMock) -> None:
    """ERROR notification works."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_httpx.post.return_value = mock_response

    notifier = TelegramNotifier(
        bot_token=SecretStr("token"),
        chat_id="123",
    )
    result = notifier.notify("Circuit breaker tripped", Level.ERROR)
    assert result is True


@patch("social_agent.telegram.httpx")
def test_notify_default_level_is_info(mock_httpx: MagicMock) -> None:
    """Default level is INFO."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_httpx.post.return_value = mock_response

    notifier = TelegramNotifier(
        bot_token=SecretStr("token"),
        chat_id="123",
    )
    result = notifier.notify("Test message")
    assert result is True

    call_kwargs = mock_httpx.post.call_args
    body = call_kwargs.kwargs["json"] if "json" in call_kwargs.kwargs else call_kwargs[1]["json"]
    assert "INFO" in body["text"]


# --- Graceful degradation ---


@patch("social_agent.telegram.httpx")
def test_api_error_returns_false(mock_httpx: MagicMock) -> None:
    """Non-200 response returns False, doesn't crash."""
    mock_response = MagicMock()
    mock_response.status_code = 400
    mock_response.text = "Bad Request"
    mock_httpx.post.return_value = mock_response

    notifier = TelegramNotifier(
        bot_token=SecretStr("token"),
        chat_id="123",
    )
    result = notifier.notify("Test")
    assert result is False


@patch("social_agent.telegram.httpx")
def test_network_error_returns_false(mock_httpx: MagicMock) -> None:
    """Network error returns False, doesn't crash."""
    mock_httpx.post.side_effect = ConnectionError("network down")

    notifier = TelegramNotifier(
        bot_token=SecretStr("token"),
        chat_id="123",
    )
    result = notifier.notify("Test")
    assert result is False


@patch("social_agent.telegram.httpx")
def test_token_used_in_url(mock_httpx: MagicMock) -> None:
    """Bot token is included in the API URL."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_httpx.post.return_value = mock_response

    notifier = TelegramNotifier(
        bot_token=SecretStr("my_bot_token_123"),
        chat_id="12345",
    )
    notifier.notify("Test")

    url = mock_httpx.post.call_args[0][0]
    assert "my_bot_token_123" in url
    assert "sendMessage" in url
