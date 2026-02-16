"""Local executor — drop-in replacement for SandboxClient.

Used when the agent runs inside E2B (or any Linux environment) directly.
Since the agent IS already sandboxed, we execute code locally via subprocess
instead of creating a nested E2B sandbox.

Same interface as SandboxClient: execute_code(), run_bash(), start(), stop().
Returns the same ExecutionResult and BashResult types.
"""

from __future__ import annotations

import logging
import subprocess
import sys
import tempfile
from pathlib import Path

from social_agent.sandbox import BashResult, ExecutionResult

logger = logging.getLogger(__name__)

# Packages required for HTTP operations (same as SandboxClient).
_REQUIRED_PACKAGES = ("httpx", "duckduckgo-search")


class LocalExecutor:
    """Executes Python code and bash commands locally via subprocess.

    Drop-in replacement for SandboxClient when running inside E2B
    or any isolated environment. No E2B API key needed.

    Usage::

        executor = LocalExecutor()

        with executor:
            result = executor.execute_code("print('hello')")
            bash = executor.run_bash("ls -la")

    """

    def __init__(self, *, python_path: str | None = None) -> None:
        self._python = python_path or sys.executable
        self._started = False
        self._packages_installed = False

    @property
    def is_running(self) -> bool:
        """Check if executor is active."""
        return self._started

    def start(self) -> None:
        """Initialize the executor. Installs required packages on first call."""
        if self._started:
            return
        self._started = True
        logger.info("LocalExecutor started (python=%s)", self._python)
        self._install_packages()

    def stop(self) -> None:
        """Stop the executor (no-op for local, but matches interface)."""
        if not self._started:
            return
        self._started = False
        logger.info("LocalExecutor stopped")

    def _install_packages(self) -> None:
        """Install required packages if not already available."""
        if self._packages_installed:
            return

        for pkg in _REQUIRED_PACKAGES:
            import_name = pkg.replace("-", "_")
            try:
                # Check if already importable
                subprocess.run(
                    [self._python, "-c", f"import {import_name}"],
                    capture_output=True,
                    timeout=10,
                    check=True,
                )
                logger.debug("Package already available: %s", pkg)
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                # Install it
                logger.info("Installing package: %s", pkg)
                try:
                    subprocess.run(
                        [self._python, "-m", "pip", "install", "-q", pkg],
                        capture_output=True,
                        timeout=120,
                        check=True,
                    )
                    logger.info("Installed: %s", pkg)
                except Exception:
                    logger.warning("Failed to install %s", pkg, exc_info=True)

        self._packages_installed = True

    def execute_code(self, code: str) -> ExecutionResult:
        """Execute Python code in a subprocess.

        Writes code to a temp file and runs it. Captures stdout/stderr.
        Matches SandboxClient.execute_code() interface exactly.

        Args:
            code: Python code to execute.

        Returns:
            ExecutionResult with stdout, stderr, text output, and success flag.
        """
        if not self._started:
            self.start()

        try:
            # Write code to temp file for clean execution
            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".py",
                delete=False,
                dir="/tmp",
            ) as f:
                f.write(code)
                tmp_path = f.name

            result = subprocess.run(
                [self._python, tmp_path],
                capture_output=True,
                text=True,
                timeout=60,
            )

            # Clean up temp file
            Path(tmp_path).unlink(missing_ok=True)

            stdout_lines = result.stdout.splitlines() if result.stdout else []
            stderr_lines = result.stderr.splitlines() if result.stderr else []

            # Last line of stdout is the "text" output (matches E2B behavior)
            text = stdout_lines[-1] if stdout_lines else None

            if result.returncode != 0:
                error_msg = result.stderr.strip() if result.stderr else f"Exit code {result.returncode}"
                return ExecutionResult(
                    stdout=stdout_lines,
                    stderr=stderr_lines,
                    text=text,
                    success=False,
                    error=error_msg,
                )

            return ExecutionResult(
                stdout=stdout_lines,
                stderr=stderr_lines,
                text=text,
                success=True,
            )

        except subprocess.TimeoutExpired:
            Path(tmp_path).unlink(missing_ok=True)
            return ExecutionResult(
                success=False,
                error="Code execution timed out (60s)",
            )
        except Exception as e:
            logger.exception("Code execution failed: %s", e)
            return ExecutionResult(success=False, error=str(e))

    def run_bash(self, command: str, timeout: float = 60) -> BashResult:
        """Run a bash command locally.

        Matches SandboxClient.run_bash() interface exactly.

        Args:
            command: Shell command to execute.
            timeout: Maximum seconds to wait (default 60).

        Returns:
            BashResult with stdout, stderr, exit code, and success flag.
        """
        if not self._started:
            self.start()

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
            )

            return BashResult(
                stdout=result.stdout,
                stderr=result.stderr,
                exit_code=result.returncode,
                success=result.returncode == 0,
            )

        except subprocess.TimeoutExpired:
            return BashResult(
                success=False,
                error=f"Command timed out ({timeout}s)",
            )
        except Exception as e:
            logger.exception("Bash command failed: %s", e)
            return BashResult(success=False, error=str(e))

    def __enter__(self) -> LocalExecutor:
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop()
