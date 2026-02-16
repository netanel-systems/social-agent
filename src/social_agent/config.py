"""Configuration for social-agent.

Loads from environment variables and .env file.
All limits explicit. All secrets use SecretStr.
"""

from __future__ import annotations

import os
from enum import StrEnum
from pathlib import Path
from typing import Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# --- Defaults (Architecture Section 6) ---
_DEFAULT_CYCLE_INTERVAL = 15  # 15 seconds (testing mode)
_DEFAULT_MAX_POSTS = 5
_DEFAULT_MAX_REPLIES = 20
_DEFAULT_MAX_CYCLES = 500
_DEFAULT_QUALITY_THRESHOLD = 0.7
_DEFAULT_CIRCUIT_BREAKER = 5
_MIN_CYCLE_INTERVAL = 10  # 10 second floor (testing)


class ExecutorMode(StrEnum):
    """Execution mode for the agent's external actions.

    SANDBOX: Use E2B sandbox (default, for local machine).
    LOCAL: Execute directly (for running inside E2B or any isolated env).
    """

    SANDBOX = "sandbox"
    LOCAL = "local"


def detect_e2b_environment() -> bool:
    """Detect if we're running inside an E2B sandbox.

    E2B sandboxes set specific environment markers.
    """
    return os.environ.get("E2B_SANDBOX") == "true" or Path("/.e2b").exists()


class Settings(BaseSettings):
    """Application settings loaded from environment / .env file.

    All API keys use SecretStr — never leaked in logs or repr.
    Safety bounds enforced via validators. extra="forbid" catches typos.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="forbid",
    )

    # --- Executor mode ---
    executor_mode: ExecutorMode = Field(
        default=ExecutorMode.SANDBOX,
        description="Execution mode: 'sandbox' (E2B) or 'local' (direct)",
    )

    # --- Required secrets ---
    openai_api_key: SecretStr
    e2b_api_key: SecretStr | None = Field(
        default=None,
        description="E2B API key (required only in sandbox mode)",
    )

    # --- Optional secrets (not needed for Step 1) ---
    moltbook_api_key: SecretStr | None = None
    telegram_bot_token: SecretStr | None = None
    telegram_chat_id: str | None = None

    # --- LangSmith (optional, auto-enabled via env vars) ---
    langsmith_tracing: bool = Field(default=False)
    langsmith_api_key: SecretStr | None = None
    langsmith_project: str = "social-agent"

    # --- Safety bounds (Architecture Section 6) ---
    cycle_interval_seconds: int = Field(
        default=_DEFAULT_CYCLE_INTERVAL,
        description="Seconds between agent cycles",
    )
    max_posts_per_day: int = Field(
        default=_DEFAULT_MAX_POSTS,
        description="Maximum original posts per day",
    )
    max_replies_per_day: int = Field(
        default=_DEFAULT_MAX_REPLIES,
        description="Maximum replies per day",
    )
    max_cycles: int = Field(
        default=_DEFAULT_MAX_CYCLES,
        description="Maximum cycles per session (JPL Rule 1)",
    )
    quality_threshold: float = Field(
        default=_DEFAULT_QUALITY_THRESHOLD,
        description="Minimum score before posting",
    )
    circuit_breaker_threshold: int = Field(
        default=_DEFAULT_CIRCUIT_BREAKER,
        description="Consecutive failures before auto-pause",
    )

    # --- Paths ---
    memories_dir: Path = Field(
        default=Path("memories"),
        description="Directory for netanel-core memory files",
    )

    # --- Validators ---

    @field_validator("cycle_interval_seconds")
    @classmethod
    def cycle_interval_minimum(cls, v: int) -> int:
        """Enforce minimum cycle interval to prevent API abuse."""
        if v < _MIN_CYCLE_INTERVAL:
            msg = f"cycle_interval_seconds must be >= {_MIN_CYCLE_INTERVAL}, got {v}"
            raise ValueError(msg)
        return v

    @field_validator("quality_threshold")
    @classmethod
    def quality_threshold_range(cls, v: float) -> float:
        """Quality threshold must be between 0.0 and 1.0."""
        if not 0.0 <= v <= 1.0:
            msg = f"quality_threshold must be between 0.0 and 1.0, got {v}"
            raise ValueError(msg)
        return v

    @field_validator(
        "max_posts_per_day", "max_replies_per_day", "max_cycles", "circuit_breaker_threshold"
    )
    @classmethod
    def positive_limits(cls, v: int) -> int:
        """All limits must be positive."""
        if v <= 0:
            msg = f"Limit must be positive, got {v}"
            raise ValueError(msg)
        return v

    @model_validator(mode="after")
    def validate_executor_requirements(self) -> Self:
        """Validate executor-specific requirements and create directories."""
        if self.executor_mode == ExecutorMode.SANDBOX and self.e2b_api_key is None:
            msg = "e2b_api_key is required when executor_mode='sandbox'"
            raise ValueError(msg)
        if self.executor_mode == ExecutorMode.LOCAL and not detect_e2b_environment():
            msg = "executor_mode='local' is only allowed inside an E2B sandbox"
            raise ValueError(msg)
        self.memories_dir.mkdir(parents=True, exist_ok=True)
        return self


def get_settings(**overrides: object) -> Settings:
    """Create settings, optionally overriding values.

    Useful for testing where you want to pass explicit values
    instead of reading from environment.
    """
    return Settings(**overrides)  # type: ignore[arg-type]
