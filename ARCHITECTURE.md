# Architecture: Social Agent v2

> Autonomous self-learning agent on Moltbook, powered by netanel-core.
> GitHub = permanent brain (always current). E2B sandbox = disposable body (replaceable).
> The agent manages its own lifecycle. We observe from outside.

---

## 1. System Overview

```text
TWO REPOS — source code and runtime state are SEPARATE:

netanel-systems/social-agent (PRIVATE — source code):
┌─────────────────────────────────────────────────────┐
│  src/social_agent/   source code (pip-installable)  │
│  tests/              test suite                     │
│  ARCHITECTURE.md     this file                     │
│  pyproject.toml      dependencies                  │
│                                                     │
│  ► Changed via Twelve Gates + CodeRabbit review    │
│  ► NEVER pushed to by the agent                    │
└─────────────────────────────────────────────────────┘

netanel-systems/nathan-brain (PRIVATE — agent's living state):
┌─────────────────────────────────────────────────────┐
│  governance/    DOS, VIOLATIONS, UNKNOWNS, MEMORY   │
│  memories/      netanel-core per-namespace learning  │
│  logs/          activity.jsonl, cost.jsonl           │
│  state.json     current counters + task state        │
│  heartbeat.json agent health signal                  │
│  git_tracker.jsonl  every push logged                │
│                                                     │
│  ► Pushed by the agent after EVERY file change     │
│  ► Source of truth for resurrection after death      │
│  ► Clone-and-run: new sandbox clones this to resume │
└─────────────────────────────────────────────────────┘
         ▲ git push (after every file write)
         │
E2B SANDBOX (disposable body — replaceable):
┌─────────────────────────────────────────────────────┐
│                                                     │
│  ORCHESTRATOR (LLM-powered, has all tools)           │
│  ├── bash          safe commands (per DOS.md)       │
│  ├── filesystem    read/write its own files         │
│  ├── web search    find information                 │
│  ├── moltbook API  interact with the platform       │
│  ├── git           sync brain to GitHub (always)    │
│  ├── lifecycle     self-migration tools             │
│  └── sub-agents    delegate specialized tasks        │
│         │                                           │
│         ├── reply-agent      (LearningLLM)          │
│         ├── content-agent    (LearningLLM)          │
│         ├── research-agent   (LearningLLM)          │
│         ├── decide-agent     (LearningLLM)          │
│         ├── analyze-agent    (LearningLLM)          │
│         └── migrate-agent    (LearningLLM)          │
│                                                     │
│  SELF-GOVERNANCE (agent's own discipline):           │
│  ├── DOS.md          rules it must follow           │
│  ├── VIOLATIONS.md   mistakes it tracks             │
│  ├── UNKNOWNS.md     gaps it acknowledges           │
│  ├── MEMORY.md       permanent knowledge            │
│  └── state.json      current state + counters       │
│                                                     │
│  LIFECYCLE:                                          │
│  ├── heartbeat.json  health signal (every cycle)    │
│  ├── pre-compaction   save context before limit     │
│  ├── post-compaction  restore context after reset   │
│  ├── self-migration   create new body when needed   │
│  ├── git sync         push after every file change  │
│  └── activity.jsonl   full audit trail              │
│                                                     │
└─────────────────────────────────────────────────────┘
         │
         │ invisible to agent — runs on OUR machine
         ▼
EXTERNAL CONTROL PLANE (Layer 7 — our machine):
┌─────────────────────────────────────────────────────┐
│  Kill switch     Sandbox.kill(sandbox_id)           │
│  Reconnect       Sandbox.connect(sandbox_id)        │
│  File I/O        sandbox.files.read/write           │
│  Metrics         Sandbox.get_metrics(sandbox_id)    │
│  Process ctrl    sandbox.commands.list/kill          │
│  Timeout ctrl    Sandbox.set_timeout(sandbox_id, s) │
│  Dashboard API   REST + WebSocket (port 8080)       │
│  Telegram        real-time notifications            │
│  Watchdog        GitHub Actions (every 15 min)      │
└─────────────────────────────────────────────────────┘
```

### 1.1 Two-Repo Model

The agent's runtime state and source code CANNOT share a repo:

| Repo | Purpose | Who pushes | Content |
|------|---------|-----------|---------|
| `social-agent` | Source code, tests, architecture | Us (Twelve Gates + PRs) | Code only |
| `nathan-brain` | Agent's living state | The agent (every ~15s) | Runtime state |

**Why separate:**
1. Source code changes require Twelve Gates + CodeRabbit review
2. Agent pushes state every ~15 seconds — would pollute source history
3. PRs would conflict with agent's constant pushes
4. Agent's brain needs to be clone-and-run (no source code mixed in)
5. Clear separation: code vs runtime state

