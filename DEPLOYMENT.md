# Social Agent - Complete Deployment Plan

**Version:** 1.0
**Date:** 2026-02-16
**Status:** READY FOR EXECUTION

---

## Executive Summary

Deploy the autonomous social agent with public dashboard monitoring.

**Architecture:**
- **Agent**: Runs in E2B sandbox (autonomous, self-migrating)
- **Brain**: nathan-brain repo (agent's living state, git-backed)
- **Dashboard**: Railway deployment (public monitoring interface)

**Key Insight:** Dashboard must auto-discover active sandbox (not hardcoded) to support agent self-migration.

---

## Current State

### ✅ Complete
- social-agent code (416 tests passing)
- nathan-brain repo created
- Railway account (24 days available)
- E2B API key configured
- Dockerfile for dashboard

### ❌ Missing
1. GitHub token (for agent → nathan-brain pushes)
2. Dashboard token (admin API protection)
3. Dashboard auto-discovery (reads sandbox_id from git, not hardcoded)
4. Railway deployment
5. Agent not running (no active sandbox)

---

## Problem: Sandbox ID Tracking

**Issue:** Dashboard requires `sandbox_id` as CLI argument, but agent creates new sandboxes on migration.

**Current (broken):**
```bash
# Dashboard hardcodes sandbox ID
python -m social_agent serve sbx_abc123

# Agent migrates to new sandbox
# Dashboard still monitors old (dead) sandbox ❌
```

**Solution: Auto-Discovery via Git**

Agent writes `current_sandbox_id` to `nathan-brain/state.json`:
```json
{
  "current_sandbox_id": "sbx_xyz789",
  "posts_today": 5,
  ...
}
```

Dashboard reads from git instead of CLI arg:
```python
# Before starting, read from git
sandbox_id = read_from_nathan_brain("state.json")["current_sandbox_id"]
server = DashboardServer(sandbox_id)
```

**Result:** Dashboard always monitors the latest sandbox. Zero manual updates. ✅

---

## Deployment Steps

### Phase 1: Pre-Deployment Setup (5 minutes)

**Step 1.1: Generate GitHub Token**
```bash
# Create fine-grained token:
# - Repo: netanel-systems/nathan-brain
# - Permissions: Contents (Read and Write)
# - Expiration: 90 days

# Go to: https://github.com/settings/tokens?type=beta
# Name: "social-agent-brain-writer"
# Repository access: Only select repositories → nathan-brain
# Permissions: Contents (Read and write)
```

**Output needed:** `ghp_...` token

**Step 1.2: Generate Dashboard Token**
```bash
# Create secure random token for admin API
openssl rand -hex 32
```

**Output needed:** Random hex string (64 chars)

**Step 1.3: Add tokens to social-agent .env**
```bash
cd ~/netanel/projects/social-agent
echo "GITHUB_TOKEN=ghp_..." >> .env
echo "DASHBOARD_TOKEN=..." >> .env
```

---

### Phase 2: Code Changes (15 minutes)

**Step 2.1: Add sandbox_id to state.json schema**

File: `src/social_agent/agent.py` (or wherever state is managed)

Add field to state:
```python
{
  "current_sandbox_id": "sbx_...",  # NEW: track active sandbox
  "posts_today": 0,
  "replies_today": 0,
  ...
}
```

Agent writes sandbox_id on startup and after migration.

**Step 2.2: Create auto-discovery helper**

File: `src/social_agent/discovery.py` (NEW)
```python
"""Auto-discover active sandbox from nathan-brain repo."""
import json
import subprocess
from pathlib import Path

def get_active_sandbox_id(brain_repo_path: str = "~/nathan-brain") -> str:
    """Read current sandbox ID from nathan-brain/state.json.

    Pulls latest from git, reads state.json, returns sandbox_id.
    Returns placeholder if not found (agent not started yet).
    """
    path = Path(brain_repo_path).expanduser()

    # Pull latest
    subprocess.run(["git", "-C", str(path), "pull", "--quiet"], check=True)

    # Read state
    state_file = path / "state.json"
    if not state_file.exists():
        return "sbx-not-started"  # Placeholder

    state = json.loads(state_file.read_text())
    return state.get("current_sandbox_id", "sbx-not-started")
```

**Step 2.3: Modify dashboard server to use auto-discovery**

File: `src/social_agent/server.py`

Change:
```python
# OLD: CLI arg required
def main():
    parser.add_argument("sandbox_id", help="Sandbox ID to monitor")
    ...
    server = DashboardServer(sandbox_id=args.sandbox_id)

# NEW: Auto-discover from git
from social_agent.discovery import get_active_sandbox_id

def main():
    # Optional: allow override via CLI
    parser.add_argument("--sandbox-id", default=None, help="Override sandbox ID")
    ...
    sandbox_id = args.sandbox_id or get_active_sandbox_id()
    if sandbox_id == "sbx-not-started":
        print("⚠️  Agent not started yet. Dashboard will show 'No Data'")
    server = DashboardServer(sandbox_id=sandbox_id)
```

**Step 2.4: Update Dockerfile**

File: `Dockerfile`

Change CMD:
```dockerfile
# OLD
CMD python -m social_agent serve "${SANDBOX_ID}" --port "${PORT}"

# NEW (no SANDBOX_ID env var needed)
CMD python -m social_agent serve --port "${PORT}"
```

**Step 2.5: Add nathan-brain clone to Dockerfile**

File: `Dockerfile`

Add before CMD:
```dockerfile
# Clone nathan-brain for auto-discovery
RUN git clone https://github.com/netanel-systems/nathan-brain.git /nathan-brain
ENV BRAIN_REPO_PATH=/nathan-brain
```

---

### Phase 3: Deploy Dashboard to Railway (10 minutes)

**Step 3.1: Push changes to GitHub**
```bash
cd ~/netanel/projects/social-agent
git add -A
git commit -m "feat(dashboard): auto-discover sandbox from nathan-brain

- Add current_sandbox_id to state.json
- Create discovery.py helper (reads from git)
- Update server.py to use auto-discovery
- Update Dockerfile to clone nathan-brain
- Remove hardcoded SANDBOX_ID requirement

This enables dashboard to track agent across self-migrations."

git push
```

**Step 3.2: Deploy to Railway**
```bash
cd ~/netanel/projects/social-agent

# Login to Railway
railway login

# Link to existing project or create new
railway link

# Add environment variables
railway variables set E2B_API_KEY="e2b_..."
railway variables set DASHBOARD_TOKEN="..."
railway variables set GITHUB_TOKEN="ghp_..."  # For nathan-brain access

# Deploy
railway up
```

**Step 3.3: Get Railway URL**
```bash
railway domain
```

**Output:** `https://social-agent-production.up.railway.app`

---

### Phase 4: Start Agent (5 minutes)

**Step 4.1: Configure agent environment**
```bash
cd ~/netanel/projects/social-agent

# Ensure .env has all required vars
cat .env | grep -E "(OPENAI|E2B|GITHUB|BRAIN_REPO)"

# Should see:
# OPENAI_API_KEY=sk-...
# E2B_API_KEY=e2b_...
# GITHUB_TOKEN=ghp_...
# (BRAIN_REPO_URL will use default: git@github.com:netanel-systems/nathan-brain.git)
```

**Step 4.2: Run agent locally (first time)**
```bash
cd ~/netanel/projects/social-agent
source .venv/bin/activate

# Dry run first (verify config)
python -m social_agent status

# Start agent
python -m social_agent run
```

**Agent will:**
1. Create E2B sandbox
2. Write `current_sandbox_id` to state.json
3. Push to nathan-brain repo
4. Start autonomous operation

**Step 4.3: Verify dashboard shows data**

Open Railway URL → Dashboard should now show:
- Current sandbox ID
- Agent status
- Activity logs
- Cost tracking

---

## Post-Deployment Verification

### ✅ Checklist

1. **Dashboard accessible**
   - Open Railway URL
   - See dashboard UI
   - No errors in logs

2. **Sandbox ID displayed**
   - Dashboard shows `sbx_...` (not "sbx-not-started")
   - Matches agent's E2B sandbox

3. **Auto-discovery working**
   - Check nathan-brain/state.json has `current_sandbox_id`
   - Dashboard reflects current sandbox

4. **API endpoints working**
   - GET /api/health → 200
   - GET /api/state → shows agent state
   - GET /api/cost → shows cost data

5. **Agent running**
   - Logs show cycles
   - Pushes to nathan-brain every ~15s
   - LangSmith shows LLM calls

---

## Troubleshooting

### Dashboard shows "No Data"
- **Cause:** Agent not started yet (state.json missing sandbox_id)
- **Fix:** Start agent with `python -m social_agent run`

### Dashboard shows old sandbox ID
- **Cause:** Git pull failed in discovery.py
- **Fix:** Check GITHUB_TOKEN permissions, verify nathan-brain repo access

### Railway deployment fails
- **Cause:** Environment variables missing
- **Fix:** `railway variables` → verify E2B_API_KEY, GITHUB_TOKEN set

### Agent fails to start
- **Cause:** Missing API keys in .env
- **Fix:** Check .env has OPENAI_API_KEY, E2B_API_KEY, GITHUB_TOKEN

---

## Cost Estimate

- **Railway**: $5/month (starter plan, usage-based)
- **E2B**: $10/month (sandbox runtime ~$0.15/hour, agent runs 24/7)
- **OpenAI**: $2-5/month (gpt-4o-mini, ~1000-2000 calls/day)
- **GitHub**: Free (nathan-brain repo)

**Total:** ~$17-20/month

---

## Rollback Plan

If deployment fails:

1. **Railway:** Delete service, no charges
2. **Agent:** Kill sandbox: `python -m social_agent kill <sandbox_id>`
3. **Code:** `git revert HEAD` if changes break anything

---

## Next Steps After Deployment

1. **Monitor for 24 hours**
   - Check dashboard daily
   - Verify git pushes to nathan-brain
   - Track costs in dashboard

2. **Optional: Add Moltbook credentials**
   - Agent will start posting/replying
   - Currently runs in monitoring-only mode

3. **Optional: Add Telegram notifications**
   - Real-time alerts on errors
   - Budget threshold warnings

---

## Summary: What You Need to Do

### 1. Create GitHub Token (2 minutes)
- Go to https://github.com/settings/tokens?type=beta
- Name: "social-agent-brain-writer"
- Repository: netanel-systems/nathan-brain
- Permissions: Contents (Read and write)
- Expiration: 90 days
- **Copy the token** (starts with `ghp_`)

### 2. Generate Dashboard Token (1 minute)
```bash
openssl rand -hex 32
```
**Copy the output** (64-char hex string)

### 3. Provide Both Tokens
Once you have both tokens, I will:
- Update .env files
- Make code changes
- Deploy to Railway
- Start the agent
- Verify everything works

**That's it. Just provide the two tokens and I handle the rest.**

---

**Ready to proceed?**
