# Browser Agent

The Browser Agent turns a natural-language objective into bounded,
policy-gated browser work.

## Configuration

`objective` (required), `browser_profile`, `allowed_domains`, `max_steps`
(≤500), `timeout`, `model_policy`, `memory_policy`, `risk_policy`,
`human_takeover_policy`.

## Loop

```text
Goal → Plan (bounded) → Browser Tool → Observation (compressed) → Model
  → Next Action → … → Structured Result → Memory / Workflow / Manager
```

- Compact observations only (budgets in `observations.py`); full DOM never
  enters context.
- State fingerprints (`url`/`title`/text/DOM/elements hashes) drive loop
  detection, change detection, and crash recovery.
- Recovery replays only retry-safe reads; mutating actions stay `PENDING`
  for explicit operator decision.
- Playground: `/browser/playground` shows plan, observations, actions,
  results and the final answer — never hidden chain-of-thought.
