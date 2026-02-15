"""Telegram notifier for real-time agent monitoring.

Sends notifications to Klement's phone on every agent action.
Runs locally (monitoring infrastructure, not agent action).
Graceful degradation: never crashes the agent if Telegram fails.
"""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from pydantic import SecretStr

logger = logging.getLogger(__name__)


class Level(StrEnum):
    """Notification severity levels."""

    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"


_LEVEL_PREFIX: dict[Level, str] = {
    Level.INFO: "ℹ️",
    Level.SUCCESS: "✅",
    Level.WARNING: "⚠️",
    Level.ERROR: "🚨",
}

# MarkdownV2 special characters that need escaping
_ESCAPE_CHARS = r"_*[]()~`>#+-=|{}.!\\"


def _escape_markdown(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2.

    Per Telegram docs, these characters must be escaped with backslash:
    _ * [ ] ( ) ~ ` > # + - = | { } . ! \\
    """
    result = []
    for char in text:
        if char in _ESCAPE_CHARS:
            result.append(f"\\{char}")
        else:
            result.append(char)
    return "".join(result)


class TelegramNotifier:
    """Sends notifications via Telegram Bot API.

    Usage::

        notifier = TelegramNotifier(
            bot_token=settings.telegram_bot_token,
            chat_id=settings.telegram_chat_id,
        )
        notifier.notify("Agent started", Level.INFO)
        notifier.notify("Post created: AI Agents 101", Level.SUCCESS)

    If bot_token or chat_id is None, all calls are no-ops (graceful degradation).
    """

    def __init__(
        self,
        bot_token: SecretStr | None = None,
        chat_id: str | None = None,
    ) -> None:
        self._bot_token = bot_token
        self._chat_id = chat_id
        self._enabled = bot_token is not None and chat_id is not None

        if not self._enabled:
            logger.warning("Telegram notifier disabled: missing bot_token or chat_id")

    @property
    def enabled(self) -> bool:
        """Whether the notifier is configured and active."""
        return self._enabled

    def notify(self, message: str, level: Level = Level.INFO) -> bool:
        """Send a notification message.

        Args:
            message: Plain text message to send.
            level: Severity level (affects prefix emoji).

        Returns:
            True if sent successfully, False otherwise.
            Always returns False if notifier is disabled.
        """
        if not self._enabled:
            logger.debug("Telegram disabled, skipping: %s", message)
            return False

        prefix = _LEVEL_PREFIX.get(level, "")
        level_text = _escape_markdown(level.value.upper())
        msg_text = _escape_markdown(message)
        formatted = f"{prefix} *{level_text}*\n{msg_text}"

        return self._send(formatted)

    def _send(self, text: str) -> bool:
        """Send a message via Telegram Bot API.

        Uses httpx directly (not E2B) — this is monitoring infrastructure,
        not an agent action. Failures are logged but never crash the agent.
        """
        if self._bot_token is None:
            logger.warning("_send called but bot_token is None")
            return False
        token = self._bot_token.get_secret_value()
        url = f"https://api.telegram.org/bot{token}/sendMessage"

        try:
            response = httpx.post(
                url,
                json={
                    "chat_id": self._chat_id,
                    "text": text,
                    "parse_mode": "MarkdownV2",
                },
                timeout=10,
            )
            if response.status_code == 200:
                logger.debug("Telegram message sent")
                return True

            logger.warning(
                "Telegram API returned %d: %s",
                response.status_code,
                response.text[:200],
            )
            return False

        except Exception:
            logger.exception("Failed to send Telegram message")
            return False
