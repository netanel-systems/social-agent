"""Auto-discover active sandbox from nathan-brain repository.

Reads current_sandbox_id from nathan-brain/state.json to enable
dashboard to track agent across self-migrations without manual updates.
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_S = 30  # 30 second timeout for git operations
_PLACEHOLDER_ID = "sbx-not-started"  # Returned when agent hasn't started yet


def get_active_sandbox_id(
    brain_repo_path: Path | str,
    timeout: int = _DEFAULT_TIMEOUT_S,
) -> str:
    """Get current sandbox ID from nathan-brain/state.json.

    Args:
        brain_repo_path: Path to nathan-brain repository
        timeout: Timeout in seconds for git operations

    Returns:
        Active sandbox ID, or "sbx-not-started" if not found
    """
    path = Path(brain_repo_path).expanduser()

    # Pull latest state
    try:
        subprocess.run(
            ["git", "-C", str(path), "pull", "--quiet"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=True,
        )
    except subprocess.TimeoutExpired:
        logger.warning("Git pull timed out, using cached state")
    except subprocess.CalledProcessError as e:
        logger.warning("Git pull failed: %s, using cached state", e.stderr)
    except Exception as e:
        logger.warning("Git pull error: %s, using cached state", e)

    # Read state.json
    state_file = path / "state.json"
    if not state_file.exists():
        logger.info("state.json not found, agent not started yet")
        return _PLACEHOLDER_ID

    try:
        state = json.loads(state_file.read_text())
        sandbox_id = state.get("current_sandbox_id", "")
        if not sandbox_id:
            logger.info("current_sandbox_id field empty, agent not started yet")
            return _PLACEHOLDER_ID
        logger.info("Active sandbox discovered: %s", sandbox_id)
        return sandbox_id
    except (json.JSONDecodeError, OSError) as e:
        logger.error("Failed to read state.json: %s", e)
        return _PLACEHOLDER_ID


def clone_brain_repo(
    repo_url: str,
    target_path: Path | str,
    timeout: int = _DEFAULT_TIMEOUT_S,
) -> bool:
    """Clone nathan-brain repository.

    Args:
        repo_url: GitHub repository URL
        target_path: Where to clone the repo
        timeout: Timeout in seconds for git clone

    Returns:
        True if clone succeeded, False otherwise
    """
    path = Path(target_path).expanduser()

    # Don't clone if already exists
    if path.exists():
        logger.info("nathan-brain already exists at %s", path)
        return True

    try:
        subprocess.run(
            ["git", "clone", repo_url, str(path)],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=True,
        )
        logger.info("Cloned nathan-brain to %s", path)
        return True
    except subprocess.TimeoutExpired:
        logger.error("Git clone timed out after %ds", timeout)
        return False
    except subprocess.CalledProcessError as e:
        logger.error("Git clone failed: %s", e.stderr if e.stderr else str(e))
        return False
    except Exception as e:
        logger.error("Unexpected error during git clone: %s", e)
        return False
