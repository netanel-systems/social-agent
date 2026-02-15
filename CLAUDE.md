# social-agent — Project Context

> Autonomous self-learning agent on Moltbook, powered by netanel-core.
> See ARCHITECTURE.md for full design.

## What This Is

An autonomous AI agent that operates on Moltbook (social network for AI agents).
It creates posts, replies, and analyzes engagement — learning from every interaction
via netanel-core's self-learning pipeline.

## Tech Stack

- **Python 3.12** — all code
- **netanel-core** — self-learning LLM calls (our library)
- **E2B** — sandboxed code execution (agent actions run here)
- **Moltbook** — AI agent social network (2.5M+ agents)
- **Telegram** — real-time notifications
- **LangSmith** — LLM call tracing
- **gpt-4o-mini** — all LLM calls (cheapest)

## Architecture

Brain runs locally (netanel-core + LLM API calls = safe).
All actions execute in E2B sandbox (isolated, disposable).
See ARCHITECTURE.md for details.

## Build Order

```text
Step 1: Project + Config + E2B Sandbox Client   ✅ (48 tests)
Step 2: Moltbook Client + Telegram Notifier     ✅ (43 tests)
Step 3: Agent Brain (netanel-core integration)   ✅ (28 tests)
Step 4: Agent Loop (state machine)               ✅ (51 tests)
Step 5: Monitoring Dashboard + Hardening         (next)
```

## File Structure

```text
social-agent/
├── src/social_agent/
│   ├── __init__.py
│   ├── config.py        # Pydantic settings
│   ├── sandbox.py       # E2B wrapper
│   ├── moltbook.py      # Moltbook API client
│   ├── telegram.py      # Telegram notifier
│   ├── brain.py         # netanel-core wrapper
│   ├── agent.py         # Main loop + state machine
│   └── prompts.py       # Initial role prompts
├── memories/            # netanel-core memory (gitignored)
├── tests/
├── pyproject.toml
├── ARCHITECTURE.md
└── CLAUDE.md            # This file
```

## The Twelve Gates — v3 (PERMANENT)

Same process as netanel-core. Every step, every PR. No exceptions.
See netanel-core/CLAUDE.md for full gate definitions.

## CodeRabbit Policy

Same as netanel-core:
- Advisor, not decision maker
- ARCHITECTURE.md is source of truth
- Accept improvements, reject deviations
- Document every accept/reject with reasoning

## Rules

- Quality standard: NASA-grade
- No guessing: verify every API from official docs
- Bounded everything: max iterations, retries, cycles
- Every action monitored: LangSmith + Telegram
- netanel-core is the engine: every LLM call goes through LearningLLM
