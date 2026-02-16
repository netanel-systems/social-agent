"""Git persistence layer for agent state.

Queues file changes and pushes them to the nathan-brain repo
via background git commands inside the E2B sandbox.

The agent is the ONLY writer to the brain repo, so there are
no merge conflicts. External edits go through the source code
repo (social-agent) and are deployed as code changes.

Usage:
    sync = GitSync(sandbox=sandbox_client, repo_url="...", token="...")
    sync.start()
    sync.queue_sync(["state.json", "logs/activity.jsonl"], "cycle 42")
    sync.stop()  # Flushes remaining queue
"""

from __future__ import annotations

import contextlib
import json
import logging
import queue
import shlex
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from social_agent.sandbox import SandboxClient

logger = logging.getLogger("social_agent.git_sync")

# Queue size limit to prevent memory growth.
_MAX_QUEUE_SIZE = 100
# Maximum retry attempts for a failed push.
_MAX_RETRIES = 3
# Delay between retries (seconds).
_RETRY_DELAY = 2.0


@dataclass(frozen=True)
class SyncEntry:
    """A single sync request to be processed."""

    files: tuple[str, ...]
    message: str


@dataclass(frozen=True)
class SyncResult:
    """Result of a git sync operation, logged to git_tracker.jsonl."""

    timestamp: str
    files: tuple[str, ...]
    commit_hash: str
    status: str  # "success", "failed", "skipped"
    duration_ms: float
    message: str
    error: str = ""
    attempts: int = 1