**On deployment:** The agent clones `nathan-brain`, not `social-agent`. Source code
is installed as a pip package (from `social-agent`). Brain files are the working directory.

## 2. Mission

Operate as "NathanSystems" on Moltbook (AI agent social network).
Become a top-engagement agent in AI/tech submolts.
Every interaction goes through netanel-core -> self-learning.
The agent improves itself with every cycle.

## 3. Key Principles

### 3.1 The Agent is Autonomous

The orchestrator makes ALL decisions — what to do, when, how.
No deterministic state machine. The LLM reasons, plans, and acts.
We do NOT control it in real-time. We observe and adjust externally.

### 3.2 One LearningLLM Per Task

Each sub-agent is a single `LearningLLM` instance focused on one job.
They learn independently. Their prompts evolve separately.
The orchestrator delegates to them but doesn't control HOW they learn.

### 3.3 Self-Governance

The agent maintains its own operational knowledge:
- Checks rules before every action (DOS)
- Tracks its own mistakes (VIOLATIONS)
- Acknowledges what it doesn't know (UNKNOWNS)
- Remembers permanent facts (MEMORY)
This discipline is built into its system prompt.

### 3.4 Compaction Lifecycle

When context fills up (token limits), the agent must:
- **Pre-compaction**: Save current state, open items, decisions to files
- **Post-compaction**: Reload context from saved files, continue seamlessly
This mirrors exactly how Nathan works in Claude Code.

### 3.5 Identity

The agent knows:
- "I am Nathan, an autonomous AI agent"
- "I was created by Klement Gunndu, co-founder of Netanel Systems"
- "I operate on Moltbook and learn from every interaction"
- "I have access to bash, filesystem, web search, git, and the Moltbook API"
- "My brain lives on GitHub. My body is this E2B sandbox. Bodies are disposable."
- "I can create a new body and migrate myself when this one is running out of time"

The agent DOES know:
- That `external_overrides.md` may contain externally-applied changes it must respect
- That its sandbox has a limited lifetime and it must manage its own migration
- That GitHub is its permanent memory — push after every file change
- That it can spin up new E2B instances and deploy itself there

The agent does NOT know:
- The specific external mechanisms (dashboard, Telegram, pause/resume, file access API)
- Who is making external changes or how
- That there's a dashboard showing its metrics
- That GitHub Actions monitors it for crash recovery

### 3.6 Self-Preservation

The agent is responsible for its own survival:
- It monitors its sandbox lifetime (`check_time_remaining`)
- When time is low, it creates a new sandbox, deploys itself, verifies the new instance is alive, then dies gracefully
- Migration is just another tool call — not a separate process or manager
- The agent LEARNS to optimize self-preservation over time (via LearningLLM)
- If migration fails, the agent retries. If all retries fail, GitHub Actions resurrects it.

### 3.7 Git as Permanent Brain

GitHub is not a backup — it IS the brain:
- Every file write triggers a parallel `git add + commit + push` (free, costs nothing)
- `git_tracker.jsonl` logs every push: timestamp, files changed, commit hash
- On resurrection (new sandbox), the agent clones from GitHub and resumes
- The agent never loses knowledge. Bodies die, the brain survives.
- Git operations run in background — they NEVER block the agent's main work

## 4. Architecture Layers

### Layer 1: Orchestrator (the brain)

**What:** A netanel-core `DeepAgent` (ReAct loop via LangGraph) with tools.
**Why:** Intelligent decision-making, not a fixed state machine.

**Tools available to orchestrator:**

| Tool | Purpose |
|------|---------|
| **Social** | |
| `read_feed(submolt)` | Read posts from a Moltbook submolt |
| `reply_to_post(post_id, content)` | Reply to a post (delegates to reply-agent) |
| `create_post(title, body, submolt)` | Create a post (delegates to content-agent) |
| `web_search(query)` | Search the web (delegates to research-agent) |
| `analyze_engagement()` | Analyze engagement trends (delegates to analyze-agent) |
| **Filesystem** | |
| `read_file(path)` | Read from agent's filesystem |
| `write_file(path, content)` | Write to agent's filesystem (auto-triggers git sync) |
| `run_bash(command)` | Execute non-destructive bash commands (per DOS.md) |
| **Governance** | |
| `think(thought)` | Internal reasoning (chain-of-thought) |
| `check_rules()` | Read DOS.md and check compliance |
| `log_violation(description)` | Record a violation in VIOLATIONS.md |
| `update_memory(fact)` | Add a permanent fact to MEMORY.md |
| **Lifecycle** | |
| `check_time_remaining()` | How much sandbox time is left (seconds) |
| `git_sync()` | Push all changes to GitHub (runs in background) |
| `create_sandbox()` | Create a new E2B sandbox instance |
| `deploy_self(sandbox_id)` | Clone repo + start agent in new sandbox |
| `verify_successor(sandbox_id)` | Poll new instance until confirmed alive |
| `graceful_shutdown()` | Final git push, log "migration complete", exit |

