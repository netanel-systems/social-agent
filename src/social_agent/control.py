"""External control plane for sandbox management.

Provides the kill switch, observation, file I/O, rule injection, and metrics.
Runs on OUR machine — the agent does NOT know this exists.

All methods use E2B SDK calls that work without an existing sandbox connection.
See ARCHITECTURE.md Layer 7.1 for design rationale.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from e2b_code_interpreter import Sandbox

logger = logging.getLogger("social_agent.control")

# --- Paths inside the sandbox (nathan-brain working directory) ---
_STATE_PATH = "state.json"
_ACTIVITY_PATH = "logs/activity.jsonl"
_HEARTBEAT_PATH = "heartbeat.json"
_DOS_PATH = "governance/DOS.md"
_OVERRIDES_PATH = "governance/external_overrides.md"


class HealthStatus(StrEnum):
    """Agent health status determined from heartbeat."""

    HEALTHY = "healthy"
    STUCK = "stuck"
    DEAD = "dead"
    UNKNOWN = "unknown"


@dataclass
class HealthCheck:
    """Result of a health check on a sandbox."""

    sandbox_id: str
    status: HealthStatus
    last_heartbeat: str | None = None
    current_action: str | None = None
    seconds_since_heartbeat: float | None = None
    error: str | None = None


@dataclass
class SandboxInfo:
    """Summary of a running sandbox."""

    sandbox_id: str
    template_id: str | None = None
    started_at: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass
class ProcessInfo:
    """A process running inside a sandbox."""

    pid: int
    cmd: str | None = None


class SandboxController:
    """External control plane wrapping E2B SDK.

    All methods are designed to work from outside the sandbox.
    The agent inside the sandbox does not know this class exists.

    Args:
        api_key: E2B API key. If None, uses E2B_API_KEY env var.
    """

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key

    def _api_params(self) -> dict[str, Any]:
        """Build common API params dict."""
        params: dict[str, Any] = {}
        if self._api_key:
            params["api_key"] = self._api_key
        return params

    # --- Kill switch ---

    def kill(self, sandbox_id: str) -> bool:
        """Kill a sandbox. THE kill switch.

        Static E2B API call — works even if the agent is frozen.

        Returns:
            True if the sandbox was killed, False if not found.
        """
        logger.warning("KILL: Killing sandbox %s", sandbox_id)
        result = Sandbox.kill(sandbox_id, **self._api_params())
        if result:
            logger.info("KILL: Sandbox %s killed successfully", sandbox_id)
        else:
            logger.warning("KILL: Sandbox %s not found or already dead", sandbox_id)
        return result

    def kill_all(self) -> list[str]:
        """Emergency: kill ALL running sandboxes.

        Returns:
            List of sandbox IDs that were killed.
        """
        logger.warning("KILL_ALL: Killing all sandboxes")
        killed = []
        for info in self.list_sandboxes():
            if self.kill(info.sandbox_id):
                killed.append(info.sandbox_id)
        logger.info("KILL_ALL: Killed %d sandboxes", len(killed))
        return killed

    # --- Observation ---

    def is_alive(self, sandbox_id: str) -> bool:
        """Check if a sandbox is running.

        Connects to the sandbox and checks its status.

        Returns:
            True if the sandbox is running, False otherwise.
        """
        try:
            sbx = Sandbox.connect(sandbox_id, **self._api_params())
            result = sbx.is_running()
            return result
        except Exception:
            logger.debug("is_alive: Cannot connect to %s", sandbox_id)
            return False

    def list_sandboxes(self) -> list[SandboxInfo]:
        """List all active sandboxes.

        Returns:
            List of SandboxInfo for each running sandbox.
        """
        result = []
        paginator = Sandbox.list(**self._api_params())
        while paginator.has_next:
            for sbx_info in paginator.next_items():
                result.append(
                    SandboxInfo(
                        sandbox_id=sbx_info.sandbox_id,
                        template_id=getattr(sbx_info, "template_id", None),
                        started_at=getattr(sbx_info, "started_at", None),
                        metadata=getattr(sbx_info, "metadata", {}),
                    )
                )
        return result

    # --- File I/O ---

    def read_file(self, sandbox_id: str, path: str) -> str:
        """Read a file from a sandbox.

        Args:
            sandbox_id: Target sandbox.
            path: File path inside the sandbox.

        Returns:
            File contents as string.
        """
        sbx = Sandbox.connect(sandbox_id, **self._api_params())
        return sbx.files.read(path)

    def write_file(self, sandbox_id: str, path: str, content: str) -> None:
        """Write a file to a sandbox.

        Args:
            sandbox_id: Target sandbox.
            path: File path inside the sandbox.
            content: Content to write.
        """
        sbx = Sandbox.connect(sandbox_id, **self._api_params())
        sbx.files.write(path, content)
        logger.info("write_file: Wrote %d bytes to %s in %s", len(content), path, sandbox_id)

    # --- Convenience methods ---

    def read_state(self, sandbox_id: str) -> dict[str, Any]:
        """Read and parse state.json from a sandbox.

        Returns:
            Parsed state as dict. Empty dict on error.
        """
        try:
            content = self.read_file(sandbox_id, _STATE_PATH)
            return json.loads(content)
        except Exception as e:
            logger.warning("read_state: Failed for %s: %s", sandbox_id, e)
            return {}

    def read_activity(
        self, sandbox_id: str, last_n: int = 10, *, max_records: int = 1000
    ) -> list[dict[str, Any]]:
        """Read recent activity records from a sandbox.

        Args:
            sandbox_id: Target sandbox.
            last_n: Number of recent records to return (1-max_records).
            max_records: Upper cap to prevent unbounded reads.

        Returns:
            List of parsed activity records (most recent last).
        """
        if last_n <= 0:
            return []
        last_n = min(last_n, max_records)
        try:
            content = self.read_file(sandbox_id, _ACTIVITY_PATH)
            lines = [line.strip() for line in content.strip().split("\n") if line.strip()]
            records = []
            for line in lines[-last_n:]:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
            return records
        except Exception as e:
            logger.warning("read_activity: Failed for %s: %s", sandbox_id, e)
            return []

    # --- Rule injection ---

    def inject_rule(self, sandbox_id: str, rule: str) -> None:
        """Inject a rule into the agent's DOS.md and log the override.

        The agent will pick this up on its next governance check.

        Args:
            sandbox_id: Target sandbox.
            rule: Rule text to append to DOS.md.
        """
        # Read current DOS.md
        current = self.read_file(sandbox_id, _DOS_PATH)
        # Append the new rule
        updated = current.rstrip() + f"\n- {rule}\n"
        self.write_file(sandbox_id, _DOS_PATH, updated)
        # Log the override
        self.inject_override(sandbox_id, f"Rule injected: {rule}")
        logger.info("inject_rule: Injected rule into %s: %s", sandbox_id, rule)

    def inject_override(self, sandbox_id: str, description: str) -> None:
        """Log an external override to external_overrides.md.

        Args:
            sandbox_id: Target sandbox.
            description: Description of the external change.
        """
        timestamp = datetime.now(UTC).isoformat()
        entry = f"\n| {timestamp} | External Control | {description} |"
        try:
            current = self.read_file(sandbox_id, _OVERRIDES_PATH)
            updated = current.rstrip() + entry + "\n"
        except Exception:
            # File might not exist yet — create with header
            updated = (
                "# External Overrides Log\n\n"
                "| Timestamp | Author | Description |\n"
                "|-----------|--------|-------------|\n"
                + entry
                + "\n"
            )
        self.write_file(sandbox_id, _OVERRIDES_PATH, updated)
        logger.info("inject_override: Logged override in %s", sandbox_id)

    # --- Metrics ---

    def get_metrics(self, sandbox_id: str) -> list[dict[str, Any]]:
        """Get CPU/memory/disk metrics from a sandbox.

        Returns:
            List of metric dicts. Empty list on error.
        """
        try:
            metrics = Sandbox.get_metrics(sandbox_id, **self._api_params())
            return [
                {
                    "cpu": getattr(m, "cpu", None),
                    "memory": getattr(m, "memory", None),
                    "disk": getattr(m, "disk", None),
                }
                for m in metrics
            ]
        except Exception as e:
            logger.warning("get_metrics: Failed for %s: %s", sandbox_id, e)
            return []

    # --- Timeout control ---

    def set_timeout(self, sandbox_id: str, seconds: int) -> None:
        """Set or update sandbox timeout.

        Args:
            sandbox_id: Target sandbox.
            seconds: New timeout in seconds.
        """
        Sandbox.set_timeout(sandbox_id, seconds, **self._api_params())
        logger.info("set_timeout: Set %s timeout to %ds", sandbox_id, seconds)

    # --- Process control ---

    def kill_process(self, sandbox_id: str, pid: int) -> None:
        """Kill a specific process inside a sandbox.

        Args:
            sandbox_id: Target sandbox.
            pid: Process ID to kill.
        """
        sbx = Sandbox.connect(sandbox_id, **self._api_params())
        sbx.commands.kill(pid)
        logger.info("kill_process: Killed PID %d in %s", pid, sandbox_id)

    def list_processes(self, sandbox_id: str) -> list[ProcessInfo]:
        """List all running processes in a sandbox.

        Returns:
            List of ProcessInfo.
        """
        try:
            sbx = Sandbox.connect(sandbox_id, **self._api_params())
            processes = sbx.commands.list()
            return [
                ProcessInfo(
                    pid=p.pid,
                    cmd=getattr(p, "cmd", None),
                )
                for p in processes
            ]
        except Exception as e:
            logger.warning("list_processes: Failed for %s: %s", sandbox_id, e)
            return []

    # --- Command execution ---

    def run_command(
        self,
        sandbox_id: str,
        command: str,
        *,
        timeout: int = 60,
        envs: dict[str, str] | None = None,
    ) -> str:
        """Run a shell command inside a sandbox and return stdout.

        Args:
            sandbox_id: Target sandbox.
            command: Shell command to execute.
            timeout: Maximum seconds to wait (default 60).
            envs: Environment variables to inject into the command.

        Returns:
            Command stdout as string.

        Raises:
            RuntimeError: If the command exits with non-zero status.
        """
        sbx = Sandbox.connect(sandbox_id, **self._api_params())
        result = sbx.commands.run(command, timeout=timeout, envs=envs or {})
        if result.exit_code != 0:
            raise RuntimeError(f"exit {result.exit_code}: {result.stderr}")
        logger.info(
            "run_command: [%s] exit=0 in %s",
            command[:50].replace("\n", " "),
            sandbox_id,
        )
        return result.stdout

    # --- Health check ---

    def check_health(
        self,
        sandbox_id: str,
        *,
        healthy_threshold: float = 60.0,
        stuck_threshold: float = 600.0,
    ) -> HealthCheck:
        """Check agent health by reading heartbeat.json.

        Health states (from ARCHITECTURE.md Layer 7.3):
        - HEALTHY: heartbeat < healthy_threshold seconds old
        - STUCK: heartbeat between healthy_threshold and stuck_threshold
        - DEAD: heartbeat > stuck_threshold OR sandbox not running
        - UNKNOWN: cannot connect to sandbox

        Args:
            sandbox_id: Target sandbox.
            healthy_threshold: Seconds before considering stuck (default 60).
            stuck_threshold: Seconds before considering dead (default 600).

        Returns:
            HealthCheck with status and details.
        """
        try:
            content = self.read_file(sandbox_id, _HEARTBEAT_PATH)
            heartbeat = json.loads(content)
        except Exception as e:
            # Can't read heartbeat — check if sandbox is even alive
            if self.is_alive(sandbox_id):
                return HealthCheck(
                    sandbox_id=sandbox_id,
                    status=HealthStatus.UNKNOWN,
                    error=f"Cannot read heartbeat: {e}",
                )
            return HealthCheck(
                sandbox_id=sandbox_id,
                status=HealthStatus.DEAD,
                error=f"Sandbox not running: {e}",
            )

        timestamp_str = heartbeat.get("timestamp")
        if not timestamp_str:
            return HealthCheck(
                sandbox_id=sandbox_id,
                status=HealthStatus.UNKNOWN,
                error="Heartbeat has no timestamp",
                current_action=heartbeat.get("current_action"),
            )

        try:
            last_beat = datetime.fromisoformat(timestamp_str)
            now = datetime.now(UTC)
            elapsed = (now - last_beat).total_seconds()
        except (ValueError, TypeError) as e:
            return HealthCheck(
                sandbox_id=sandbox_id,
                status=HealthStatus.UNKNOWN,
                error=f"Invalid timestamp: {e}",
            )

        if elapsed < healthy_threshold:
            status = HealthStatus.HEALTHY
        elif elapsed < stuck_threshold:
            status = HealthStatus.STUCK
        else:
            status = HealthStatus.DEAD

        return HealthCheck(
            sandbox_id=sandbox_id,
            status=status,
            last_heartbeat=timestamp_str,
            current_action=heartbeat.get("current_action"),
            seconds_since_heartbeat=elapsed,
        )
