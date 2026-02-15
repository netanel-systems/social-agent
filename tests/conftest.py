"""Shared test configuration.

Clears environment variables that pydantic-settings would pick up,
ensuring tests are fully isolated from .env files and system env.
"""

from __future__ import annotations

import pytest

# All env vars that Settings reads — must be cleared for test isolation.
_SETTINGS_ENV_VARS = [
    "OPENAI_API_KEY",
    "E2B_API_KEY",
    "MOLTBOOK_API_KEY",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "LANGSMITH_TRACING",
    "LANGSMITH_API_KEY",
    "LANGSMITH_PROJECT",
]


@pytest.fixture(autouse=True)
def _isolate_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove all Settings-related env vars for every test.

    autouse=True means this applies automatically — no test
    can accidentally read real credentials.
    """
    for var in _SETTINGS_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
