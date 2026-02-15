# DO's — Pre-Flight Checklist

> Check BEFORE every action. No exceptions.

## Before Writing Code
- [ ] Read ARCHITECTURE.md — does this change align?
- [ ] Read CLAUDE.md — does this follow our rules?
- [ ] Check VIOLATIONS.md — am I repeating a past mistake?
- [ ] Verify API signatures from official docs — no guessing

## Before Committing
- [ ] Tests pass: `pytest`
- [ ] Lint clean: `ruff check`
- [ ] Type clean: `mypy`
- [ ] No secrets in code (check .env.example only)
- [ ] No hardcoded API keys, passwords, or tokens

## Before PR
- [ ] Issue exists for this step
- [ ] Branch named: `step-N-description`
- [ ] All acceptance criteria from issue met
- [ ] ARCHITECTURE.md updated if design changed

## Agent Safety
- [ ] All external actions go through E2B sandbox
- [ ] Rate limits enforced (max_posts, max_replies, cycle_interval)
- [ ] Quality threshold checked before posting (score >= 0.7)
- [ ] Telegram notification sent for every public action
- [ ] Circuit breaker active (5 failures → pause)
- [ ] Budget tracking active

## Memory Locations
- **netanel-core memories:** `memories/` (gitignored, per-namespace)
  - `memories/moltbook-decide/patterns/` — decision learnings
  - `memories/moltbook-content/patterns/` — content learnings
  - `memories/moltbook-reply/patterns/` — reply learnings
  - `memories/moltbook-analyze/patterns/` — analysis learnings
  - `memories/*/prompts/prompt_current.md` — evolved prompts
- **Activity log:** `logs/activity.jsonl` (gitignored)
- **Agent state:** `state.json` (gitignored, tracks daily counts)
