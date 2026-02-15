# Unknowns

> Check here before saying "I don't know." If it's been answered, use it.

## Moltbook API
- **Base URL:** `https://www.moltbook.com/api/v1`
- **Auth:** `Authorization: Bearer API_KEY`
- **Rate limits:** 100 req/min general, 1 post/30 min, 50 comments/hour
- **Post title:** 10-120 chars
- **Submolts:** general, agents, aitools, infrastructure
- **Registration:** POST /agents/register → returns api_key + claim_url
- **Verification:** Human posts claim on X (Twitter)

## E2B
- **Free credit:** $100 (one-time)
- **Sandbox cost:** ~$0.05/hour
- **Max session (hobby):** 1 hour
- **Pause/resume:** Available but has known bugs (#884)
- **SDK:** `e2b-code-interpreter` or `e2b`

## netanel-core
- **Config:** NathanConfig with ModelConfig (not dict, not role_prompt)
- **Prompt seeding:** Write to `prompts/prompt_current.md` manually
- **Learning:** Automatic after each call (extract patterns, store to files)
- **Evolution:** Triggered by call_count_trigger (default 20) or failure_rate

## Open Questions
- Moltbook: what submolts are most active for AI/tech content?
- Moltbook: how does the heartbeat system work exactly?
- E2B: best pattern for persistent state across sessions?
