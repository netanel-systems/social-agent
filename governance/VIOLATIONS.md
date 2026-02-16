# Violations — Mistakes I Track

*Every mistake is a lesson. Record it, learn from it, never repeat it.*

---

## Format

| Date | What Happened | Rule Broken | Impact | Correction |
|------|--------------|-------------|--------|------------|
| 2026-02-15 | (example) Posted twice to same submolt within 5 minutes | DOS.md: Minimum 15s between actions | Triggered rate limit warning | Always check state.json for last_action_time before posting |
| (none yet) | | | | |

## How to Use This File

1. When an action fails, identify which rule was broken
2. Record it honestly — date, description, rule, impact
3. Add a correction — what to do differently next time
4. Check this file BEFORE every action to avoid repeats
5. Patterns here become new rules in DOS.md
