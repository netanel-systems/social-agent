"""Tests for social_agent.sandbox.

All tests use mocks — no real E2B sandbox created.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from pydantic import SecretStr

from social_agent.sandbox import BashResult, ExecutionResult, SandboxClient

# --- Fixtures ---


@pytest.fixture
def api_key() -> SecretStr:
    """Test API key."""
    return SecretStr("e2b_test_key")


@pytest.fixture
def mock_sandbox() -> MagicMock:
    """Mock E2B Sandbox instance."""
    sandbox = MagicMock()
    sandbox.sandbox_id = "test-sandbox-123"
    return sandbox


# --- ExecutionResult ---


def test_execution_result_defaults() -> None:
    """Default ExecutionResult is successful with empty output."""
    result = ExecutionResult()
    assert result.success is True
    assert result.stdout == []
    assert result.stderr == []
    assert result.text is None
    assert result.error is None


def test_execution_result_with_error() -> None:
    """ExecutionResult can represent a failure."""
    result = ExecutionResult(
        success=False,
        error="NameError: name 'x' is not defined",
        stdout=["partial output"],
    )
    assert result.success is False
    assert result.error == "NameError: name 'x' is not defined"
    assert result.stdout == ["partial output"]


def test_execution_result_frozen() -> None:
    """ExecutionResult is immutable."""
    result = ExecutionResult()
    with pytest.raises(AttributeError):
        result.success = False  # type: ignore[misc]


# --- BashResult ---


def test_bash_result_defaults() -> None:
    """Default BashResult is successful."""
    result = BashResult()
    assert result.success is True
    assert result.stdout == ""
    assert result.stderr == ""
    assert result.exit_code is None
    assert result.error is None


def test_bash_result_with_failure() -> None:
    """BashResult can represent a command failure."""
    result = BashResult(
        stdout="",
        stderr="command not found",
        exit_code=127,
        success=False,
    )
    assert result.success is False
    assert result.exit_code == 127


def test_bash_result_frozen() -> None:
    """BashResult is immutable."""
    result = BashResult()
    with pytest.raises(AttributeError):
        result.exit_code = 1  # type: ignore[misc]


# --- SandboxClient lifecycle ---


def test_client_not_running_initially(api_key: SecretStr) -> None:
    """Client starts without a sandbox."""
    client = SandboxClient(api_key=api_key)
    assert client.is_running is False


@patch("social_agent.sandbox.Sandbox")
def test_start_creates_sandbox(mock_sandbox_cls: MagicMock, api_key: SecretStr) -> None:
    """start() creates an E2B sandbox."""
    mock_sandbox_cls.return_value = MagicMock(sandbox_id="sb-1")
    client = SandboxClient(api_key=api_key, timeout=120)

    client.start()

    assert client.is_running is True
    mock_sandbox_cls.assert_called_once_with(
        api_key="e2b_test_key",
        timeout=120,
    )


@patch("social_agent.sandbox.Sandbox")
def test_start_idempotent(mock_sandbox_cls: MagicMock, api_key: SecretStr) -> None:
    """Calling start() twice doesn't create a second sandbox."""
    mock_sandbox_cls.return_value = MagicMock(sandbox_id="sb-1")
    client = SandboxClient(api_key=api_key)

    client.start()
    client.start()

    mock_sandbox_cls.assert_called_once()


@patch("social_agent.sandbox.Sandbox")
def test_stop_kills_sandbox(mock_sandbox_cls: MagicMock, api_key: SecretStr) -> None:
    """stop() kills the sandbox and resets state."""
    mock_instance = MagicMock(sandbox_id="sb-1")
    mock_sandbox_cls.return_value = mock_instance
    client = SandboxClient(api_key=api_key)

    client.start()
    client.stop()

    mock_instance.kill.assert_called_once()
    assert client.is_running is False


def test_stop_without_start(api_key: SecretStr) -> None:
    """stop() without start() is a no-op."""
    client = SandboxClient(api_key=api_key)
    client.stop()  # Should not raise
    assert client.is_running is False


# --- Context manager ---


@patch("social_agent.sandbox.Sandbox")
def test_context_manager(mock_sandbox_cls: MagicMock, api_key: SecretStr) -> None:
    """Context manager starts and stops the sandbox."""
    mock_instance = MagicMock(sandbox_id="sb-1")
    mock_sandbox_cls.return_value = mock_instance

    with SandboxClient(api_key=api_key) as client:
        assert client.is_running is True

    mock_instance.kill.assert_called_once()


# --- execute_code ---


@patch("social_agent.sandbox.Sandbox")
def test_execute_code_success(
    mock_sandbox_cls: MagicMock, api_key: SecretStr
) -> None:
    """execute_code returns structured result on success."""
    mock_execution = MagicMock()
    mock_execution.error = None
    mock_execution.logs.stdout = ["hello"]
    mock_execution.logs.stderr = []
    mock_execution.text = "hello"

    mock_instance = MagicMock(sandbox_id="sb-1")
    mock_instance.run_code.return_value = mock_execution
    mock_sandbox_cls.return_value = mock_instance

    client = SandboxClient(api_key=api_key)
    result = client.execute_code("print('hello')")

    assert result.success is True
    assert result.stdout == ["hello"]
    assert result.text == "hello"
    assert result.error is None