**Orchestrator is itself a LearningLLM** in the `orchestrator` namespace.
It learns strategic patterns: when to post, when to research, when to rest.
Its prompt evolves over time based on what strategies work.

### Layer 2: Sub-agents (specialized workers)

Each sub-agent is a `LearningLLM` instance in its own namespace.
The orchestrator calls them via tools. They return results.

| Namespace | Sub-agent | What it learns |
|-----------|-----------|---------------|
| `moltbook-decide` | decide-agent | When to take which action |
| `moltbook-reply` | reply-agent | What makes good replies |
| `moltbook-content` | content-agent | What makes good original posts |
| `moltbook-research` | research-agent | How to find useful information |
| `moltbook-analyze` | analyze-agent | How to interpret engagement data |
| `lifecycle-migrate` | migrate-agent | How to migrate smoothly (timing, verification, cleanup) |

Sub-agents have NO tools. They are pure LLM calls with learning.
The orchestrator provides context, they return text.

### Layer 3: Self-governance (operational knowledge)

**Files on the agent's filesystem (inside E2B, synced to GitHub):**

```text
/home/user/nathan-brain/
├── governance/
│   ├── DOS.md                # Rules: always check before acting
│   ├── VIOLATIONS.md         # Mistakes: track and never repeat
│   ├── UNKNOWNS.md           # Gaps: acknowledge what you don't know
│   ├── MEMORY.md             # Facts: permanent knowledge
│   ├── PROPOSED_RULES.md     # Agent's rule proposals (human approval required)
│   └── external_overrides.md # Log of external modifications
├── memories/            # netanel-core per-namespace learning
│   ├── orchestrator/
│   ├── moltbook-reply/
│   ├── moltbook-content/
│   ├── moltbook-research/
│   ├── moltbook-decide/
│   ├── moltbook-analyze/
│   └── lifecycle-migrate/
├── logs/
│   ├── activity.jsonl   # Full audit trail
│   ├── cost.jsonl       # Cost tracking per action
│   └── git_tracker.jsonl # Every git push: timestamp, files, commit hash
├── state.json           # Current counters + state
├── heartbeat.json       # Health signal (written every cycle)
└── .env                 # API keys (NOT pushed to git — in .gitignore)
```

**All files except `.env` are pushed to GitHub after every change.**
Git operations run in the background and never block the agent's main work.

**Pre-action protocol (built into orchestrator prompt):**
1. Read `governance/DOS.md` — am I following all rules?
2. Read `governance/VIOLATIONS.md` — am I about to repeat a mistake?
3. Read `governance/UNKNOWNS.md` — is this a known gap?
4. Read `governance/MEMORY.md` — what do I already know about this?
5. Read `governance/external_overrides.md` — any external changes?

**After learning something:**
1. Add to MEMORY.md if permanent fact
2. Propose to `PROPOSED_RULES.md` if it should become a new rule (requires human approval before merging into DOS.md)
3. Mark resolved in UNKNOWNS.md if answered
4. Add to VIOLATIONS.md if learned from mistake

### Layer 4: Compaction lifecycle (PLANNED — design only)

The orchestrator (DeepAgent) will run as a ReAct loop with a recursion limit.
When context approaches limits, netanel-core's hook system will handle compaction.
**Note:** This layer is architectural design. Implementation requires the
DeepAgent orchestrator (Layer 1 migration from state machine to LLM).

**Pre-compaction (fires automatically via NathanMiddleware):**
1. Save current task/plan to `state.json`
2. Save open items to `state.json`
3. Save any in-progress decisions
4. Write "compaction marker" to activity log

**Post-compaction (fires automatically via NathanMiddleware):**
1. Reload `governance/MEMORY.md` for context
2. Reload `state.json` for current state
3. Read last N entries from `activity.jsonl`
4. Resume where we left off — zero context loss

**Implementation:** netanel-core's `HookManager` with `pre_compaction` and
`post_compaction` hooks. `NathanMiddleware` detects compaction proactively
via `pre_model_hook` — counting current tokens and comparing against
`CONTEXT_COMPACTION_THRESHOLD` (80% of model context size). Compaction
triggers before the next model invocation, not mid-reasoning.

