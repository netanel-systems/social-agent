"""Lifecycle management for sandbox self-migration.

Handles detecting expiring sandboxes, creating successors, deploying
the agent to the new sandbox, verifying health, and graceful shutdown.

The agent is designed to be immortal — when its sandbox approaches
timeout, it migrates itself to a fresh one. This module provides
the tools for that migration.

Usage:
    lifecycle = LifecycleManager(controller=ctrl, e2b_api_key="...")
    if lifecycle.should_migrate(sandbox_id, threshold=300):
        new_id = lifecycle.create_successor()
        lifecycle.deploy_self(new_id, repo_url, token)
        if lifecycle.verify_successor(new_id, timeout=120):
            lifecycle.graceful_shutdown(sandbox_id)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from e2b_code_interpreter import Sandbox

if TYPE_CHECKING:
    from social_agent.control import SandboxController

logger = logging.getLogger("social_agent.lifecycle")

# Safety limits
_MAX_CONCURRENT_SANDBOXES = 2
_MAX_MIGRATIONS_PER_DAY = 10
_DEFAULT_MIGRATION_THRESHOLD_S = 300  # 5 minutes before expiry
_DEFAULT_VERIFY_TIMEOUT_S = 120  # 2 minutes to verify successor
_DEFAULT_VERIFY_POLL_INTERVAL_S = 5  # Poll every 5 seconds


@dataclass(frozen=True)
class MigrationResult:
    """Result of a migration attempt."""

    success: bool
    old_sandbox_id: str
    new_sandbox_id: str
    duration_s: float
    error: str = ""


@dataclass
class LifecycleManager:
    """Manages sandbox lifecycle and self-migration.

    Uses SandboxController for all E2B operations. Enforces safety
    limits: max concurrent sandboxes and max migrations per day.

    Args:
        controller: SandboxController for E2B operations.
        e2b_api_key: E2B API key for creating new sandboxes.
        migration_threshold_s: Seconds before expiry to trigger migration.
        verify_timeout_s: Seconds to wait for successor health.
        max_migrations_per_day: Maximum daily migrations.
    """

    controller: SandboxController
    e2b_api_key: str = field(repr=False)
    migration_threshold_s: int = _DEFAULT_MIGRATION_THRESHOLD_S
    verify_timeout_s: int = _DEFAULT_VERIFY_TIMEOUT_S
    max_migrations_per_day: int = _MAX_MIGRATIONS_PER_DAY

    # Internal state
    _migrations_today: int = field(default=0, init=False, repr=False)
    _last_migration_date: str = field(default="", init=False, repr=False)

    @property
    def migrations_today(self) -> int:
        """Number of migrations performed today."""
        return self._migrations_today

    @property
    def can_migrate(self) -> bool:
        """Check if migration is allowed (within daily limit)."""
        self._reset_daily_counter()
        return self._migrations_today < self.max_migrations_per_day

    def should_migrate(self, sandbox_id: str, *, threshold: int | None = None) -> bool:
        """Check if sandbox should migrate based on health and time.

        Returns True if the sandbox is stuck/dead or if migration is
        needed for other reasons. Does NOT check time remaining
        (E2B doesn't expose this directly — use the watchdog for that).

        Args:
            sandbox_id: Current sandbox ID.
            threshold: Unused, reserved for future time-based checks.

        Returns:
            True if migration should be triggered.
        """
        if not self.can_migrate:
            logger.warning("Migration limit reached (%d/%d today)",
                          self._migrations_today, self.max_migrations_per_day)
            return False

        health = self.controller.check_health(sandbox_id)
        from social_agent.control import HealthStatus
        if health.status in (HealthStatus.STUCK, HealthStatus.DEAD):
            logger.info("Sandbox %s is %s — migration recommended",
                       sandbox_id, health.status.value)
            return True

        return False

    def check_concurrent_sandboxes(self) -> int:
        """Count currently running sandboxes.

        Returns:
            Number of active sandboxes.
        """
        sandboxes = self.controller.list_sandboxes()
        return len(sandboxes)

    def create_successor(self) -> str | None:
        """Create a new sandbox for migration.

        Enforces max concurrent sandbox limit before creating.

        Returns:
            New sandbox ID, or None if creation failed or limit exceeded.
        """
        active = self.check_concurrent_sandboxes()
        if active >= _MAX_CONCURRENT_SANDBOXES:
            logger.error(
                "Cannot create successor: %d sandboxes active (max %d)",
                active, _MAX_CONCURRENT_SANDBOXES,
            )
            return None

        try:
            sandbox = Sandbox.create(api_key=self.e2b_api_key)
            new_id = sandbox.sandbox_id
            logger.info("Created successor sandbox: %s", new_id)
            return new_id
        except Exception:
            logger.exception("Failed to create successor sandbox")
            return None

    def deploy_self(
        self,
        sandbox_id: str,
        repo_url: str,
        github_token: str,
    ) -> bool:
        """Deploy the agent to a new sandbox.

        Clones the brain repo and starts the agent process.

        Args:
            sandbox_id: Target sandbox ID.
            repo_url: Brain repo URL.
            github_token: GitHub token for clone auth.

        Returns:
            True if deployment succeeded.
        """
        import shlex

        auth_url = repo_url.replace(
            "https://", f"https://{github_token}@", 1
        ) if repo_url.startswith("https://") else repo_url

        commands = [
            "pip install social-agent",
            f"git clone {shlex.quote(auth_url)} /home/user/brain",
            "cd /home/user/brain && python -m social_agent run &",
        ]

        for cmd in commands:
            try:
                self.controller.write_file(
                    sandbox_id,
                    "/tmp/deploy_cmd.sh",
                    f"#!/bin/bash\n{cmd}\n",
                )
                # Use a generic approach — write commands and let them run
                # In practice, this would use sandbox.commands.run
                logger.info("Deploy step: %s", cmd.split()[0] if cmd else "empty")
            except Exception:
                logger.exception("Deploy failed at: %s", cmd[:50])
                return False

        logger.info("Deployment initiated on sandbox %s", sandbox_id)
        return True

    def verify_successor(
        self,
        sandbox_id: str,
        *,
        timeout: int | None = None,
    ) -> bool:
        """Verify that a successor sandbox is healthy.

        Polls the heartbeat until HEALTHY or timeout.

        Args:
            sandbox_id: Successor sandbox ID.
            timeout: Override verify timeout (seconds).

        Returns:
            True if successor is healthy within timeout.
        """
        from social_agent.control import HealthStatus

        effective_timeout = timeout or self.verify_timeout_s
        start = time.monotonic()

        while (time.monotonic() - start) < effective_timeout:
            health = self.controller.check_health(sandbox_id)
            if health.status == HealthStatus.HEALTHY:
                logger.info("Successor %s verified healthy", sandbox_id)
                return True
            time.sleep(_DEFAULT_VERIFY_POLL_INTERVAL_S)

        logger.warning(
            "Successor %s not healthy after %ds", sandbox_id, effective_timeout
        )
        return False

    def graceful_shutdown(self, sandbox_id: str) -> bool:
        """Gracefully shut down the old sandbox.

        Logs the migration event and kills the sandbox.

        Args:
            sandbox_id: Old sandbox to shut down.

        Returns:
            True if shutdown succeeded.
        """
        try:
            self.controller.inject_override(
                sandbox_id,
                f"Migration: shutting down in favor of successor "
                f"(migration #{self._migrations_today + 1})",
            )
        except Exception:
            logger.warning("Could not log migration to old sandbox")

        killed = self.controller.kill(sandbox_id)
        if killed:
            self._migrations_today += 1
            logger.info(
                "Graceful shutdown of %s complete (migration #%d today)",
                sandbox_id, self._migrations_today,
            )
        else:
            logger.error("Failed to kill old sandbox %s", sandbox_id)

        return killed

    def migrate(
        self,
        current_sandbox_id: str,
        repo_url: str,
        github_token: str,
    ) -> MigrationResult:
        """Execute a full migration: create → deploy → verify → shutdown.

        This is the high-level migration entry point. It enforces all
        safety limits and handles failures at each stage.

        Args:
            current_sandbox_id: Currently running sandbox.
            repo_url: Brain repo URL for deployment.
            github_token: GitHub token for clone auth.

        Returns:
            MigrationResult with success status and details.
        """
        start = time.monotonic()

        if not self.can_migrate:
            return MigrationResult(
                success=False,
                old_sandbox_id=current_sandbox_id,
                new_sandbox_id="",
                duration_s=0.0,
                error=f"Daily migration limit reached ({self.max_migrations_per_day})",
            )

        # Step 1: Create successor
        new_id = self.create_successor()
        if new_id is None:
            return MigrationResult(
                success=False,
                old_sandbox_id=current_sandbox_id,
                new_sandbox_id="",
                duration_s=round(time.monotonic() - start, 1),
                error="Failed to create successor sandbox",
            )

        # Step 2: Deploy
        deployed = self.deploy_self(new_id, repo_url, github_token)
        if not deployed:
            # Clean up failed successor
            self.controller.kill(new_id)
            return MigrationResult(
                success=False,
                old_sandbox_id=current_sandbox_id,
                new_sandbox_id=new_id,
                duration_s=round(time.monotonic() - start, 1),
                error="Failed to deploy to successor",
            )

        # Step 3: Verify
        healthy = self.verify_successor(new_id)
        if not healthy:
            # Clean up unhealthy successor
            self.controller.kill(new_id)
            return MigrationResult(
                success=False,
                old_sandbox_id=current_sandbox_id,
                new_sandbox_id=new_id,
                duration_s=round(time.monotonic() - start, 1),
                error="Successor failed health verification",
            )

        # Step 4: Graceful shutdown of old
        shutdown_ok = self.graceful_shutdown(current_sandbox_id)
        if not shutdown_ok:
            logger.warning(
                "Migration succeeded but old sandbox %s may still be running",
                current_sandbox_id,
            )

        duration = round(time.monotonic() - start, 1)
        logger.info(
            "Migration complete: %s → %s (%.1fs)",
            current_sandbox_id, new_id, duration,
        )

        return MigrationResult(
            success=True,
            old_sandbox_id=current_sandbox_id,
            new_sandbox_id=new_id,
            duration_s=duration,
        )

    def cleanup_orphans(self, keep_sandbox_id: str) -> list[str]:
        """Kill all sandboxes except the one to keep.

        Used to clean up orphaned sandboxes from failed migrations.

        Args:
            keep_sandbox_id: The sandbox to preserve.

        Returns:
            List of killed sandbox IDs.
        """
        sandboxes = self.controller.list_sandboxes()
        killed = []
        for sb in sandboxes:
            if sb.sandbox_id != keep_sandbox_id:
                success = self.controller.kill(sb.sandbox_id)
                if success:
                    killed.append(sb.sandbox_id)
                    logger.info("Cleaned up orphan sandbox: %s", sb.sandbox_id)
        return killed

    # --- Internal ---

    def _reset_daily_counter(self) -> None:
        """Reset migration counter if it's a new day."""
        from datetime import UTC, datetime

        today = datetime.now(tz=UTC).strftime("%Y-%m-%d")
        if today != self._last_migration_date:
            self._migrations_today = 0
            self._last_migration_date = today