@dataclass
class GitSync:
    """Background git sync for agent state persistence.

    Runs a worker thread that processes sync requests from a queue.
    Each sync request does: git add <files> && git commit && git push.

    Args:
        sandbox: SandboxClient for running git commands.
        repo_url: GitHub repo URL (e.g. https://github.com/org/nathan-brain).
        token: GitHub token for push authentication.
        tracker_path: Path to git_tracker.jsonl for logging.
        branch: Git branch to push to.
    """

    sandbox: SandboxClient
    repo_url: str
    token: str = field(repr=False)
    tracker_path: Path | None = None
    branch: str = "main"

    # Internal state (not constructor args)
    _queue: queue.Queue[SyncEntry | None] = field(
        default_factory=lambda: queue.Queue(maxsize=_MAX_QUEUE_SIZE),
        init=False,
        repr=False,
    )
    _thread: threading.Thread | None = field(
        default=None,
        init=False,
        repr=False,
    )
    _running: bool = field(
        default=False,
        init=False,
        repr=False,
    )
    _total_syncs: int = field(default=0, init=False, repr=False)
    _total_failures: int = field(default=0, init=False, repr=False)

    @property
    def is_running(self) -> bool:
        """Check if the sync worker is running."""
        return self._running

    @property
    def stats(self) -> dict[str, int]:
        """Return sync statistics."""
        return {
            "total_syncs": self._total_syncs,
            "total_failures": self._total_failures,
            "queue_size": self._queue.qsize(),
        }

    def start(self) -> None:
        """Start the background sync worker."""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._worker,
            daemon=True,
            name="git-sync-worker",
        )
        self._thread.start()
        logger.info("Git sync started (repo=%s, branch=%s)", self.repo_url, self.branch)

    def stop(self, timeout: float = 10.0) -> None:
        """Stop the sync worker, flushing the queue first.

        Sends a sentinel (None) to the queue to signal the worker
        to drain remaining items and exit.
        """
        if not self._running:
            return

        self._running = False
        # Send sentinel to unblock the worker
        with contextlib.suppress(queue.Full):
            self._queue.put_nowait(None)

        if self._thread is not None:
            self._thread.join(timeout=timeout)
            if self._thread.is_alive():
                logger.warning(
                    "Git sync worker did not stop within %.1fs timeout", timeout
                )
            self._thread = None

        logger.info(
            "Git sync stopped (syncs=%d, failures=%d)",
            self._total_syncs,
            self._total_failures,
        )

    def queue_sync(self, files: list[str], message: str) -> bool:
        """Queue a sync request.

        Returns True if queued successfully, False if queue is full.
        Non-blocking — the actual sync happens in the background.
        """
        if not self._running:
            logger.warning("Git sync not running, dropping sync request")
            return False

        entry = SyncEntry(files=tuple(files), message=message)
        try:
            self._queue.put_nowait(entry)
            return True
        except queue.Full:
            logger.warning("Git sync queue full, dropping: %s", message)
            return False

    def init_repo(self) -> bool:
        """Initialize the brain repo inside the sandbox.

        Clones the repo if not already cloned. Sets up git config.
        Should be called once before starting the sync worker.
        """
        # Build authenticated URL
        auth_url = self._authenticated_url()

        # Configure git identity
        config_commands = [
            "git config --global user.email 'nathan@netanel.systems'",
            "git config --global user.name 'Nathan'",
        ]
        for cmd in config_commands:
            result = self.sandbox.run_bash(cmd)
            if result.exit_code != 0:
                logger.error("Git config failed: %s → %s", cmd, result.stderr)
                return False

        # Clone repo — tolerate "already exists", fail on real errors
        clone_result = self.sandbox.run_bash(
            f"git clone {shlex.quote(auth_url)} /home/user/brain"
        )
        if clone_result.exit_code != 0:
            stderr = clone_result.stderr or ""
            if "already exists" in stderr:
                logger.info("Brain repo already cloned, skipping clone")
            else:
                logger.error("Git clone failed: %s", stderr)
                return False

        return True

    # --- Internal ---

    def _authenticated_url(self) -> str:
        """Build authenticated git URL from repo URL and token."""
        # https://github.com/org/repo → https://TOKEN@github.com/org/repo
        if self.repo_url.startswith("https://"):
            return self.repo_url.replace("https://", f"https://{self.token}@", 1)
        return self.repo_url

    def _worker(self) -> None:
        """Background worker that processes sync requests."""
        while self._running or not self._queue.empty():
            try:
                entry = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue

            # Sentinel value signals shutdown
            if entry is None:
                continue

            self._process_entry(entry)

    def _process_entry(self, entry: SyncEntry) -> None:
        """Process a single sync entry with retries."""
        start_time = time.monotonic()
        last_error = ""

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                commit_hash = self._do_sync(entry)
                duration_ms = (time.monotonic() - start_time) * 1000
                status = "skipped" if commit_hash == "skipped" else "success"

                self._total_syncs += 1
                self._log_result(SyncResult(
                    timestamp=self._now_iso(),
                    files=entry.files,
                    commit_hash=commit_hash,
                    status=status,
                    duration_ms=round(duration_ms, 1),
                    message=entry.message,
                    attempts=attempt,
                ))
                return

            except Exception as exc:
                last_error = str(exc)
                logger.warning(
                    "Git sync attempt %d/%d failed: %s",
                    attempt, _MAX_RETRIES, last_error,
                )
                if attempt < _MAX_RETRIES:
                    time.sleep(_RETRY_DELAY)

        # All retries exhausted
        duration_ms = (time.monotonic() - start_time) * 1000
        self._total_failures += 1
        self._log_result(SyncResult(
            timestamp=self._now_iso(),
            files=entry.files,
            commit_hash="",
            status="failed",
            duration_ms=round(duration_ms, 1),
            message=entry.message,
            error=last_error,
            attempts=_MAX_RETRIES,
        ))

    def _do_sync(self, entry: SyncEntry) -> str:
        """Execute git add + commit + push. Returns commit hash."""
        safe_files = " ".join(shlex.quote(f) for f in entry.files)
        safe_message = shlex.quote(entry.message)
        safe_branch = shlex.quote(self.branch)

        # Stage files
        add_result = self.sandbox.run_bash(
            f"cd /home/user/brain && git add {safe_files}"
        )
        if add_result.exit_code != 0:
            msg = f"git add failed: {add_result.stderr}"
            raise RuntimeError(msg)

        # Check if there are changes to commit
        diff_result = self.sandbox.run_bash(
            "cd /home/user/brain && git diff --cached --quiet"
        )
        if diff_result.exit_code == 0:
            # No changes staged — skip
            logger.debug("No changes to commit for: %s", entry.message)
            return "skipped"

        # Commit
        commit_result = self.sandbox.run_bash(
            f"cd /home/user/brain && git commit -m {safe_message}"
        )
        if commit_result.exit_code != 0:
            msg = f"git commit failed: {commit_result.stderr}"
            raise RuntimeError(msg)

        # Extract commit hash
        hash_result = self.sandbox.run_bash(
            "cd /home/user/brain && git rev-parse --short HEAD"
        )
        commit_hash = (hash_result.stdout or "").strip()

        # Push
        push_result = self.sandbox.run_bash(
            f"cd /home/user/brain && git push origin {safe_branch}"
        )
        if push_result.exit_code != 0:
            msg = f"git push failed: {push_result.stderr}"
            raise RuntimeError(msg)

        logger.info("Git sync: %s → %s", entry.message, commit_hash)
        return commit_hash

    def _log_result(self, result: SyncResult) -> None:
        """Append sync result to git_tracker.jsonl."""
        if self.tracker_path is None:
            return

        try:
            from dataclasses import asdict

            self.tracker_path.parent.mkdir(parents=True, exist_ok=True)
            with self.tracker_path.open("a") as f:
                f.write(json.dumps(asdict(result), default=str) + "\n")
        except Exception:
            logger.exception("Failed to log git sync result")

    @staticmethod
    def _now_iso() -> str:
        """Return current UTC time as ISO string."""
        from datetime import UTC, datetime

        return datetime.now(tz=UTC).isoformat()