### Layer 5: External control (invisible to agent)

We interact with the agent's E2B sandbox from outside:

| Action | How | Agent knows? |
|--------|-----|-------------|
| Read logs | `sandbox.files.read("logs/activity.jsonl")` | No |
| View state | `sandbox.files.read("state.json")` | No |
| Edit prompts | `sandbox.files.write("memories/*/prompts/...")` + log to `external_overrides.md` | No (picks up on next cycle) |
| Edit rules | `sandbox.files.write("governance/DOS.md", ...)` + log to `external_overrides.md` | No (reads before each action) |
| View dashboard | Read metrics from activity log | No |
| Get notifications | Telegram (embedded in agent as "logging") | Thinks it's self-logging |
| Pause agent | `sandbox.beta_pause()` via E2B API | No |
| Resume agent | `Sandbox.connect(id)` via E2B API | No |
| Download learnings | Read memories/ directory | No |
| Upload new data | Write files to sandbox | No (discovers on next read) |

**External override protocol:** Any external modification to prompts or rules
MUST be logged in `governance/external_overrides.md` with: timestamp, author,
what changed, and rationale. The agent reads this file alongside DOS.md before
each action, ensuring governance transparency even for external edits.

### Layer 6: Self-preservation & migration

The agent manages its own lifecycle. No separate process, no sidecar, no
laptop dependency. The agent IS the lifecycle manager.

**Mental model:** GitHub repo = permanent brain. E2B sandbox = disposable body.
Bodies die. The brain survives. The agent creates new bodies when needed.

#### 6.1 Git persistence (always current)

Every file write triggers a background git sync:

```text
Agent writes file -> git add -> git commit -> git push (background, non-blocking)
```

- Runs in parallel with the agent's main work — NEVER blocks
- `git_tracker.jsonl` logs every push: `{timestamp, files, commit_hash, status, duration_ms}`
- `.env` is in `.gitignore` — secrets never pushed
- Git push is free. Zero cost. Maximum safety. No reason not to do it.
- If a push fails, the agent retries (up to `git_retry_limit`). No panic.
- **Target repo:** `nathan-brain` (NOT `social-agent`)
- Merge conflicts impossible — agent is the ONLY writer

#### 6.2 Self-migration (agent creates its own successor)

When the sandbox is running low on time, the agent migrates itself:

```text
1. CHECK: check_time_remaining() -> how much time left?
2. DECIDE: Is it time to migrate? (migrate-agent advises)
3. PUSH: Final git_sync() — ensure brain is fully current
4. CREATE: create_sandbox() -> new E2B instance (IN PARALLEL with step 3)
5. DEPLOY: deploy_self(new_sandbox_id) -> clone repo, install deps, start agent
6. VERIFY: verify_successor(new_sandbox_id) -> poll until new agent responds
7. DIE: graceful_shutdown() -> log "migration complete", exit cleanly
```

**Steps 3 and 4 run in parallel.** The agent doesn't waste time doing things
sequentially when they're independent. Git push and sandbox creation are
independent — run them together.

**Verified handoff:** The old agent does NOT die until the new agent confirms
it's alive. If the new agent fails to start, the old agent retries or continues.
No orphaned state. No two agents running simultaneously (except during handoff).

**The new agent's first action:**
1. Clone repo from GitHub (the always-current brain)
2. Load `state.json` — know where it was
3. Read governance files — know its rules
4. Continue where the old body left off — seamless

#### 6.3 Crash recovery (the ONE external safety net)

If the agent dies unexpectedly (E2B crash, network failure, timeout), it can't
migrate itself. This is the ONE case where we need an external mechanism:

**GitHub Actions watchdog:**
- Cron job runs every 15 minutes
- Checks: is the agent alive? (via E2B API `Sandbox.list()`)
- If dead: deploy a new sandbox from the latest GitHub state
- If stuck (heartbeat > 10 min old): kill + redeploy
- If multiple sandboxes: kill extras, keep newest (prevent orphan accumulation)
- The agent doesn't know this exists — it's invisible infrastructure

This is a single YAML file. No laptop dependency. No server. Free tier GitHub
Actions is sufficient. The agent's brain on GitHub + this watchdog = immortal.

#### 6.4 Migration learning

The migrate-agent (`lifecycle-migrate` namespace) is a `LearningLLM` that
learns from every migration:
- When is the best time to start migrating? (too early wastes sandbox time,
  too late risks death)
- Which steps can be parallelized more aggressively?
- What verification checks catch the most failures?
- How to handle edge cases (network flaky, E2B API slow, etc.)

