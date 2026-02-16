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
Step 5: Monitoring Dashboard + Hardening         ✅ (35 tests)
Step 6: External Control Module (control.py)     ✅ (44 tests)
Step 7: Heartbeat + Stuck Detection              ✅ (7 tests)
Step 8: Dashboard API Server (server.py)         ✅ (23 tests)
Step 9: Public Dashboard Frontend (static/)      ✅ (6 tests)
Step 10: Git Persistence Layer (git_sync.py)     ✅ (28 tests)
Step 11: Cost Tracking (cost.py)                 ✅ (33 tests)
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
│   ├── prompts.py       # Initial role prompts
│   ├── control.py       # External control plane (kill, observe)
│   ├── server.py        # Dashboard API server (REST + static)
│   ├── git_sync.py      # Background git persistence to nathan-brain
│   ├── cost.py          # LLM + E2B cost tracking with budget enforcement
│   └── static/          # Dashboard frontend (HTML/CSS/JS)
│       ├── index.html
│       ├── style.css
│       └── dashboard.js
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