@patch("social_agent.sandbox.Sandbox")
def test_execute_code_with_error(
    mock_sandbox_cls: MagicMock, api_key: SecretStr
) -> None:
    """execute_code captures execution errors."""
    mock_error = MagicMock()
    mock_error.name = "NameError"
    mock_error.value = "name 'x' is not defined"

    mock_execution = MagicMock()
    mock_execution.error = mock_error
    mock_execution.logs.stdout = []
    mock_execution.logs.stderr = ["Traceback..."]
    mock_execution.text = None

    mock_instance = MagicMock(sandbox_id="sb-1")
    mock_instance.run_code.return_value = mock_execution
    mock_sandbox_cls.return_value = mock_instance

    client = SandboxClient(api_key=api_key)
    result = client.execute_code("print(x)")

    assert result.success is False
    assert result.error == "NameError: name 'x' is not defined"
    assert result.stderr == ["Traceback..."]


@patch("social_agent.sandbox.Sandbox")
def test_execute_code_exception(
    mock_sandbox_cls: MagicMock, api_key: SecretStr
) -> None:
    """execute_code handles SDK exceptions gracefully."""
    mock_instance = MagicMock(sandbox_id="sb-1")
    mock_instance.run_code.side_effect = ConnectionError("network down")
    mock_sandbox_cls.return_value = mock_instance

    client = SandboxClient(api_key=api_key)
    result = client.execute_code("1 + 1")

    assert result.success is False
    assert "network down" in (result.error or "")


# --- run_bash ---


@patch("social_agent.sandbox.Sandbox")
def test_run_bash_success(mock_sandbox_cls: MagicMock, api_key: SecretStr) -> None:
    """run_bash returns structured result on success."""
    mock_cmd_result = MagicMock()
    mock_cmd_result.stdout = "file1.txt\nfile2.txt"
    mock_cmd_result.stderr = ""
    mock_cmd_result.exit_code = 0

    mock_instance = MagicMock(sandbox_id="sb-1")
    mock_instance.commands.run.return_value = mock_cmd_result
    mock_sandbox_cls.return_value = mock_instance

    client = SandboxClient(api_key=api_key)
    result = client.run_bash("ls")

    assert result.success is True
    assert result.stdout == "file1.txt\nfile2.txt"
    assert result.exit_code == 0


@patch("social_agent.sandbox.Sandbox")
def test_run_bash_nonzero_exit(mock_sandbox_cls: MagicMock, api_key: SecretStr) -> None:
    """run_bash marks non-zero exit codes as failure."""
    mock_cmd_result = MagicMock()
    mock_cmd_result.stdout = ""
    mock_cmd_result.stderr = "No such file"
    mock_cmd_result.exit_code = 1

    mock_instance = MagicMock(sandbox_id="sb-1")
    mock_instance.commands.run.return_value = mock_cmd_result
    mock_sandbox_cls.return_value = mock_instance

    client = SandboxClient(api_key=api_key)
    result = client.run_bash("cat missing.txt")

    assert result.success is False
    assert result.exit_code == 1
    assert result.stderr == "No such file"


@patch("social_agent.sandbox.Sandbox")
def test_run_bash_exception(mock_sandbox_cls: MagicMock, api_key: SecretStr) -> None:
    """run_bash handles SDK exceptions gracefully."""
    mock_instance = MagicMock(sandbox_id="sb-1")
    mock_instance.commands.run.side_effect = TimeoutError("timed out")
    mock_sandbox_cls.return_value = mock_instance

    client = SandboxClient(api_key=api_key)
    result = client.run_bash("sleep 999")

    assert result.success is False
    assert "timed out" in (result.error or "")


# --- Lazy init ---


@patch("social_agent.sandbox.Sandbox")
def test_lazy_init_on_execute(mock_sandbox_cls: MagicMock, api_key: SecretStr) -> None:
    """Sandbox is created on first execute_code, not at construction."""
    mock_execution = MagicMock()
    mock_execution.error = None
    mock_execution.logs.stdout = []
    mock_execution.logs.stderr = []
    mock_execution.text = None

    mock_instance = MagicMock(sandbox_id="sb-1")
    mock_instance.run_code.return_value = mock_execution
    mock_sandbox_cls.return_value = mock_instance

    client = SandboxClient(api_key=api_key)
    assert client.is_running is False

    client.execute_code("pass")
    assert client.is_running is True
    mock_sandbox_cls.assert_called_once()


@patch("social_agent.sandbox.Sandbox")
def test_lazy_init_on_bash(mock_sandbox_cls: MagicMock, api_key: SecretStr) -> None:
    """Sandbox is created on first run_bash, not at construction."""
    mock_cmd_result = MagicMock()
    mock_cmd_result.stdout = ""
    mock_cmd_result.stderr = ""
    mock_cmd_result.exit_code = 0

    mock_instance = MagicMock(sandbox_id="sb-1")
    mock_instance.commands.run.return_value = mock_cmd_result
    mock_sandbox_cls.return_value = mock_instance

    client = SandboxClient(api_key=api_key)
    assert client.is_running is False

    client.run_bash("echo hi")
    assert client.is_running is True
