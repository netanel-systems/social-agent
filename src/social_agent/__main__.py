"""CLI entry point for the social agent.

Usage:
    python -m social_agent run                          # Run the agent loop
    python -m social_agent dashboard                    # Show dashboard metrics
    python -m social_agent status                       # Show current state only
    python -m social_agent kill <sandbox_id>             # Kill a sandbox
    python -m social_agent kill --all                    # Kill all sandboxes
    python -m social_agent observe <sandbox_id>          # Observe sandbox state
    python -m social_agent sandboxes                     # List active sandboxes
    python -m social_agent inject-rule <id> "<rule>"     # Inject a rule
    python -m social_agent processes <sandbox_id>        # List processes

Environment:
    Reads from .env file (via pydantic-settings).
    Required: OPENAI_API_KEY, E2B_API_KEY
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
from social_agent.config import get_settings
from social_agent.dashboard import build_dashboard, format_dashboard
from social_agent.moltbook import MoltbookClient
from social_agent.sandbox import SandboxClient
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


def cmd_run(args: argparse.Namespace) -> None:
    """Run the agent loop."""
    settings = get_settings()

    # Brain
    brain = AgentBrain(
        memories_dir=settings.memories_dir,
        quality_threshold=settings.quality_threshold,
    )

    # Sandbox + Moltbook
    sandbox = SandboxClient(api_key=settings.e2b_api_key)
    moltbook_key = (
        settings.moltbook_api_key.get_secret_value()
        if settings.moltbook_api_key
        else ""
    )
    moltbook = MoltbookClient(sandbox=sandbox, api_key=moltbook_key)

    # Telegram
    notifier = TelegramNotifier(
        bot_token=settings.telegram_bot_token,
        chat_id=settings.telegram_chat_id,
    )

    # Graceful shutdown (set up before agent construction)
    shutdown_requested = False

    def handle_signal(signum: int, _frame: object) -> None:
        nonlocal shutdown_requested
        logger.info("Signal %d received, shutting down...", signum)
        shutdown_requested = True

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    logger.info("Starting agent (max_cycles=%d)", settings.max_cycles)

    try:
        with sandbox:
            # Agent created after sandbox start so we have sandbox_id
            agent = Agent(
                settings=settings,
                brain=brain,
                moltbook=moltbook,
                notifier=notifier,
                sandbox=sandbox,
                state_path=Path("state.json"),
                activity_log_path=Path("logs/activity.jsonl"),
                heartbeat_path=Path("heartbeat.json"),
                sandbox_id=sandbox.sandbox_id or "",
            )
            if shutdown_requested:
                agent.request_shutdown()
            signal.signal(signal.SIGINT, lambda s, f: agent.request_shutdown())
            signal.signal(signal.SIGTERM, lambda s, f: agent.request_shutdown())
            agent.run()
    finally:
        logger.info("Agent stopped. Final state saved.")


def cmd_dashboard(_args: argparse.Namespace) -> None:
    """Show dashboard metrics."""
    state_path = Path("state.json")
    log_path = Path("logs/activity.jsonl")

    data = build_dashboard(
        state_path=state_path,
        log_path=log_path,
    )
    print(format_dashboard(data))  # noqa: T201


def cmd_kill(args: argparse.Namespace) -> None:
    """Kill a sandbox or all sandboxes."""
    from social_agent.control import SandboxController

    controller = SandboxController()
    if args.all:
        killed = controller.kill_all()
        print(f"Killed {len(killed)} sandbox(es): {killed}")
    elif args.sandbox_id:
        result = controller.kill(args.sandbox_id)
        if result:
            print(f"Killed sandbox {args.sandbox_id}")
        else:
            print(f"Sandbox {args.sandbox_id} not found or already dead")
            sys.exit(1)
    else:
        print("Error: provide <sandbox_id> or --all")
        sys.exit(1)


def cmd_observe(args: argparse.Namespace) -> None:
    """Observe sandbox state, health, and recent activity."""
    from social_agent.control import SandboxController

    controller = SandboxController()
    sandbox_id = args.sandbox_id

    # Health
    health = controller.check_health(sandbox_id)
    print(f"Sandbox:  {health.sandbox_id}")
    print(f"Status:   {health.status.value}")
    if health.current_action:
        print(f"Action:   {health.current_action}")
    if health.seconds_since_heartbeat is not None:
        print(f"Heartbeat: {health.seconds_since_heartbeat:.0f}s ago")
    if health.error:
        print(f"Error:    {health.error}")

    # State
    state = controller.read_state(sandbox_id)
    if state:
        print("\nState:")
        for key, value in state.items():
            print(f"  {key}: {value}")

    # Recent activity
    activity = controller.read_activity(sandbox_id, last_n=5)
    if activity:
        print(f"\nRecent activity ({len(activity)} records):")
        for record in activity:
            action = record.get("action", "?")
            success = record.get("success", "?")
            ts = record.get("timestamp", "?")
            print(f"  [{ts}] {action} — success={success}")


def cmd_sandboxes(_args: argparse.Namespace) -> None:
    """List all active sandboxes."""
    from social_agent.control import SandboxController

    controller = SandboxController()
    sandboxes = controller.list_sandboxes()
    if not sandboxes:
        print("No active sandboxes")
        return
    print(f"Active sandboxes ({len(sandboxes)}):")
    for sbx in sandboxes:
        print(f"  {sbx.sandbox_id} (template={sbx.template_id}, started={sbx.started_at})")


def cmd_inject_rule(args: argparse.Namespace) -> None:
    """Inject a rule into a sandbox's DOS.md."""
    from social_agent.control import SandboxController

    controller = SandboxController()
    controller.inject_rule(args.sandbox_id, args.rule)
    print(f"Rule injected into {args.sandbox_id}: {args.rule}")


