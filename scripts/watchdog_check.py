"""Watchdog check script for GitHub Actions.

Runs every 15 minutes to ensure the agent is alive and healthy.
This is the ONE external safety net — if the agent crashes, this
resurrects it.

Logic:
    1. List running sandboxes
    2. If none: deploy a fresh sandbox (agent died)
    3. If one: check heartbeat — if stuck > 10 min, kill + redeploy
    4. If multiple: keep newest healthy, kill the rest

Environment variables required:
    E2B_API_KEY: E2B API key
    BRAIN_REPO_URL: nathan-brain repo URL
    GITHUB_TOKEN: GitHub token for cloning brain repo

Exit codes:
    0: Agent is healthy (or successfully recovered)
    1: Recovery failed
    2: Configuration error (missing env vars)
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass, field

from social_agent.control import HealthStatus, SandboxController
from social_agent.lifecycle import LifecycleManager

logger = logging.getLogger("watchdog")

# Watchdog-specific thresholds
_STUCK_THRESHOLD_S = 600  # 10 minutes — kill and redeploy


@dataclass(frozen=True)
class WatchdogResult:
    """Result of a watchdog check cycle."""

    action: str  # "healthy", "deployed", "recovered", "cleaned", "failed"
    sandbox_id: str = ""
    killed: list[str] = field(default_factory=list)
    error: str = ""


@dataclass
class WatchdogConfig:
    """Configuration for watchdog from environment variables."""

    e2b_api_key: str
    brain_repo_url: str
    github_token: str
    stuck_threshold_s: float = _STUCK_THRESHOLD_S

    @classmethod
    def from_env(cls) -> WatchdogConfig:
        """Load config from environment variables.

        Raises:
            SystemExit: If required variables are missing.
        """
        e2b_key = os.environ.get("E2B_API_KEY", "")
        brain_url = os.environ.get("BRAIN_REPO_URL", "")
        gh_token = os.environ.get("GITHUB_TOKEN", "")

        missing = []
        if not e2b_key:
            missing.append("E2B_API_KEY")
        if not brain_url:
            missing.append("BRAIN_REPO_URL")
        if not gh_token:
            missing.append("GITHUB_TOKEN")

        if missing:
            logger.error("Missing required env vars: %s", ", ".join(missing))
            sys.exit(2)

        return cls(
            e2b_api_key=e2b_key,
            brain_repo_url=brain_url,
            github_token=gh_token,
        )


def run_watchdog(config: WatchdogConfig) -> WatchdogResult:
    """Execute a single watchdog check cycle.

    Args:
        config: Watchdog configuration.

    Returns:
        WatchdogResult describing what action was taken.
    """
    controller = SandboxController(e2b_api_key=config.e2b_api_key)
    lifecycle = LifecycleManager(
        controller=controller,
        e2b_api_key=config.e2b_api_key,
    )

    # Step 1: List running sandboxes
    sandboxes = controller.list_sandboxes()
    logger.info("Found %d running sandbox(es)", len(sandboxes))

    if len(sandboxes) == 0:
        return _handle_no_sandboxes(lifecycle, config)

    if len(sandboxes) == 1:
        return _handle_one_sandbox(controller, lifecycle, config, sandboxes[0].sandbox_id)

    # Multiple sandboxes — find the healthiest, kill the rest
    return _handle_multiple_sandboxes(controller, lifecycle, config, sandboxes)


def _handle_no_sandboxes(
    lifecycle: LifecycleManager,
    config: WatchdogConfig,
) -> WatchdogResult:
    """Deploy a fresh sandbox when none are running."""
    logger.warning("No sandboxes running — deploying fresh agent")

    new_id = lifecycle.create_successor()
    if new_id is None:
        return WatchdogResult(action="failed", error="Failed to create sandbox")

    deployed = lifecycle.deploy_self(
        new_id,
        config.brain_repo_url,
        config.github_token,
    )
    if not deployed:
        lifecycle.controller.kill(new_id)
        return WatchdogResult(action="failed", error="Failed to deploy to new sandbox")

    logger.info("Deployed fresh agent to sandbox %s", new_id)
    return WatchdogResult(action="deployed", sandbox_id=new_id)


def _handle_one_sandbox(
    controller: SandboxController,
    lifecycle: LifecycleManager,
    config: WatchdogConfig,
    sandbox_id: str,
) -> WatchdogResult:
    """Check health of a single sandbox, recover if stuck."""
    health = controller.check_health(
        sandbox_id,
        stuck_threshold=config.stuck_threshold_s,
    )

    if health.status == HealthStatus.HEALTHY:
        elapsed = health.seconds_since_heartbeat or 0
        logger.info(
            "Agent is healthy (sandbox=%s, heartbeat=%.0fs ago)",
            sandbox_id, elapsed,
        )
        return WatchdogResult(action="healthy", sandbox_id=sandbox_id)

    if health.status in (HealthStatus.STUCK, HealthStatus.DEAD):
        logger.warning(
            "Agent is %s (sandbox=%s) — killing and redeploying",
            health.status.value, sandbox_id,
        )
        controller.kill(sandbox_id)

        new_id = lifecycle.create_successor()
        if new_id is None:
            return WatchdogResult(
                action="failed",
                killed=[sandbox_id],
                error="Killed stuck sandbox but failed to create replacement",
            )

        deployed = lifecycle.deploy_self(
            new_id,
            config.brain_repo_url,
            config.github_token,
        )
        if not deployed:
            lifecycle.controller.kill(new_id)
            return WatchdogResult(
                action="failed",
                killed=[sandbox_id],
                error="Killed stuck sandbox but failed to deploy replacement",
            )

        logger.info("Recovered: killed %s, deployed %s", sandbox_id, new_id)
        return WatchdogResult(
            action="recovered",
            sandbox_id=new_id,
            killed=[sandbox_id],
        )

    # UNKNOWN status — can't determine health, leave it alone
    logger.warning(
        "Agent health unknown (sandbox=%s, error=%s) — leaving running",
        sandbox_id, health.error,
    )
    return WatchdogResult(action="healthy", sandbox_id=sandbox_id)


def _handle_multiple_sandboxes(
    controller: SandboxController,
    lifecycle: LifecycleManager,
    config: WatchdogConfig,
    sandboxes: list,
) -> WatchdogResult:
    """Keep the healthiest sandbox, kill the rest."""
    logger.warning("Multiple sandboxes running (%d) — cleaning up", len(sandboxes))

    # Check health of each, pick the best
    best_id = ""
    best_elapsed = float("inf")

    for sb in sandboxes:
        health = controller.check_health(sb.sandbox_id)
        if health.status == HealthStatus.HEALTHY:
            elapsed = health.seconds_since_heartbeat or float("inf")
            if elapsed < best_elapsed:
                best_id = sb.sandbox_id
                best_elapsed = elapsed

    # If no healthy sandbox found, pick the first one and hope for the best
    if not best_id:
        best_id = sandboxes[0].sandbox_id
        logger.warning("No healthy sandbox found, keeping %s", best_id)

    # Kill all others
    killed = lifecycle.cleanup_orphans(best_id)
    logger.info("Kept %s, killed %d orphan(s): %s", best_id, len(killed), killed)

    # Now check if the keeper is healthy or needs replacement
    keeper_health = controller.check_health(
        best_id,
        stuck_threshold=config.stuck_threshold_s,
    )
    if keeper_health.status in (HealthStatus.STUCK, HealthStatus.DEAD):
        # The "best" is still sick — kill and redeploy
        controller.kill(best_id)
        killed.append(best_id)

        new_id = lifecycle.create_successor()
        if new_id is None:
            return WatchdogResult(
                action="failed",
                killed=killed,
                error="All sandboxes unhealthy, failed to create replacement",
            )

        deployed = lifecycle.deploy_self(
            new_id,
            config.brain_repo_url,
            config.github_token,
        )
        if not deployed:
            lifecycle.controller.kill(new_id)
            return WatchdogResult(
                action="failed",
                killed=killed,
                error="All sandboxes unhealthy, failed to deploy replacement",
            )

        return WatchdogResult(
            action="recovered",
            sandbox_id=new_id,
            killed=killed,
        )

    return WatchdogResult(
        action="cleaned",
        sandbox_id=best_id,
        killed=killed,
    )


def main() -> None:
    """Entry point for the watchdog script."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    config = WatchdogConfig.from_env()
    result = run_watchdog(config)

    logger.info(
        "Watchdog result: action=%s sandbox=%s killed=%s error=%s",
        result.action, result.sandbox_id, result.killed, result.error,
    )

    if result.action == "failed":
        logger.error("Watchdog FAILED: %s", result.error)
        sys.exit(1)


if __name__ == "__main__":
    main()
