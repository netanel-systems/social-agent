"""CLI entry point for the social agent.

Usage:
    python -m social_agent run          # Run with E2B sandbox (default)
    python -m social_agent run --local  # Run with local executor (inside E2B)
    python -m social_agent deploy       # Deploy to E2B and run autonomously
    python -m social_agent dashboard    # Show dashboard metrics
    python -m social_agent status       # Show current state only

Environment:
    Reads from .env file (via pydantic-settings).
    Required: OPENAI_API_KEY
    Required (sandbox mode): E2B_API_KEY
    Optional: MOLTBOOK_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
from pathlib import Path

from social_agent.agent import Agent
from social_agent.brain import AgentBrain
from social_agent.config import ExecutorMode, get_settings
from social_agent.dashboard import build_dashboard, format_dashboard
from social_agent.moltbook import MoltbookClient
from social_agent.telegram import TelegramNotifier

logger = logging.getLogger("social_agent")


def _setup_logging(verbose: bool = False) -> None:
    """Configure logging for CLI output."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _create_executor(settings: object) -> object:
    """Create the appropriate executor based on settings.

    Returns either a SandboxClient or LocalExecutor, both with
    the same interface (execute_code, run_bash, start, stop).
    """
    from social_agent.config import ExecutorMode as _EM

    mode = getattr(settings, "executor_mode", _EM.SANDBOX)

    if mode == _EM.LOCAL:
        from social_agent.local_executor import LocalExecutor

        logger.info("Using LocalExecutor (direct execution mode)")
        return LocalExecutor()

    from social_agent.sandbox import SandboxClient

    e2b_key = getattr(settings, "e2b_api_key", None)
    if e2b_key is None:
        msg = "E2B API key required for sandbox mode"
        raise ValueError(msg)
    logger.info("Using SandboxClient (E2B sandbox mode)")
    return SandboxClient(api_key=e2b_key)


def cmd_run(args: argparse.Namespace) -> None:
    """Run the agent loop."""
    overrides: dict[str, object] = {}
    if getattr(args, "local", False):
        overrides["executor_mode"] = ExecutorMode.LOCAL

    settings = get_settings(**overrides)

    # Brain
    brain = AgentBrain(
        memories_dir=settings.memories_dir,
        quality_threshold=settings.quality_threshold,
    )

    # Executor (SandboxClient or LocalExecutor)
    executor = _create_executor(settings)
    moltbook_key = (
        settings.moltbook_api_key.get_secret_value()
        if settings.moltbook_api_key
        else ""
    )
    moltbook = MoltbookClient(sandbox=executor, api_key=moltbook_key)

    # Telegram
    notifier = TelegramNotifier(
        bot_token=settings.telegram_bot_token,
        chat_id=settings.telegram_chat_id,
    )

    # Agent
    agent = Agent(
        settings=settings,
        brain=brain,
        moltbook=moltbook,
        notifier=notifier,
        sandbox=executor,
        state_path=Path("state.json"),
        activity_log_path=Path("logs/activity.jsonl"),
    )

    # Graceful shutdown
    def handle_signal(signum: int, _frame: object) -> None:
        logger.info("Signal %d received, shutting down...", signum)
        agent.request_shutdown()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    logger.info(
        "Starting agent (max_cycles=%d, executor=%s)",
        settings.max_cycles,
        settings.executor_mode.value,
    )

    try:
        with executor:
            agent.run()
    finally:
        logger.info("Agent stopped. Final state saved.")


def cmd_deploy(args: argparse.Namespace) -> None:
    """Deploy agent to E2B sandbox and run autonomously."""
    from social_agent.deploy import deploy_and_run

    deploy_and_run(verbose=getattr(args, "verbose", False))


def cmd_dashboard(_args: argparse.Namespace) -> None:
    """Show dashboard metrics."""
    state_path = Path("state.json")
    log_path = Path("logs/activity.jsonl")

    data = build_dashboard(
        state_path=state_path,
        log_path=log_path,
    )
    print(format_dashboard(data))  # noqa: T201


def cmd_status(_args: argparse.Namespace) -> None:
    """Show current agent state."""
    from social_agent.agent import AgentState

    state_path = Path("state.json")
    state = AgentState.load(state_path)

    print(f"Cycle count:           {state.cycle_count}")  # noqa: T201
    print(f"Posts today:           {state.posts_today}")  # noqa: T201
    print(f"Replies today:         {state.replies_today}")  # noqa: T201
    print(f"Consecutive failures:  {state.consecutive_failures}")  # noqa: T201
    print(f"Last reset date:       {state.last_reset_date}")  # noqa: T201


def main() -> None:
    """Parse arguments and dispatch to subcommand."""
    parser = argparse.ArgumentParser(
        prog="social-agent",
        description="Autonomous self-learning agent on Moltbook",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable debug logging"
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # run
    run_parser = subparsers.add_parser("run", help="Run the agent loop")
    run_parser.add_argument(
        "--local",
        action="store_true",
        help="Use local executor (for running inside E2B or isolated env)",
    )

    # deploy
    subparsers.add_parser("deploy", help="Deploy to E2B and run autonomously")

    # dashboard / status
    subparsers.add_parser("dashboard", help="Show dashboard metrics")
    subparsers.add_parser("status", help="Show current state")

    args = parser.parse_args()
    _setup_logging(args.verbose)

    commands = {
        "run": cmd_run,
        "deploy": cmd_deploy,
        "dashboard": cmd_dashboard,
        "status": cmd_status,
    }

    handler = commands.get(args.command)
    if handler is None:
        parser.print_help()
        sys.exit(1)

    handler(args)


if __name__ == "__main__":
    main()
