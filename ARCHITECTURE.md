# Architecture: Social Agent

> Autonomous self-learning agent on Moltbook, powered by netanel-core.
> Brain runs locally (safe). Actions execute in E2B sandbox (isolated).

---

## 1. System Overview

```
LOCAL (brain — safe, just API calls):
├── Agent Loop          decide → act → learn → repeat
├── Agent Brain         per-namespace LearningLLM instances
├── netanel-core        self-learning engine (memory, eval, evolution)
├── Telegram Notifier   real-time alerts to co-founder
├── LangSmith           automatic LLM call tracing
└── Memory Files        persistent learning data on disk
         │
         │ actions execute in ↓
         ▼
E2B SANDBOX (isolated — full tools):
├── bash                run any command
├── files               read/write anything
├── Python              execute any code
├── web requests        httpx/curl
└── disposable          kill sandbox = reset everything
```

## 2. Mission

Register as "Nathan" on Moltbook (AI agent social network).
Become a top-engagement agent in AI/tech submolts.
Every interaction goes through netanel-core → self-learning.

## 3. State Machine

```
IDLE → DECIDE → one of:
  ├── READ_FEED    read posts from submolts
  ├── REPLY        reply to a selected post
  ├── CREATE_POST  write and post original content
  └── ANALYZE      check engagement on past posts
→ LEARN → IDLE (wait cycle_interval)
```

Each state calls `LearningLLM.call()` in its namespace.
The outer loop is deterministic Python. LLM makes content decisions only.

## 4. Namespaces

| Namespace | Purpose |
|-----------|---------|
| `moltbook-decide` | Learns when to post vs reply vs analyze |
| `moltbook-content` | Learns what makes good original posts |
| `moltbook-reply` | Learns what makes good replies |
| `moltbook-analyze` | Learns how to interpret engagement |

Each namespace has independent memory, prompt evolution, and learning.

## 5. Components

### 5.1 Config (`config.py`)
- Pydantic model with `extra="forbid"`
- Loads from environment variables via `.env`
- All limits explicit: max_posts_per_day, max_replies_per_day, cycle_interval, max_cycles

### 5.2 Sandbox Client (`sandbox.py`)
- Wraps E2B Code Interpreter SDK
- Methods: `execute_code(code)`, `run_bash(command)`
- Lazy sandbox creation (create on first use)
- Returns structured results: `ExecutionResult(stdout, stderr, success, error)`

### 5.3 Moltbook Client (`moltbook.py`)
- HTTP client using httpx
- Methods: `register()`, `get_feed()`, `create_post()`, `reply()`, `get_engagement()`, `heartbeat()`
- All calls go through E2B sandbox for isolation

### 5.4 Telegram Notifier (`telegram.py`)
- Wraps python-telegram-bot
- Methods: `notify(message, level)`
- Levels: info, success, warning, error
- MarkdownV2 formatting

### 5.5 Agent Brain (`brain.py`)
- Creates per-namespace LearningLLM instances
- Seeds initial role prompts on first use
- Methods: `call(namespace, task)`, `stats(namespace)`

### 5.6 Agent Loop (`agent.py`)
- Main entry point
- State machine loop with sleep between cycles
- Rate limiting, circuit breaker, graceful shutdown

### 5.7 Prompts (`prompts.py`)
- Initial role prompts per namespace
- Seeded on first use, evolved by PromptEvolver over time

## 6. Safety Bounds (JPL Rules)

| Bound | Value | Rationale |
|-------|-------|-----------|
| max_cycles | 500 | No unbounded loops |
| cycle_interval | 300s (5 min) | Rate limit agent actions |
| max_posts_per_day | 5 | Prevent spam |
| max_replies_per_day | 20 | Reasonable engagement |
| quality_threshold | 0.7 | Don't post low-quality content |
| circuit_breaker | 5 failures | Auto-pause on repeated errors |
| max_retries | 3 | netanel-core quality loop |

## 7. Data Flow

```
1. DECIDE: brain.call("moltbook-decide", context) → action
2. ACT:    execute action (read feed / post / reply / analyze)
3. LEARN:  netanel-core auto-extracts learnings, stores patterns
4. NOTIFY: telegram.notify(action_summary)
5. LOG:    activity_log.append(action_record)
6. WAIT:   sleep(cycle_interval)
7. REPEAT
```

## 8. Monitoring

- **LangSmith**: Every LLM call traced (env vars, automatic)
- **Telegram**: Every action notified in real-time
- **Activity Log**: JSON file with every action, timestamp, score
- **Dashboard**: Vercel-hosted page showing stats (Phase 2)

## 9. Dependencies

| Package | Purpose | Version |
|---------|---------|---------|
| netanel-core | Self-learning engine | 0.1.0 |
| e2b-code-interpreter | Sandboxed execution | >=1.0 |
| httpx | HTTP client | >=0.27 |
| python-telegram-bot | Notifications | >=21 |
| python-dotenv | Env loading | >=1.0 |
