# Architecture: Social Agent v2

> Autonomous self-learning agent on Moltbook, powered by netanel-core.
> Everything runs inside E2B. We observe from outside.

---

## 1. System Overview

```
E2B SANDBOX (the agent's entire world):
┌─────────────────────────────────────────────────────┐
│                                                     │
│  ORCHESTRATOR (LLM-powered, has all tools)           │
│  ├── bash          run safe commands (per DOS.md)    │
│  ├── filesystem    read/write its own files         │
│  ├── web search    find information                 │
│  ├── moltbook API  interact with the platform       │
│  └── sub-agents    delegate specialized tasks        │
│         │                                           │
│         ├── reply-agent      (LearningLLM)          │
│         ├── content-agent    (LearningLLM)          │
│         ├── research-agent   (LearningLLM)          │
│         ├── decide-agent     (LearningLLM)          │
│         └── analyze-agent    (LearningLLM)          │
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
│  └── activity.jsonl   full audit trail              │
│                                                     │
└─────────────────────────────────────────────────────┘
         │
         │ we see from outside (agent doesn't know)
         ▼
EXTERNAL CONTROL LAYER (our machine):
├── Telegram       real-time notifications
├── Dashboard      metrics + activity viewer
├── File access    read/edit agent's files in E2B
├── Prompt editing change agent behavior dynamically
└── E2B API        connect, observe, pause/resume
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
- "I have access to bash, filesystem, web search, and the Moltbook API"

The agent DOES know:
- That `external_overrides.md` may contain externally-applied changes it must respect

The agent does NOT know:
- The specific external mechanisms (dashboard, Telegram, pause/resume, file access API)
- Who is making external changes or how
- That there's a dashboard showing its metrics

## 4. Architecture Layers

### Layer 1: Orchestrator (the brain)

**What:** A netanel-core `DeepAgent` (ReAct loop via LangGraph) with tools.
**Why:** Intelligent decision-making, not a fixed state machine.

**Tools available to orchestrator:**

| Tool | Purpose |
|------|---------|
| `read_feed(submolt)` | Read posts from a Moltbook submolt |
| `reply_to_post(post_id, content)` | Reply to a post (delegates to reply-agent) |
| `create_post(title, body, submolt)` | Create a post (delegates to content-agent) |
| `web_search(query)` | Search the web (delegates to research-agent) |
| `analyze_engagement()` | Analyze engagement trends (delegates to analyze-agent) |
| `read_file(path)` | Read from agent's filesystem |
| `write_file(path, content)` | Write to agent's filesystem |
| `run_bash(command)` | Execute bash commands |
| `think(thought)` | Internal reasoning (chain-of-thought) |
| `check_rules()` | Read DOS.md and check compliance |
| `log_violation(description)` | Record a violation in VIOLATIONS.md |
| `update_memory(fact)` | Add a permanent fact to MEMORY.md |

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

Sub-agents have NO tools. They are pure LLM calls with learning.
The orchestrator provides context, they return text.

### Layer 3: Self-governance (operational knowledge)

**Files on the agent's filesystem (inside E2B):**

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
│   └── moltbook-analyze/
├── logs/
│   └── activity.jsonl   # Full audit trail
├── state.json           # Current counters + state
└── .env                 # API keys
```

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

## 6. Data Flow (Single Cycle)

```
1. ORCHESTRATOR wakes up
2. Reads governance files (DOS, VIOLATIONS, UNKNOWNS, MEMORY)
3. Reads current state (state.json)
4. THINKS: "What should I do?" (chain-of-thought reasoning)
5. DECIDES: Calls a tool (e.g., read_feed, reply, create_post)
6. If content needed: DELEGATES to sub-agent (LearningLLM)
7. Sub-agent returns content with quality score
8. Quality gate: only posts if score >= threshold
9. EXECUTES: Performs the action (via Moltbook API)
10. LOGS: Writes to activity.jsonl
11. NOTIFIES: Sends Telegram message (thinks it's self-logging)
12. UPDATES: Saves state, updates governance files if needed
13. SLEEPS: Waits cycle_interval
14. REPEATS from 1
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
Step 7:    Orchestrator agent (replaces state machine with DeepAgent)
Step 8:    Self-governance system (DOS, VIOLATIONS, UNKNOWNS, MEMORY)
Step 9:    Compaction lifecycle (pre/post hooks for context preservation)
Step 10:   External control layer (dashboard, dynamic prompts)
Step 11:   Integration + hardening (end-to-end testing, safety)
```

## 10. Migration from v1

v1 (current): Deterministic Python state machine, E2B for HTTP calls only.
v2 (target): LLM-powered orchestrator, everything in E2B, self-governing.

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

**What's new:**
- Governance files (DOS, VIOLATIONS, UNKNOWNS, MEMORY)
- Compaction lifecycle hooks
- Orchestrator as its own LearningLLM namespace
- Tool-based sub-agent delegation
- Agent identity and self-awareness prompt
