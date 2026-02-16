"""Git push helper for nathan-brain state persistence.

Lightweight subprocess-based git push to sync state.json changes
to the nathan-brain repository for dashboard discovery.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_S = 30  # 30 second timeout for git operations


def push_state(brain_path: Path, message: str, timeout: int = _DEFAULT_TIMEOUT_S) -> bool:
    """Push state.json changes to nathan-brain repository.

    Args:
        brain_path: Path to nathan-brain repository
        message: Git commit message
        timeout: Timeout in seconds for git operations

    Returns:
        True if push succeeded, False otherwise
    """
    try:
        # Ensure brain_path exists
        if not brain_path.exists():
            logger.error("nathan-brain path does not exist: %s", brain_path)
            return False

        # Add state.json
        subprocess.run(
            ["git", "-C", str(brain_path), "add", "state.json"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=True,
        )

        # Commit changes
        subprocess.run(
            ["git", "-C", str(brain_path), "commit", "-m", message],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=True,
        )

        # Push to remote
        subprocess.run(
            ["git", "-C", str(brain_path), "push"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=True,
        )

        logger.info("Pushed state to nathan-brain: %s", message)
        return True

    except subprocess.TimeoutExpired:
        logger.error("Git push timed out after %ds", timeout)
        return False
    except subprocess.CalledProcessError as e:
        logger.error("Git push failed: %s", e.stderr if e.stderr else str(e))
        return False
    except Exception as e:
        logger.error("Unexpected error during git push: %s", e)
        return False
