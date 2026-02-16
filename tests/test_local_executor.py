"""Tests for social_agent.local_executor.

LocalExecutor is a drop-in replacement for SandboxClient that
executes code locally via subprocess. These tests verify the
interface matches SandboxClient's output types.
"""

from __future__ import annotations

import pytest

from social_agent.local_executor import LocalExecutor
from social_agent.sandbox import BashResult, ExecutionResult


# --- Lifecycle ---


class TestLifecycle:
    """Tests for start/stop/context manager."""

    def test_not_running_initially(self) -> None:
        """Executor is not running before start()."""
        executor = LocalExecutor()
        assert not executor.is_running

    def test_start_sets_running(self) -> None:
        """start() marks executor as running."""
        executor = LocalExecutor()
        executor.start()
        assert executor.is_running
        executor.stop()

    def test_stop_clears_running(self) -> None:
        """stop() marks executor as not running."""
        executor = LocalExecutor()
        executor.start()
        executor.stop()
        assert not executor.is_running

    def test_start_idempotent(self) -> None:
        """Calling start() multiple times is safe."""
        executor = LocalExecutor()
        executor.start()
        executor.start()  # Should not raise
        assert executor.is_running
        executor.stop()

    def test_stop_idempotent(self) -> None:
        """Calling stop() without start is safe."""
        executor = LocalExecutor()
        executor.stop()  # Should not raise
        assert not executor.is_running

    def test_context_manager(self) -> None:
        """Context manager starts and stops properly."""
        executor = LocalExecutor()
        with executor:
            assert executor.is_running
        assert not executor.is_running


# --- execute_code ---


class TestExecuteCode:
    """Tests for Python code execution."""

    def test_simple_print(self) -> None:
        """Simple print produces stdout."""
        with LocalExecutor() as executor:
            result = executor.execute_code("print('hello world')")

        assert isinstance(result, ExecutionResult)
        assert result.success is True
        assert "hello world" in result.stdout
        assert result.error is None

    def test_stdout_lines(self) -> None:
        """Multiple prints produce multiple stdout lines."""
        with LocalExecutor() as executor:
            result = executor.execute_code("print('line1')\nprint('line2')")

        assert result.success is True
        assert len(result.stdout) == 2
        assert result.stdout[0] == "line1"
        assert result.stdout[1] == "line2"

    def test_text_is_last_stdout(self) -> None:
        """text field is the last stdout line (matches E2B behavior)."""
        with LocalExecutor() as executor:
            result = executor.execute_code("print('first')\nprint('last')")

        assert result.text == "last"

    def test_syntax_error(self) -> None:
        """Invalid Python produces error."""
        with LocalExecutor() as executor:
            result = executor.execute_code("def incomplete(")

        assert result.success is False
        assert result.error is not None
        assert "SyntaxError" in result.error

    def test_runtime_error(self) -> None:
        """Runtime exception produces error."""
        with LocalExecutor() as executor:
            result = executor.execute_code("raise ValueError('test error')")

        assert result.success is False
        assert result.error is not None
        assert "ValueError" in result.error

    def test_import_and_compute(self) -> None:
        """Can import stdlib and compute."""
        code = "import json\nprint(json.dumps({'a': 1}))"
        with LocalExecutor() as executor:
            result = executor.execute_code(code)

        assert result.success is True
        assert '{"a": 1}' in result.stdout[0]

    def test_empty_code(self) -> None:
        """Empty code succeeds with no output."""
        with LocalExecutor() as executor:
            result = executor.execute_code("")

        assert result.success is True
        assert result.stdout == []

    def test_auto_starts_on_execute(self) -> None:
        """execute_code auto-starts if not started."""
        executor = LocalExecutor()
        assert not executor.is_running
        result = executor.execute_code("print('auto')")
        assert result.success is True
        assert executor.is_running
        executor.stop()

    def test_stderr_captured(self) -> None:
        """stderr output is captured."""
        code = "import sys; print('err', file=sys.stderr)"
        with LocalExecutor() as executor:
            result = executor.execute_code(code)

        assert result.success is True
        assert len(result.stderr) > 0
        assert "err" in result.stderr[0]