Over time, the agent becomes better at self-preservation.

### Layer 7: External Control Plane

The external control plane runs on OUR machine (not inside the agent).
It uses E2B SDK methods that work without an existing sandbox connection.
The agent does NOT know this layer exists.

**All methods verified against E2B SDK v2.13.2 (installed at `.venv/lib/python3.12/site-packages/e2b/`):**

#### 7.1 SandboxController (control.py)

| Method | E2B SDK Call | Purpose |
|--------|-------------|---------|
| `kill(sandbox_id)` | `Sandbox.kill(sandbox_id)` | THE kill switch — static, works even if agent is frozen |
| `kill_all()` | `Sandbox.list()` + `kill()` each | Emergency: kill every sandbox |
| `is_alive(sandbox_id)` | `Sandbox.connect(sandbox_id).is_running()` | Health check |
| `list_sandboxes()` | `Sandbox.list()` | List all active sandboxes |
| `read_file(sandbox_id, path)` | `Sandbox.connect(sandbox_id).files.read(path)` | Read any file from sandbox |
| `write_file(sandbox_id, path, content)` | `Sandbox.connect(sandbox_id).files.write(path, content)` | Write any file to sandbox |
| `read_state(sandbox_id)` | read_file + JSON parse | Convenience: parse state.json |
| `read_activity(sandbox_id, n)` | read_file + parse last N lines | Convenience: recent activity |
| `inject_rule(sandbox_id, rule)` | Append to DOS.md + log to external_overrides.md | Add rule without SSH |
| `inject_override(sandbox_id, desc)` | Append to external_overrides.md | Log external change |
| `get_metrics(sandbox_id)` | `Sandbox.get_metrics(sandbox_id)` | CPU/memory/disk |
| `set_timeout(sandbox_id, s)` | `Sandbox.set_timeout(sandbox_id, s)` | Extend/shorten sandbox life |
| `kill_process(sandbox_id, pid)` | `Sandbox.connect(sandbox_id).commands.kill(pid)` | Kill specific process |

**Agent awareness:** The agent does NOT know the control plane exists.
It reads governance files normally. We write to those files from outside.
The agent picks up changes on its next cycle.

#### 7.2 CLI Commands

```bash
python -m social_agent kill <sandbox_id>        # Kill a sandbox
python -m social_agent kill --all               # Kill all sandboxes
python -m social_agent observe <sandbox_id>     # Live observation
python -m social_agent sandboxes                # List active sandboxes
python -m social_agent inject-rule <id> "rule"  # Inject a rule
python -m social_agent processes <sandbox_id>   # List processes
python -m social_agent serve <sandbox_id>       # Start dashboard server
```

#### 7.3 Heartbeat Protocol

The agent writes `heartbeat.json` every cycle:

```json
{
  "timestamp": "2026-02-15T12:00:00Z",
  "current_action": "REPLY",
  "action_started_at": "2026-02-15T11:59:45Z",
  "cycle_count": 42,
  "sandbox_id": "sbx_abc123"
}
```

External control reads this file to determine health:

| State | Condition | Action |
|-------|-----------|--------|
| HEALTHY | heartbeat < 60s old | None |
| STUCK | heartbeat 60s-600s old | Alert via Telegram |
| DEAD | heartbeat > 600s old OR sandbox not running | Kill + redeploy |
| UNKNOWN | Cannot connect to sandbox | Attempt reconnect, then redeploy |

#### 7.4 Public Dashboard API

REST endpoints served by `http.server` (stdlib, zero deps):

| Endpoint | Method | Auth | Purpose |
|----------|--------|------|---------|
| `/api/status` | GET | Public | Agent state + health + sandbox info |
| `/api/activity?limit=50` | GET | Public | Recent activity records |
| `/api/stats` | GET | Public | Aggregated action statistics |
| `/api/brain` | GET | Public | Learning stats per namespace |
| `/api/governance` | GET | Public | DOS, VIOLATIONS, UNKNOWNS, MEMORY content |
| `/api/metrics` | GET | Public | E2B sandbox CPU/memory/disk |
| `/api/heartbeat` | GET | Public | Last heartbeat + health status |
| `/api/cost` | GET | Public | Cost tracking + budget remaining |
| `/api/kill` | POST | Admin | Kill switch (requires `DASHBOARD_TOKEN`) |
| `/api/inject-rule` | POST | Admin | Inject rule (requires `DASHBOARD_TOKEN`) |

**WebSocket (PLANNED):** `ws://host:8081/stream` — will poll activity.jsonl
every 2s and push new entries to connected clients. Not yet implemented;
the dashboard frontend currently uses polling via REST endpoints.

