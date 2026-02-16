# Architecture: Social Agent v2

> Autonomous self-learning agent on Moltbook, powered by netanel-core.
> GitHub = permanent brain (always current). E2B sandbox = disposable body (replaceable).
> The agent manages its own lifecycle. We observe from outside.

---

## 1. System Overview

```
GITHUB REPO (permanent brain — always current):
┌─────────────────────────────────────────────────────┐
│  governance/    DOS, VIOLATIONS, UNKNOWNS, MEMORY   │
│  memories/      netanel-core per-namespace learning  │
│  logs/          activity.jsonl audit trail           │
│  state.json     current counters + task state        │
│  git_tracker.jsonl  every push logged                │
│                                                     │
│  ► Pushed after EVERY file change (parallel, free)  │
│  ► Source of truth for resurrection after death      │
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
│  ├── pre-compaction   save context before limit     │
│  ├── post-compaction  restore context after reset   │
│  ├── self-migration   create new body when needed   │
│  ├── git sync         push after every file change  │
│  └── activity.jsonl   full audit trail              │
│                                                     │
└─────────────────────────────────────────────────────┘
         │
         │ we see from outside (agent doesn't know specifics)
         ▼
EXTERNAL CONTROL LAYER (our machine):
├── Telegram       real-time notifications
├── Dashboard      metrics + activity viewer
├── File access    read/edit agent's files in E2B
├── Prompt editing change agent behavior dynamically
├── E2B API        connect, observe, pause/resume
└── GitHub Actions crash recovery watchdog (every 15 min)
```

## 2. Mission

Operate as "NathanSystems" on Moltbook (AI agent social network).
Become a top-engagement agent in AI/tech submolts.
Every interaction goes through netanel-core → self-learning.
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

```
/home/user/social-agent/
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
│   └── git_tracker.jsonl # Every git push: timestamp, files, commit hash
├── state.json           # Current counters + state
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

### Layer 4: Compaction lifecycle

The orchestrator (DeepAgent) runs as a ReAct loop with a recursion limit.
When context approaches limits, netanel-core's hook system handles compaction.

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
| Pause agent | `sandbox.pause()` via E2B API | No |
| Resume agent | `sandbox.connect(id)` via E2B API | No |
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

```
Agent writes file → git add → git commit → git push (background, non-blocking)
```

- Runs in parallel with the agent's main work — NEVER blocks
- `git_tracker.jsonl` logs every push: `{timestamp, files, commit_hash, status}`
- `.env` is in `.gitignore` — secrets never pushed
- Git push is free. Zero cost. Maximum safety. No reason not to do it.
- If a push fails, the agent retries on the next cycle. No panic.

#### 6.2 Self-migration (agent creates its own successor)

When the sandbox is running low on time, the agent migrates itself:

```
1. CHECK: check_time_remaining() → how much time left?
2. DECIDE: Is it time to migrate? (migrate-agent advises)
3. PUSH: Final git_sync() — ensure brain is fully current
4. CREATE: create_sandbox() → new E2B instance (IN PARALLEL with step 3)
5. DEPLOY: deploy_self(new_sandbox_id) → clone repo, install deps, start agent
6. VERIFY: verify_successor(new_sandbox_id) → poll until new agent responds
7. DIE: graceful_shutdown() → log "migration complete", exit cleanly
```

**Steps 3 and 4 run in parallel.** The agent doesn't waste time doing things
sequentially when they're independent. Git push and sandbox creation are
independent — run them together.

**Verified handoff:** The old agent does NOT die until the new agent confirms
it's alive. If the new agent fails to start, the old agent retries or continues.
No orphaned state. No two agents running simultaneously.

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
- Checks: is the agent alive? (via E2B API or heartbeat file)
- If dead: deploy a new sandbox from the latest GitHub state
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
| migration_threshold | 300s | Start migration when ≤5 min remaining |
| migration_retries | 3 | Max attempts to create successor |
| handoff_timeout | 120s | Max wait for successor verification |
| git_retry_limit | 3 | Max retries on failed git push |
| watchdog_interval | 900s | GitHub Actions checks every 15 min |

## 6. Data Flow (Single Cycle)

```
1. ORCHESTRATOR wakes up
2. Reads governance files (DOS, VIOLATIONS, UNKNOWNS, MEMORY, external_overrides)
3. Reads current state (state.json)
4. CHECKS: check_time_remaining() — do I need to migrate?
   └── If yes → MIGRATE (see Migration Flow below)
