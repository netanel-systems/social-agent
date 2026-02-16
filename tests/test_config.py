"""Tests for social_agent.config.

All tests use explicit values — no real .env file needed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from social_agent.config import ExecutorMode, Settings, get_settings

if TYPE_CHECKING:
    from pathlib import Path

# --- Fixtures ---


@pytest.fixture
def required_env(tmp_path: Path) -> dict[str, object]:
    """Minimal required fields for a valid Settings.

    _env_file=None prevents BaseSettings from reading the real .env file.
    Combined with conftest.py's autouse fixture that clears env vars,
    this ensures full test isolation.
    """
    return {
        "_env_file": None,
        "openai_api_key": "sk-test-key",
        "e2b_api_key": "e2b_test_key",
        "memories_dir": tmp_path / "memories",
    }


# --- Required fields ---


def test_valid_settings(required_env: dict[str, object]) -> None:
    """Settings created with required fields succeeds."""
    settings = Settings(**required_env)  # type: ignore[arg-type]
    assert settings.openai_api_key.get_secret_value() == "sk-test-key"
    assert settings.e2b_api_key.get_secret_value() == "e2b_test_key"


def test_missing_openai_key(tmp_path: Path) -> None:
    """Missing openai_api_key raises ValidationError."""
    with pytest.raises(ValidationError, match="openai_api_key"):
        Settings(_env_file=None, e2b_api_key="e2b_test", memories_dir=tmp_path / "mem")  # type: ignore[call-arg]


def test_missing_e2b_key_sandbox_mode(tmp_path: Path) -> None:
    """Missing e2b_api_key in sandbox mode raises ValidationError."""
    with pytest.raises(ValidationError, match="e2b_api_key"):
        Settings(
            _env_file=None,
            openai_api_key="sk-test",
            executor_mode="sandbox",
            memories_dir=tmp_path / "mem",
        )  # type: ignore[call-arg]


def test_missing_e2b_key_local_mode(tmp_path: Path) -> None:
    """Missing e2b_api_key in local mode is fine."""
    settings = Settings(
        _env_file=None,
        openai_api_key="sk-test",
        executor_mode="local",
        memories_dir=tmp_path / "mem",
    )  # type: ignore[call-arg]
    assert settings.e2b_api_key is None
    assert settings.executor_mode == ExecutorMode.LOCAL


# --- Defaults ---


def test_default_cycle_interval(required_env: dict[str, object]) -> None:
    """Default cycle interval is 15 seconds (testing mode)."""
    settings = Settings(**required_env)  # type: ignore[arg-type]
    assert settings.cycle_interval_seconds == 15


def test_default_max_posts(required_env: dict[str, object]) -> None:
    """Default max posts per day is 5."""
    settings = Settings(**required_env)  # type: ignore[arg-type]
    assert settings.max_posts_per_day == 5


def test_default_max_replies(required_env: dict[str, object]) -> None:
    """Default max replies per day is 20."""
    settings = Settings(**required_env)  # type: ignore[arg-type]
    assert settings.max_replies_per_day == 20


def test_default_max_cycles(required_env: dict[str, object]) -> None:
    """Default max cycles is 500 (JPL Rule 1)."""
    settings = Settings(**required_env)  # type: ignore[arg-type]
    assert settings.max_cycles == 500


def test_default_quality_threshold(required_env: dict[str, object]) -> None:
    """Default quality threshold is 0.7."""
    settings = Settings(**required_env)  # type: ignore[arg-type]
    assert settings.quality_threshold == 0.7


def test_default_circuit_breaker(required_env: dict[str, object]) -> None:
    """Default circuit breaker is 5 consecutive failures."""
    settings = Settings(**required_env)  # type: ignore[arg-type]
    assert settings.circuit_breaker_threshold == 5


# --- Optional fields ---


def test_optional_fields_default_none(required_env: dict[str, object]) -> None:
    """Optional fields default to None."""
    settings = Settings(**required_env)  # type: ignore[arg-type]
    assert settings.moltbook_api_key is None
    assert settings.telegram_bot_token is None
    assert settings.telegram_chat_id is None


def test_optional_fields_set(required_env: dict[str, object]) -> None:
    """Optional fields can be set."""
    settings = Settings(
        **required_env,  # type: ignore[arg-type]
        moltbook_api_key="molt_test",
        telegram_bot_token="bot_test",
        telegram_chat_id="12345",
    )
    assert settings.moltbook_api_key is not None
    assert settings.moltbook_api_key.get_secret_value() == "molt_test"
    assert settings.telegram_bot_token is not None
    assert settings.telegram_bot_token.get_secret_value() == "bot_test"
    assert settings.telegram_chat_id == "12345"


# --- Secrets are hidden ---


def test_secrets_not_in_repr(required_env: dict[str, object]) -> None:
    """API keys must not appear in repr (security)."""
    settings = Settings(**required_env)  # type: ignore[arg-type]
    r = repr(settings)
    assert "sk-test-key" not in r
    assert "e2b_test_key" not in r


# --- Validators ---


def test_cycle_interval_too_low(required_env: dict[str, object]) -> None:
    """Cycle interval below minimum raises ValidationError."""
    with pytest.raises(ValidationError, match="cycle_interval_seconds"):
        Settings(**required_env, cycle_interval_seconds=5)  # type: ignore[arg-type]


def test_cycle_interval_at_minimum(required_env: dict[str, object]) -> None:
    """Cycle interval at minimum is valid."""
    settings = Settings(**required_env, cycle_interval_seconds=10)  # type: ignore[arg-type]
    assert settings.cycle_interval_seconds == 10


def test_quality_threshold_too_high(required_env: dict[str, object]) -> None:
    """Quality threshold > 1.0 raises ValidationError."""
    with pytest.raises(ValidationError, match="quality_threshold"):
        Settings(**required_env, quality_threshold=1.5)  # type: ignore[arg-type]


def test_quality_threshold_negative(required_env: dict[str, object]) -> None:
    """Quality threshold < 0.0 raises ValidationError."""
    with pytest.raises(ValidationError, match="quality_threshold"):
        Settings(**required_env, quality_threshold=-0.1)  # type: ignore[arg-type]


def test_quality_threshold_boundaries(required_env: dict[str, object]) -> None:
    """Quality threshold 0.0 and 1.0 are both valid."""
    s_zero = Settings(**required_env, quality_threshold=0.0)  # type: ignore[arg-type]
    assert s_zero.quality_threshold == 0.0
    s_one = Settings(**required_env, quality_threshold=1.0)  # type: ignore[arg-type]
    assert s_one.quality_threshold == 1.0


def test_zero_max_posts_rejected(required_env: dict[str, object]) -> None:
    """Zero max_posts_per_day raises ValidationError."""
    with pytest.raises(ValidationError, match="positive"):
        Settings(**required_env, max_posts_per_day=0)  # type: ignore[arg-type]


def test_negative_max_cycles_rejected(required_env: dict[str, object]) -> None:
    """Negative max_cycles raises ValidationError."""
    with pytest.raises(ValidationError, match="positive"):
        Settings(**required_env, max_cycles=-1)  # type: ignore[arg-type]


def test_zero_circuit_breaker_rejected(required_env: dict[str, object]) -> None:
    """Zero circuit_breaker_threshold raises ValidationError."""
    with pytest.raises(ValidationError, match="positive"):
        Settings(**required_env, circuit_breaker_threshold=0)  # type: ignore[arg-type]


# --- extra="forbid" ---


def test_extra_fields_rejected(required_env: dict[str, object]) -> None:
    """Unknown fields raise ValidationError (catches typos)."""
    with pytest.raises(ValidationError, match="extra"):
        Settings(**required_env, unknown_field="oops")  # type: ignore[arg-type]


# --- memories_dir ---


def test_memories_dir_created(required_env: dict[str, object]) -> None:
    """Memories directory is created on settings init."""
    settings = Settings(**required_env)  # type: ignore[arg-type]
    assert settings.memories_dir.exists()
    assert settings.memories_dir.is_dir()


# --- get_settings helper ---


def test_get_settings_with_overrides(tmp_path: Path) -> None:
    """get_settings passes overrides correctly."""
    settings = get_settings(
        _env_file=None,
        openai_api_key="sk-override",
        e2b_api_key="e2b_override",
        memories_dir=tmp_path / "override_mem",
        max_posts_per_day=10,
    )
    assert settings.openai_api_key.get_secret_value() == "sk-override"
    assert settings.max_posts_per_day == 10


# --- LangSmith fields ---


def test_langsmith_defaults(required_env: dict[str, object]) -> None:
    """LangSmith tracing defaults to False, project to 'social-agent'."""
    settings = Settings(**required_env)  # type: ignore[arg-type]
    assert settings.langsmith_tracing is False
    assert settings.langsmith_project == "social-agent"
    assert settings.langsmith_api_key is None


# --- Executor mode ---


def test_default_executor_mode(required_env: dict[str, object]) -> None:
    """Default executor mode is sandbox."""
    settings = Settings(**required_env)  # type: ignore[arg-type]
    assert settings.executor_mode == ExecutorMode.SANDBOX


def test_local_executor_mode(tmp_path: Path) -> None:
    """Local executor mode works without E2B key."""
    settings = Settings(
        _env_file=None,
        openai_api_key="sk-test",
        executor_mode="local",
        memories_dir=tmp_path / "mem",
    )  # type: ignore[call-arg]
    assert settings.executor_mode == ExecutorMode.LOCAL
    assert settings.e2b_api_key is None


def test_sandbox_mode_requires_e2b_key(tmp_path: Path) -> None:
    """Sandbox mode requires E2B API key."""
    with pytest.raises(ValidationError, match="e2b_api_key"):
        Settings(
            _env_file=None,
            openai_api_key="sk-test",
            executor_mode="sandbox",
            memories_dir=tmp_path / "mem",
        )  # type: ignore[call-arg]


def test_invalid_executor_mode(required_env: dict[str, object]) -> None:
    """Invalid executor mode raises ValidationError."""
    with pytest.raises(ValidationError):
        Settings(**required_env, executor_mode="invalid")  # type: ignore[arg-type]