# --- run_bash ---


class TestRunBash:
    """Tests for bash command execution."""

    def test_simple_command(self) -> None:
        """Simple bash command works."""
        with LocalExecutor() as executor:
            result = executor.run_bash("echo 'hello'")

        assert isinstance(result, BashResult)
        assert result.success is True
        assert "hello" in result.stdout
        assert result.exit_code == 0

    def test_failing_command(self) -> None:
        """Command that exits non-zero reports failure."""
        with LocalExecutor() as executor:
            result = executor.run_bash("exit 1")

        assert result.success is False
        assert result.exit_code == 1

    def test_command_with_stderr(self) -> None:
        """Command stderr is captured."""
        with LocalExecutor() as executor:
            result = executor.run_bash("echo 'err' >&2")

        assert "err" in result.stderr

    def test_nonexistent_command(self) -> None:
        """Nonexistent command fails gracefully."""
        with LocalExecutor() as executor:
            result = executor.run_bash("nonexistent_command_xyz")

        assert result.success is False

    def test_auto_starts_on_bash(self) -> None:
        """run_bash auto-starts if not started."""
        executor = LocalExecutor()
        result = executor.run_bash("echo 'auto'")
        assert result.success is True
        assert executor.is_running
        executor.stop()


# --- Interface compatibility ---


class TestInterfaceCompat:
    """Verify LocalExecutor matches SandboxClient interface."""

    def test_has_execute_code(self) -> None:
        """LocalExecutor has execute_code method."""
        assert hasattr(LocalExecutor, "execute_code")

    def test_has_run_bash(self) -> None:
        """LocalExecutor has run_bash method."""
        assert hasattr(LocalExecutor, "run_bash")

    def test_has_start_stop(self) -> None:
        """LocalExecutor has start/stop methods."""
        assert hasattr(LocalExecutor, "start")
        assert hasattr(LocalExecutor, "stop")

    def test_has_is_running(self) -> None:
        """LocalExecutor has is_running property."""
        executor = LocalExecutor()
        assert hasattr(executor, "is_running")

    def test_has_context_manager(self) -> None:
        """LocalExecutor supports context manager protocol."""
        assert hasattr(LocalExecutor, "__enter__")
        assert hasattr(LocalExecutor, "__exit__")

    def test_execute_returns_execution_result(self) -> None:
        """execute_code returns the same ExecutionResult type as SandboxClient."""
        with LocalExecutor() as executor:
            result = executor.execute_code("print(1)")
        assert isinstance(result, ExecutionResult)

    def test_bash_returns_bash_result(self) -> None:
        """run_bash returns the same BashResult type as SandboxClient."""
        with LocalExecutor() as executor:
            result = executor.run_bash("echo 1")
        assert isinstance(result, BashResult)


# --- HTTP code execution (validates MoltbookClient compat) ---


class TestHTTPCodeExecution:
    """Tests that HTTP code patterns from MoltbookClient work in LocalExecutor."""

    def test_json_output_pattern(self) -> None:
        """The JSON output pattern used by MoltbookClient parses correctly."""
        # This mirrors _build_http_code output format
        code = (
            "import json\n"
            "result = {'status': 200, 'body': {'id': '123'}}\n"
            "print(json.dumps(result))\n"
        )
        with LocalExecutor() as executor:
            result = executor.execute_code(code)

        assert result.success is True
        assert len(result.stdout) > 0
        # Verify the JSON is parseable (like _parse_response does)
        import json

        parsed = json.loads(result.stdout[0])
        assert parsed["status"] == 200
        assert parsed["body"]["id"] == "123"

    @pytest.mark.skipif(
        True,  # Skip by default — requires httpx installed
        reason="Requires httpx package",
    )
    def test_httpx_available(self) -> None:
        """httpx can be imported (after package install)."""
        code = "import httpx; print('httpx ok')"
        with LocalExecutor() as executor:
            result = executor.execute_code(code)
        assert result.success is True