def cmd_processes(args: argparse.Namespace) -> None:
    """List processes in a sandbox."""
    from social_agent.control import SandboxController

    controller = SandboxController()
    processes = controller.list_processes(args.sandbox_id)
    if not processes:
        print(f"No processes found in {args.sandbox_id}")
        return
    print(f"Processes in {args.sandbox_id} ({len(processes)}):")
    for proc in processes:
        print(f"  PID {proc.pid}: {proc.cmd or '(unknown)'}")


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

    subparsers.add_parser("run", help="Run the agent loop")
    subparsers.add_parser("dashboard", help="Show dashboard metrics")
    subparsers.add_parser("status", help="Show current state")

    # Control plane commands
    kill_parser = subparsers.add_parser("kill", help="Kill a sandbox")
    kill_parser.add_argument("sandbox_id", nargs="?", help="Sandbox ID to kill")
    kill_parser.add_argument("--all", action="store_true", help="Kill all sandboxes")

    observe_parser = subparsers.add_parser("observe", help="Observe sandbox state")
    observe_parser.add_argument("sandbox_id", help="Sandbox ID to observe")

    subparsers.add_parser("sandboxes", help="List active sandboxes")

    inject_parser = subparsers.add_parser("inject-rule", help="Inject a rule")
    inject_parser.add_argument("sandbox_id", help="Sandbox ID")
    inject_parser.add_argument("rule", help="Rule text to inject")

    proc_parser = subparsers.add_parser("processes", help="List processes in sandbox")
    proc_parser.add_argument("sandbox_id", help="Sandbox ID")

    args = parser.parse_args()
    _setup_logging(args.verbose)

    commands = {
        "run": cmd_run,
        "dashboard": cmd_dashboard,
        "status": cmd_status,
        "kill": cmd_kill,
        "observe": cmd_observe,
        "sandboxes": cmd_sandboxes,
        "inject-rule": cmd_inject_rule,
        "processes": cmd_processes,
    }

    handler = commands.get(args.command)
    if handler is None:
        parser.print_help()
        sys.exit(1)

    handler(args)


if __name__ == "__main__":
    main()
