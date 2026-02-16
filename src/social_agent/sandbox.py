"""E2B sandbox client for isolated code execution.

All agent actions run inside the sandbox — never on the host.
Lazy initialization: sandbox created on first use, not at import.
Context manager support for proper cleanup.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from e2b_code_interpreter import Sandbox

if TYPE_CHECKING:
    from pydantic import SecretStr

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExecutionResult:
    """Result of running Python code in the sandbox."""

    stdout: list[str] = field(default_factory=list)
    stderr: list[str] = field(default_factory=list)
    text: str | None = None
    success: bool = True
    error: str | None = None


@dataclass(frozen=True)
class BashResult:
    """Result of running a bash command in the sandbox."""

    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    success: bool = True
    error: str | None = None


class SandboxClient:
    """Wraps E2B Code Interpreter with lazy init and structured results.

    Usage::

        client = SandboxClient(api_key=settings.e2b_api_key)

        # As context manager (recommended)
        with client:
            result = client.execute_code("print('hello')")
            bash = client.run_bash("ls -la")

        # Manual lifecycle
        client.start()
        result = client.execute_code("1 + 1")
        client.stop()
    """

    def __init__(
        self,
        api_key: SecretStr,
        timeout: int = 300,
    ) -> None:
        self._api_key = api_key
        self._timeout = timeout
        self._sandbox: Sandbox | None = None

    @property
    def is_running(self) -> bool:
        """Check if sandbox is currently active."""
        return self._sandbox is not None

    @property
    def sandbox_id(self) -> str | None:
        """Return the sandbox ID if running, else None."""
        return self._sandbox.sandbox_id if self._sandbox else None

    # Packages required in the sandbox for HTTP operations.
    _SANDBOX_PACKAGES = ("httpx", "duckduckgo-search")

    def start(self) -> None:
        """Create the sandbox. Idempotent — safe to call multiple times."""
        if self._sandbox is not None:
            return
        logger.info("Creating E2B sandbox (timeout=%ds)", self._timeout)
        self._sandbox = Sandbox.create(
            api_key=self._api_key.get_secret_value(),
            timeout=self._timeout,
        )
        logger.info("Sandbox created: %s", self._sandbox.sandbox_id)
        self._install_packages()

    def stop(self) -> None:
        """Kill the sandbox and release resources."""
        if self._sandbox is None:
            return
        sandbox_id = self._sandbox.sandbox_id
        try:
            self._sandbox.kill()
        except Exception:
            logger.warning("Failed to kill sandbox %s", sandbox_id, exc_info=True)
        finally:
            self._sandbox = None
            logger.info("Sandbox stopped: %s", sandbox_id)

    def _install_packages(self) -> None:
        """Install required packages in the sandbox."""
        if not self._sandbox or not self._SANDBOX_PACKAGES:
            return
        pkgs = " ".join(self._SANDBOX_PACKAGES)
        logger.info("Installing sandbox packages: %s", pkgs)
        pkg_args = ", ".join(repr(p) for p in self._SANDBOX_PACKAGES)
        install_code = (
            "import subprocess, sys; "
            "subprocess.run("
            f"[sys.executable, '-m', 'pip', 'install', '-q', {pkg_args}], "
            "capture_output=True, check=True)"
        )
        try:
            result = self._sandbox.run_code(install_code)
            if result.error:
                logger.warning(
                    "Package install warning: %s: %s",
                    result.error.name,
                    result.error.value,
                )
            else:
                logger.info("Sandbox packages installed")
        except Exception:
            logger.exception("Failed to install sandbox packages")

    # Max automatic retries when sandbox expires mid-session.
    _MAX_RECOVERY_RETRIES = 1

    def _ensure_sandbox(self) -> Sandbox:
        """Lazy init — create sandbox on first use."""
        if self._sandbox is None:
            self.start()
        assert self._sandbox is not None
        return self._sandbox

    @staticmethod
    def _is_sandbox_expired(error: Exception) -> bool:
        """Check if an exception indicates the sandbox timed out."""
        msg = str(error).lower()
        return "sandbox was not found" in msg or "sandbox timeout" in msg

    def _recover_sandbox(self) -> Sandbox:
        """Kill stale reference and create a fresh sandbox."""
        logger.warning("Sandbox expired — creating a new one")
        self._sandbox = None
        return self._ensure_sandbox()

    def execute_code(self, code: str) -> ExecutionResult:
        """Execute Python code in the sandbox.

        Auto-recovers if the sandbox has expired (timeout). Creates a new
        sandbox and retries once before reporting failure.

        Args:
            code: Python code to execute.

        Returns:
            ExecutionResult with stdout, stderr, text output, and success flag.
        """
        sandbox = self._ensure_sandbox()
        for attempt in range(self._MAX_RECOVERY_RETRIES + 1):
            try:
                execution = sandbox.run_code(code)
                break
            except Exception as e:
                if attempt < self._MAX_RECOVERY_RETRIES and self._is_sandbox_expired(e):
                    sandbox = self._recover_sandbox()
                    continue
                logger.exception("Code execution failed: %s", e)
                return ExecutionResult(success=False, error=str(e))

        if execution.error:
            return ExecutionResult(
                stdout=list(execution.logs.stdout),
                stderr=list(execution.logs.stderr),
                text=execution.text,
                success=False,
                error=f"{execution.error.name}: {execution.error.value}",
            )

        return ExecutionResult(
            stdout=list(execution.logs.stdout),
            stderr=list(execution.logs.stderr),
            text=execution.text,
            success=True,
        )

    def run_bash(self, command: str, timeout: float = 60) -> BashResult:
        """Run a bash command in the sandbox.

        Auto-recovers if the sandbox has expired (timeout). Creates a new
        sandbox and retries once before reporting failure.

        Args:
            command: Shell command to execute.
            timeout: Maximum seconds to wait (default 60).

        Returns:
            BashResult with stdout, stderr, exit code, and success flag.
        """
        sandbox = self._ensure_sandbox()
        for attempt in range(self._MAX_RECOVERY_RETRIES + 1):
            try:
                result = sandbox.commands.run(command, timeout=timeout)
                break
            except Exception as e:
                if attempt < self._MAX_RECOVERY_RETRIES and self._is_sandbox_expired(e):
                    sandbox = self._recover_sandbox()
                    continue
                logger.exception("Bash command failed: %s", e)
                return BashResult(success=False, error=str(e))

        return BashResult(
            stdout=result.stdout,
            stderr=result.stderr,
            exit_code=result.exit_code,
            success=result.exit_code == 0,
        )

    def __enter__(self) -> SandboxClient:
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop()