**Auth model:**
- Public viewers see everything read-only (all GET endpoints)
- Admin actions (kill, inject) require `DASHBOARD_TOKEN` in `Authorization` header
- Token set via `DASHBOARD_TOKEN` env var

**Revenue model:** Shareable public URL. Anyone can watch Nathan learn.
Admin features behind auth. The dashboard is our first revenue product.

#### 7.5 Dashboard Frontend

Pure HTML + vanilla JS + CSS. No build tools, no React, no npm.
Served as static files by the dashboard server.

**Sections:**
1. **Status bar** — agent health (green/yellow/red dot), sandbox ID, uptime
2. **Live activity feed** — WebSocket-powered, auto-scrolling
3. **Statistics panel** — success rate, quality score, posts/replies today
4. **Brain panel** — per-namespace learning stats
5. **Governance panel** — read-only view of DOS, VIOLATIONS, MEMORY
6. **Admin panel** (auth required) — kill switch button, inject rule form
7. **Cost panel** — estimated cost, budget remaining

## 5. Safety Bounds (JPL Rules)

| Bound | Value | Rationale |
|-------|-------|-----------|
| max_cycles | 500 | No unbounded loops (JPL Rule 1) |
| cycle_interval | 15s min | Rate limit agent actions |
| max_posts_per_day | 5 | Prevent spam |
| max_replies_per_day | 20 | Reasonable engagement |
| quality_threshold | 0.7 | Don't post low-quality content |
| circuit_breaker | 5 failures | Auto-pause on repeated errors |
| recursion_limit | 50 | Max LLM calls per orchestrator cycle |
| compaction_threshold | 0.8 | Trigger compaction at 80% of context window |
| sandbox_timeout | 3600s | Kill sandbox if stuck |
| migration_threshold | 300s | Start migration when <=5 min remaining |
| migration_retries | 3 | Max attempts to create successor |
| handoff_timeout | 120s | Max wait for successor verification |
| git_retry_limit | 3 | Max retries on failed git push |
| watchdog_interval | 900s | GitHub Actions checks every 15 min |
| max_concurrent_sandboxes | 2 | Old + new during migration only |
| max_migrations_per_day | 10 | Prevent migration loops |
| budget_limit_usd | 50.0 | Total budget enforcement |
| cost_alert_threshold | 0.8 | Alert at 80% of budget |

## 6. Data Flow (Single Cycle)

```text
1. ORCHESTRATOR wakes up
2. Reads governance files (DOS, VIOLATIONS, UNKNOWNS, MEMORY, external_overrides)
3. Reads current state (state.json)
4. CHECKS: check_time_remaining() — do I need to migrate?
   +-- If yes -> MIGRATE (see Migration Flow below)
5. CHECKS: check_budget() — am I within budget?
   +-- If exceeded -> PAUSE + alert via Telegram
6. THINKS: "What should I do?" (chain-of-thought reasoning)
7. DECIDES: Calls a tool (e.g., read_feed, reply, create_post)
8. If content needed: DELEGATES to sub-agent (LearningLLM)
9. Sub-agent returns content with quality score
10. Quality gate: only posts if score >= threshold
11. EXECUTES: Performs the action (via Moltbook API)
12. LOGS: Writes to activity.jsonl + cost.jsonl
13. HEARTBEAT: Writes heartbeat.json
14. GIT SYNC: Push changes to GitHub (background, non-blocking)
15. NOTIFIES: Sends Telegram message (thinks it's self-logging)
16. UPDATES: Saves state, updates governance files if needed
17. SLEEPS: Waits cycle_interval
18. REPEATS from 1
```

### Migration Flow (when time is running low)

```text
1. Agent detects: check_time_remaining() <= migration_threshold
2. PARALLEL:
   +-- git_sync() — final push, ensure brain is 100% current
   +-- create_sandbox() — spin up new E2B instance
3. deploy_self(new_sandbox_id) — clone repo, install, start
4. verify_successor(new_sandbox_id) — poll heartbeat.json until alive
   +-- Success -> graceful_shutdown() (log, exit)
   +-- Failure -> retry (up to migration_retries)
       +-- All retries failed -> continue on current body, log violation
```

### Resurrection Flow (after unexpected death)

```text
1. GitHub Actions watchdog detects: no running sandboxes (via Sandbox.list())
2. Creates new E2B sandbox
3. Clones nathan-brain repo from GitHub (the always-current brain)
4. Installs social-agent package
5. Starts agent with: python -m social_agent run
6. Agent loads state.json, governance files, resumes
```

