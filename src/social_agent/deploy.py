"""Deploy social-agent to E2B sandbox for autonomous operation.

Uploads the agent source code, netanel-core, dependencies, state,
and memories to an E2B sandbox, then runs the agent with LocalExecutor.

The sandbox IS the isolation layer. Inside it, the agent executes
HTTP calls directly — no nested sandbox needed.

Usage:
    python -m social_agent deploy        # Deploy and run
    python -m social_agent deploy -v     # Deploy with verbose logging

Environment:
    Requires E2B_API_KEY in .env or environment.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# Project paths (relative to social-agent root)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_NETANEL_CORE_ROOT = _PROJECT_ROOT.parent / "netanel-core"
_SRC_DIR = _PROJECT_ROOT / "src" / "social_agent"
_ENV_FILE = _PROJECT_ROOT / ".env"
_STATE_FILE = _PROJECT_ROOT / "state.json"
_MEMORIES_DIR = _PROJECT_ROOT / "memories"
_LOGS_DIR = _PROJECT_ROOT / "logs"

# E2B sandbox configuration
_SANDBOX_TIMEOUT = 3600  # 1 hour active
_SANDBOX_WORKING_DIR = "/home/user/social-agent"

# State file for tracking sandbox ID (for resume)
_SANDBOX_STATE_FILE = _PROJECT_ROOT / ".sandbox_state.json"


def _load_env_vars() -> dict[str, str]:
    """Load environment variables from .env file.

    Returns a dict of env vars needed inside the sandbox.
    Excludes E2B_API_KEY (not needed inside) and adds EXECUTOR_MODE=local.
    """
    env_vars: dict[str, str] = {}

    if _ENV_FILE.exists():
        for line in _ENV_FILE.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()
                # Skip E2B key — not needed inside the sandbox
                if key == "E2B_API_KEY":
                    continue
                env_vars[key] = value

    # Force local executor mode inside the sandbox
    env_vars["EXECUTOR_MODE"] = "local"

    return env_vars


def _get_e2b_api_key() -> str:
    """Get E2B API key from environment or .env file."""
    # Check environment first
    key = os.environ.get("E2B_API_KEY")
    if key:
        return key

    # Fall back to .env file
    if _ENV_FILE.exists():
        for line in _ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line.startswith("E2B_API_KEY="):
                return line.split("=", 1)[1].strip()

    msg = "E2B_API_KEY not found in environment or .env file"
    raise RuntimeError(msg)


def _build_netanel_core_wheel() -> Path:
    """Build netanel-core wheel for upload to sandbox.

    Returns path to the built .whl file.
    """
    if not _NETANEL_CORE_ROOT.exists():
        msg = f"netanel-core not found at {_NETANEL_CORE_ROOT}"
        raise FileNotFoundError(msg)

    logger.info("Building netanel-core wheel...")
    dist_dir = _NETANEL_CORE_ROOT / "dist"

    # Clean previous builds
    if dist_dir.exists():
        for f in dist_dir.glob("*.whl"):
            f.unlink()

    result = subprocess.run(
        [sys.executable, "-m", "build", "--wheel", str(_NETANEL_CORE_ROOT)],
        capture_output=True,
        text=True,
        timeout=120,
    )

    if result.returncode != 0:
        logger.error("Wheel build failed: %s", result.stderr)
        msg = f"Failed to build netanel-core wheel: {result.stderr}"
        raise RuntimeError(msg)

    wheels = list(dist_dir.glob("*.whl"))
    if not wheels:
        msg = "No wheel file produced"
        raise RuntimeError(msg)

    wheel_path = wheels[0]
    logger.info("Built: %s", wheel_path.name)
    return wheel_path


def _collect_source_files() -> list[tuple[str, str]]:
    """Collect all Python source files to upload.

    Returns list of (remote_path, content) tuples.
    """
    files: list[tuple[str, str]] = []

    # social_agent source files
    for py_file in sorted(_SRC_DIR.glob("*.py")):
        remote_path = f"{_SANDBOX_WORKING_DIR}/src/social_agent/{py_file.name}"
        files.append((remote_path, py_file.read_text()))

    # pyproject.toml
    pyproject = _PROJECT_ROOT / "pyproject.toml"
    if pyproject.exists():
        files.append((f"{_SANDBOX_WORKING_DIR}/pyproject.toml", pyproject.read_text()))

    return files


def _collect_memory_files() -> list[tuple[str, str]]:
    """Collect memory files for upload (learned patterns, prompts, state).

    Returns list of (remote_path, content) tuples.
    """
    files: list[tuple[str, str]] = []

    # State file
    if _STATE_FILE.exists():
        files.append((
            f"{_SANDBOX_WORKING_DIR}/state.json",
            _STATE_FILE.read_text(),
        ))

    # Memories directory (recursive)
    if _MEMORIES_DIR.exists():
        for mem_file in sorted(_MEMORIES_DIR.rglob("*")):
            if mem_file.is_file():
                rel = mem_file.relative_to(_MEMORIES_DIR).as_posix()
                remote = f"{_SANDBOX_WORKING_DIR}/memories/{rel}"
                try:
                    files.append((remote, mem_file.read_text()))
                except UnicodeDecodeError:
                    logger.warning("Skipping binary file: %s", mem_file)

    # Activity log
    activity_log = _LOGS_DIR / "activity.jsonl"
    if activity_log.exists():
        files.append((
            f"{_SANDBOX_WORKING_DIR}/logs/activity.jsonl",
            activity_log.read_text(),
        ))

    return files


def _write_env_file_content(env_vars: dict[str, str]) -> str:
    """Generate .env file content from env vars dict."""
    lines = []
    for key, value in sorted(env_vars.items()):
        lines.append(f"{key}={value}")
    return "\n".join(lines) + "\n"


def _save_sandbox_state(sandbox_id: str) -> None:
    """Save sandbox ID for resume capability."""
    state = {
        "sandbox_id": sandbox_id,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "status": "running",
    }
    _SANDBOX_STATE_FILE.write_text(json.dumps(state, indent=2))
    logger.info("Sandbox state saved to %s", _SANDBOX_STATE_FILE)


def _load_sandbox_state() -> dict[str, str] | None:
    """Load saved sandbox state for resume."""
    if not _SANDBOX_STATE_FILE.exists():
        return None
    try:
        return json.loads(_SANDBOX_STATE_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def deploy_and_run(*, verbose: bool = False) -> None:
    """Deploy the agent to E2B and run it autonomously.

    Steps:
    1. Build netanel-core wheel
    2. Create E2B sandbox (or resume existing)
    3. Upload source code, wheel, .env, memories, state
    4. Install dependencies
    5. Run agent with --local flag
    6. Stream output
    """
    from e2b_code_interpreter import Sandbox

    api_key = _get_e2b_api_key()

    # Check for existing sandbox to resume
    saved_state = _load_sandbox_state()
    sandbox = None

    if saved_state:
        sandbox_id = saved_state.get("sandbox_id", "")
        logger.info("Found saved sandbox: %s — attempting to resume...", sandbox_id)
        try:
            sandbox = Sandbox.connect(sandbox_id, api_key=api_key)
            logger.info("Resumed sandbox: %s", sandbox_id)
        except Exception:
            logger.warning("Could not resume sandbox %s — creating new one", sandbox_id)
            sandbox = None

    if sandbox is None:
        # Build wheel first (before creating sandbox to avoid timeout)
        wheel_path = _build_netanel_core_wheel()

        logger.info("Creating E2B sandbox (timeout=%ds)...", _SANDBOX_TIMEOUT)
        sandbox = Sandbox.create(api_key=api_key, timeout=_SANDBOX_TIMEOUT)
        logger.info("Sandbox created: %s", sandbox.sandbox_id)
        _save_sandbox_state(sandbox.sandbox_id)

        # Set up working directory
        sandbox.commands.run(f"mkdir -p {_SANDBOX_WORKING_DIR}/src/social_agent")
        sandbox.commands.run(f"mkdir -p {_SANDBOX_WORKING_DIR}/memories")
        sandbox.commands.run(f"mkdir -p {_SANDBOX_WORKING_DIR}/logs")

        # Upload source files
        logger.info("Uploading source files...")
        source_files = _collect_source_files()
        for remote_path, content in source_files:
            sandbox.files.write(remote_path, content)
        logger.info("Uploaded %d source files", len(source_files))

        # Upload .env
        env_vars = _load_env_vars()
        env_content = _write_env_file_content(env_vars)
        sandbox.files.write(f"{_SANDBOX_WORKING_DIR}/.env", env_content)
        logger.info("Uploaded .env (%d vars)", len(env_vars))

        # Upload memory files (learned patterns, state, logs)
        memory_files = _collect_memory_files()
        if memory_files:
            for remote_path, content in memory_files:
                # Ensure parent directories exist
                parent = "/".join(remote_path.split("/")[:-1])
                sandbox.commands.run(f"mkdir -p {parent}")
                sandbox.files.write(remote_path, content)
            logger.info("Uploaded %d memory/state files", len(memory_files))

        # Upload netanel-core wheel
        logger.info("Uploading netanel-core wheel...")
        wheel_content = wheel_path.read_bytes()
        remote_wheel = f"/tmp/{wheel_path.name}"
        sandbox.files.write(remote_wheel, wheel_content)

        # Install dependencies
        logger.info("Installing dependencies (this may take a minute)...")
        install_result = sandbox.commands.run(
            f"pip install -q {remote_wheel} "
            "httpx duckduckgo-search pydantic-settings python-dotenv "
            "python-telegram-bot e2b-code-interpreter",
            timeout=300,
        )
        if install_result.exit_code != 0:
            logger.error("Dependency install failed: %s", install_result.stderr)
            msg = f"Failed to install dependencies: {install_result.stderr}"
            raise RuntimeError(msg)
        logger.info("Dependencies installed")

        # Install social-agent in editable mode
        sandbox.commands.run(
            f"cd {_SANDBOX_WORKING_DIR} && pip install -q -e .",
            timeout=120,
        )

    # Run the agent
    logger.info("Starting agent in sandbox...")
    verbose_flag = " -v" if verbose else ""
    run_cmd = (
        f"cd {_SANDBOX_WORKING_DIR} && "
        f"python -m social_agent{verbose_flag} run --local"
    )

    logger.info("Command: %s", run_cmd)
    logger.info("=" * 60)
    logger.info("AGENT RUNNING AUTONOMOUSLY IN E2B SANDBOX")
    logger.info("Sandbox ID: %s", sandbox.sandbox_id)
    logger.info("To resume later: sandbox ID saved to .sandbox_state.json")
    logger.info("Press Ctrl+C to disconnect (agent continues running)")
    logger.info("=" * 60)

    try:
        # Run as background process so it survives our disconnect
        result = sandbox.commands.run(
            f"nohup bash -c '{run_cmd}' > /tmp/agent.log 2>&1 &"
            " && echo 'Agent started in background'",
            timeout=10,
        )
        logger.info("Background result: %s", result.stdout.strip())

        # Stream logs (bounded: max 10 minutes, then disconnect)
        max_stream_seconds = 600
        start_time = time.monotonic()
        logger.info(
            "Streaming agent output (Ctrl+C to disconnect, auto-stop after %ds)...",
            max_stream_seconds,
        )
        while time.monotonic() - start_time < max_stream_seconds:
            try:
                log_result = sandbox.commands.run(
                    "tail -n 50 /tmp/agent.log 2>/dev/null || echo 'Waiting for logs...'",
                    timeout=10,
                )
                if log_result.stdout.strip():
                    print(log_result.stdout)
                time.sleep(5)
            except KeyboardInterrupt:
                break
        else:
            logger.info("Stopped log streaming after %ds", max_stream_seconds)

    except KeyboardInterrupt:
        logger.info("\nDisconnected from sandbox. Agent continues running.")
        logger.info("Sandbox ID: %s", sandbox.sandbox_id)
        logger.info("To check status: read .sandbox_state.json")

    logger.info("Deploy complete.")


def download_state(*, api_key: str | None = None) -> None:
    """Download state and memories from running sandbox back to local.

    Call this to sync learned patterns back to your local machine.
    """
    from e2b_code_interpreter import Sandbox

    if api_key is None:
        api_key = _get_e2b_api_key()

    saved_state = _load_sandbox_state()
    if not saved_state:
        logger.error("No saved sandbox state. Run deploy first.")
        return

    sandbox_id = saved_state.get("sandbox_id")
    if not sandbox_id:
        logger.error("Saved sandbox state missing sandbox_id — corrupted state file")
        return
    logger.info("Connecting to sandbox: %s", sandbox_id)

    try:
        sandbox = Sandbox.connect(sandbox_id, api_key=api_key)
    except Exception:
        logger.exception("Could not connect to sandbox %s", sandbox_id)
        return

    # Download state.json
    try:
        content = sandbox.files.read(f"{_SANDBOX_WORKING_DIR}/state.json")
        _STATE_FILE.write_text(content if isinstance(content, str) else content.decode())
        logger.info("Downloaded state.json")
    except Exception:
        logger.warning("Could not download state.json")

    # Download activity log
    try:
        content = sandbox.files.read(f"{_SANDBOX_WORKING_DIR}/logs/activity.jsonl")
        _LOGS_DIR.mkdir(parents=True, exist_ok=True)
        (_LOGS_DIR / "activity.jsonl").write_text(
            content if isinstance(content, str) else content.decode()
        )
        logger.info("Downloaded activity log")
    except Exception:
        logger.warning("Could not download activity log")

    # Download memories (list and download each)
    try:
        ls_result = sandbox.commands.run(
            f"find {_SANDBOX_WORKING_DIR}/memories -type f 2>/dev/null",
            timeout=10,
        )
        if ls_result.stdout.strip():
            for remote_path in ls_result.stdout.strip().splitlines():
                remote_path = remote_path.strip()
                if not remote_path:
                    continue
                rel = remote_path.replace(f"{_SANDBOX_WORKING_DIR}/memories/", "")
                local_path = _MEMORIES_DIR / rel
                local_path.parent.mkdir(parents=True, exist_ok=True)
                try:
                    content = sandbox.files.read(remote_path)
                    local_path.write_text(
                        content if isinstance(content, str) else content.decode()
                    )
                except Exception:
                    logger.warning("Could not download: %s", remote_path)
            logger.info("Downloaded memories")
    except Exception:
        logger.warning("Could not list memory files")

    logger.info("Sync complete.")