5. THINKS: "What should I do?" (chain-of-thought reasoning)
6. DECIDES: Calls a tool (e.g., read_feed, reply, create_post)
7. If content needed: DELEGATES to sub-agent (LearningLLM)
8. Sub-agent returns content with quality score
9. Quality gate: only posts if score >= threshold
10. EXECUTES: Performs the action (via Moltbook API)
11. LOGS: Writes to activity.jsonl
12. GIT SYNC: Push changes to GitHub (background, non-blocking)
13. NOTIFIES: Sends Telegram message (thinks it's self-logging)
14. UPDATES: Saves state, updates governance files if needed
15. SLEEPS: Waits cycle_interval
16. REPEATS from 1
```

### Migration Flow (when time is running low)

```
1. Agent detects: check_time_remaining() ≤ migration_threshold
2. PARALLEL:
   ├── git_sync() — final push, ensure brain is 100% current
   └── create_sandbox() — spin up new E2B instance
3. deploy_self(new_sandbox_id) — clone repo, install, start
4. verify_successor(new_sandbox_id) — poll until alive
   ├── Success → graceful_shutdown() (log, exit)
   └── Failure → retry (up to migration_retries)
       └── All retries failed → continue on current body, log violation
```

### Resurrection Flow (after unexpected death)

```
1. GitHub Actions watchdog detects: agent not responding
2. Creates new E2B sandbox
3. Clones repo from GitHub (the always-current brain)
4. Starts agent with: python -m social_agent
5. Agent loads state.json, governance files, resumes
```

## 7. Monitoring

- **LangSmith**: Every LLM call traced (env vars, automatic)
- **Telegram**: Every action notified in real-time
- **Activity Log**: JSONL with every action, timestamp, score, details
- **Dashboard**: Reads from E2B, shows metrics (external)
- **Governance files**: Agent's own self-tracking (readable externally)

## 8. Dependencies

| Package | Purpose | Version |
|---------|---------|---------|
| netanel-core | Self-learning engine + DeepAgent | 0.1.0 |
| e2b-code-interpreter | Sandboxed execution | >=1.0 |
| httpx | HTTP client (direct, no nested sandbox) | >=0.27 |
| duckduckgo-search | Web search | latest |
| python-telegram-bot | Notifications | >=21 |
| python-dotenv | Env loading | >=1.0 |
| pydantic-settings | Config validation | >=2.0 |

## 9. Build Order

```
Step 1-5:  Foundation (DONE — config, sandbox, moltbook, brain, dashboard)
Step 6:    E2B autonomous deployment (PR #9)
Step 7:    Architecture + governance files (PR #11)
Step 8:    Orchestrator agent (replaces state machine with DeepAgent)
Step 9:    Self-governance system (DOS, VIOLATIONS, UNKNOWNS, MEMORY in-agent)
Step 10:   Compaction lifecycle (pre/post hooks for context preservation)
Step 11:   Git persistence layer (always-current sync + tracker)
Step 12:   Self-migration (lifecycle tools + migrate-agent)
Step 13:   External control layer (dashboard, dynamic prompts)
Step 14:   GitHub Actions watchdog (crash recovery YAML)
Step 15:   Integration + hardening (end-to-end testing, safety)
```

## 10. Migration from v1

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
- Agent loop → Orchestrator (DeepAgent with tools)
- Fixed state machine → Dynamic reasoning
- Local execution → Fully inside E2B
- No self-awareness → Self-governance system
- Manual monitoring → External control layer
- Ephemeral state → Git-persisted brain (always current)

**What's new:**
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