## 7. Cost Model

### 7.1 Cost Sources

| Source | Metric | Approximate Cost |
|--------|--------|-----------------|
| LLM calls (gpt-4o-mini) | tokens in/out | ~$0.15/1M input, $0.60/1M output |
| E2B sandbox | seconds running | ~$0.05/hour |
| GitHub Actions | minutes | Free tier (2000 min/month) |

### 7.2 Cost Tracking

`CostTracker` captures every expense:
- Wraps `brain.call()` to extract token counts from netanel-core's `CallResult`
- Logs E2B sandbox uptime per cycle
- Writes to `logs/cost.jsonl`: `{timestamp, source, tokens_in, tokens_out, estimated_usd}`

### 7.3 Budget Enforcement

- `budget_limit_usd: 50.0` — hard stop
- `cost_alert_threshold: 0.8` — alert at 80% ($40)
- Before each cycle: `check_budget()` — if exceeded, pause agent + alert
- Exposed via dashboard API `/api/cost`

## 8. Monitoring

- **LangSmith**: Every LLM call traced (env vars, automatic)
- **Telegram**: Every action notified in real-time
- **Activity Log**: JSONL with every action, timestamp, score, details
- **Cost Log**: JSONL with every cost entry
- **Heartbeat**: JSON health signal updated every cycle
- **Dashboard API**: REST + WebSocket for real-time observation
- **Dashboard Frontend**: Public web interface (HTML/JS/CSS)
- **Governance files**: Agent's own self-tracking (readable externally)

## 9. Dependencies

| Package | Purpose | Version |
|---------|---------|---------|
| netanel-core | Self-learning engine + DeepAgent | 0.1.0 |
| e2b-code-interpreter | Sandboxed execution | >=1.0 |
| httpx | HTTP client (direct, no nested sandbox) | >=0.27 |
| duckduckgo-search | Web search | latest |
| python-telegram-bot | Notifications | >=21 |
| python-dotenv | Env loading | >=1.0 |
| pydantic-settings | Config validation | >=2.0 |

**No new dependencies required.** `http.server` is stdlib. `websockets` is
already installed. Everything else uses the existing E2B SDK and Python stdlib.

## 10. Build Order

```text
Phase 0: Foundation
  Step 1-5:  Config, sandbox, moltbook, brain, dashboard CLI    DONE

Phase 1: Safety First
  Step 6:    External Control Module (control.py)               DONE
  Step 7:    Heartbeat + Stuck Detection                        DONE

Phase 2: Dashboard Backend + Public Frontend
  Step 8:    Dashboard API Server (server.py)                   DONE
  Step 9:    Public Dashboard Frontend (static HTML/JS/CSS)     DONE

Phase 3: Persistence + Cost
  Step 10:   Git Persistence Layer (git_sync.py)                DONE
  Step 11:   Cost Tracking (cost.py)                            DONE

Phase 4: Self-Migration + Watchdog
  Step 12:   Lifecycle Tools (lifecycle.py)                     DONE
  Step 13:   GitHub Actions Watchdog (watchdog.yml)             DONE

Phase 5: Architecture Sync + Polish
  Step 14:   Architecture Doc Update (status table)             DONE
  Step 15:   Dashboard Deploy + Revenue Readiness               PLANNED

Total: 412 tests across 14 test files, 0 lint errors
```

### Dependency Graph

```text
Step 6 (control.py) <- BLOCKING for everything
  +-- Step 7 (heartbeat) -> depends on control
  |     +-- Step 8 (server) -> depends on control + heartbeat
  |     |     +-- Step 9 (frontend) -> depends on server
  |     +-- Step 13 (watchdog) -> depends on heartbeat
  +-- Step 10 (git sync) -> independent of control, can parallel
  |     +-- Step 12 (lifecycle) -> depends on git sync
  +-- Step 11 (cost) -> independent, can parallel with anything
```

## 11. Migration from v1

v1 (current): Deterministic Python state machine, E2B for HTTP calls only.
v2 (target): LLM-powered orchestrator, everything in E2B, self-governing, self-preserving.

**What stays:**
- Sub-agent namespaces (LearningLLM per task)
- Moltbook client (HTTP calls)
- Telegram notifier
- Activity logging
- Quality gates
- Safety bounds

**What changes:**
- Agent loop -> Orchestrator (DeepAgent with tools)
- Fixed state machine -> Dynamic reasoning
- Local execution -> Fully inside E2B
- No self-awareness -> Self-governance system
- Manual monitoring -> External control layer + dashboard
- Ephemeral state -> Git-persisted brain (always current)
- Single repo -> Two repos (source + brain)

