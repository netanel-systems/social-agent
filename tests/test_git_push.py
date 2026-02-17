"""Tests for social_agent.git_push.

Verifies that push_state:
  - Calls git config to set author identity before commit (Issue #57)
  - Calls git add, commit, push in the correct order
  - Returns True on success, False on failure
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from social_agent.git_push import (
    _GIT_AUTHOR_EMAIL,
    _GIT_AUTHOR_NAME,
    push_state,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_run(returncode: int = 0) -> MagicMock:
    """Return a mock for subprocess.run that succeeds by default."""
    mock = MagicMock()
    mock.returncode = returncode
    return mock


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@patch("social_agent.git_push.subprocess.run")
def test_push_state_success(mock_run: MagicMock, tmp_path: Path) -> None:
    """push_state returns True when all git commands succeed."""
    result = push_state(tmp_path, "test commit")
    assert result is True


@patch("social_agent.git_push.subprocess.run")
def test_push_state_calls_git_config_name(mock_run: MagicMock, tmp_path: Path) -> None:
    """push_state configures user.name before committing (Issue #57).

    E2B sandboxes have no global git config — without this, commit
    fails with 'Author identity unknown'.
    """
    push_state(tmp_path, "startup commit")

    calls = mock_run.call_args_list
    # Find the user.name config call
    config_name_calls = [
        c for c in calls
        if "config" in c.args[0] and "user.name" in c.args[0]
    ]
    assert config_name_calls, "git config user.name was not called"
    assert _GIT_AUTHOR_NAME in config_name_calls[0].args[0]


@patch("social_agent.git_push.subprocess.run")
def test_push_state_calls_git_config_email(mock_run: MagicMock, tmp_path: Path) -> None:
    """push_state configures user.email before committing (Issue #57)."""
    push_state(tmp_path, "startup commit")

    calls = mock_run.call_args_list
    config_email_calls = [
        c for c in calls
        if "config" in c.args[0] and "user.email" in c.args[0]
    ]
    assert config_email_calls, "git config user.email was not called"
    assert _GIT_AUTHOR_EMAIL in config_email_calls[0].args[0]


@patch("social_agent.git_push.subprocess.run")
def test_push_state_config_before_commit(mock_run: MagicMock, tmp_path: Path) -> None:
    """git config calls come BEFORE git commit."""
    push_state(tmp_path, "startup commit")

    calls = mock_run.call_args_list
    commands = [" ".join(c.args[0]) for c in calls]

    config_idx = next(
        i for i, cmd in enumerate(commands) if "config" in cmd
    )
    commit_idx = next(i for i, cmd in enumerate(commands) if "commit" in cmd)

    assert config_idx < commit_idx, "config must come before commit"


@patch("social_agent.git_push.subprocess.run")
def test_push_state_calls_add_commit_push(
    mock_run: MagicMock, tmp_path: Path
) -> None:
    """push_state calls git add, commit, and push."""
    push_state(tmp_path, "cycle 42")

    commands = [" ".join(c.args[0]) for c in mock_run.call_args_list]
    assert any("add" in cmd for cmd in commands), "git add not called"
    assert any("commit" in cmd for cmd in commands), "git commit not called"
    assert any("push" in cmd for cmd in commands), "git push not called"


@patch("social_agent.git_push.subprocess.run")
def test_push_state_uses_brain_path(mock_run: MagicMock, tmp_path: Path) -> None:
    """push_state uses the provided brain_path for all git -C commands."""
    push_state(tmp_path, "test")

    for c in mock_run.call_args_list:
        cmd = c.args[0]
        if "git" in cmd and "-C" in cmd:
            assert str(tmp_path) == cmd[cmd.index("-C") + 1]


# ---------------------------------------------------------------------------
# Failure cases
# ---------------------------------------------------------------------------


def test_push_state_missing_path(tmp_path: Path) -> None:
    """push_state returns False when brain_path doesn't exist."""
    result = push_state(tmp_path / "nonexistent", "test")
    assert result is False


@patch("social_agent.git_push.subprocess.run")
def test_push_state_git_failure_returns_false(
    mock_run: MagicMock, tmp_path: Path
) -> None:
    """push_state returns False on CalledProcessError."""
    import subprocess

    mock_run.side_effect = subprocess.CalledProcessError(
        1, ["git", "push"], stderr="Authentication failed"
    )
    result = push_state(tmp_path, "test")
    assert result is False


@patch("social_agent.git_push.subprocess.run")
def test_push_state_timeout_returns_false(
    mock_run: MagicMock, tmp_path: Path
) -> None:
    """push_state returns False on TimeoutExpired."""
    import subprocess

    mock_run.side_effect = subprocess.TimeoutExpired(["git", "push"], 30)
    result = push_state(tmp_path, "test")
    assert result is False