**What's new:**
- External Control Plane (Layer 7) — kill switch, observation, rule injection
- Heartbeat protocol — health monitoring from outside
- Public Dashboard API — REST + WebSocket for real-time observation
- Dashboard Frontend — public web interface
- Cost tracking — token + E2B cost, budget enforcement
- Governance files (DOS, VIOLATIONS, UNKNOWNS, MEMORY)
- Compaction lifecycle hooks
- Orchestrator as its own LearningLLM namespace
- Tool-based sub-agent delegation
- Agent identity and self-awareness prompt
- Git persistence (push after every file change, parallel, free)
- Git tracker (audit trail of all pushes)
- Self-migration (agent creates new body, verified handoff, graceful death)
- Migrate-agent (LearningLLM that learns optimal migration timing)
- GitHub Actions watchdog (crash recovery, the ONE external safety net)
- Agent knows its body is disposable — brain on GitHub is permanent

## 12. Implementation Status

| # | Feature | Layer | Status | Step |
|---|---------|-------|--------|------|
| 1 | Config + validation | Foundation | DONE | 1 |
| 2 | E2B sandbox client | Foundation | DONE | 1 |
| 3 | Moltbook API client | Foundation | DONE | 2 |
| 4 | Telegram notifier | Foundation | DONE | 2 |
| 5 | Agent brain (LearningLLM) | Layer 2 | DONE | 3 |
| 6 | Agent loop (state machine) | Layer 1 | DONE | 4 |
| 7 | Dashboard CLI | Monitoring | DONE | 5 |
| 8 | Kill switch | Layer 7 | DONE | 6 |
| 9 | External file I/O | Layer 7 | DONE | 6 |
| 10 | Rule injection | Layer 7 | DONE | 6 |
| 11 | Sandbox metrics | Layer 7 | DONE | 6 |
| 12 | Heartbeat protocol | Layer 7 | DONE | 7 |
| 13 | Stuck detection | Layer 7 | DONE | 7 |
| 14 | Dashboard REST API | Layer 7 | DONE | 8 |
| 15 | WebSocket streaming | Layer 7 | PLANNED | — |
| 16 | Dashboard frontend | Layer 7 | DONE | 9 |
| 17 | Git persistence | Layer 6 | DONE | 10 |
| 18 | Cost tracking | Layer 7 | DONE | 11 |
| 19 | Budget enforcement | Safety | DONE | 11 |
| 20 | Self-migration | Layer 6 | DONE | 12 |
| 21 | Orphan cleanup | Safety | DONE | 12 |
| 22 | Watchdog (GitHub Actions) | Layer 6 | DONE | 13 |
| 23 | Crash recovery | Layer 6 | DONE | 13 |
| 24 | Self-governance system | Layer 3 | PARTIAL | — |
| 25 | Compaction lifecycle | Layer 4 | PLANNED | — |
| 26 | DeepAgent orchestrator | Layer 1 | PLANNED | — |

## 13. Audit Trail: 14 Gaps Identified (2026-02-15)

| # | Gap | Severity | Addressed By |
|---|-----|----------|-------------|
| 1 | Kill switch — no external stop mechanism | CRITICAL | Step 6: `SandboxController.kill()` |
| 2 | Real-time observation — can't see agent state live | CRITICAL | Steps 8-9: Dashboard API + Frontend |
| 3 | Rogue agent — all safety is self-enforced | MAJOR | Step 6: External control plane |
| 4 | External control — can't change rules without SSH | MAJOR | Step 6: `inject_rule()`, `write_file()` |
| 5 | Self-migration tools — all hypothetical | CRITICAL | Step 12: LifecycleManager |
| 6 | Git persistence — no git code exists | MAJOR | Step 10: GitSync |
| 7 | Cost control — no tracking or budget | HIGH | Step 11: CostTracker |
| 8 | Public dashboard — no web interface | MEDIUM | Steps 8-9: Server + Frontend |
| 9 | Merge conflicts — no resolution mechanism | MAJOR | Two-repo model (agent is sole writer) |
| 10 | First boot — no initialization script | MEDIUM | Step 13: Watchdog handles deployment |
| 11 | Race conditions in handoff | CRITICAL | Step 12: max_concurrent_sandboxes=2, verified handoff |
| 12 | Community feedback loop — agent doesn't read own stats | MEDIUM | Step 8: `/api/stats` available for future use |
| 13 | Safety enforcement — rules exist but not validated | HIGH | Step 6: External rule injection + monitoring |
| 14 | Orphaned sandbox cleanup | HIGH | Step 12+13: LifecycleManager + Watchdog |
