# Browser Profiles

```text
Browser Profile: profile_id, owner, organization, display_name,
browser_type, storage_state, policy, timestamps
```

Types: `EPHEMERAL` (default, isolated) | `PERSISTENT` | `SHARED` |
`ORGANIZATION` | `USER`. Anything beyond `EPHEMERAL` requires explicit
policy authorization at creation. `storage_state` (cookies/localStorage)
is server-side only and never enters prompts, logs, or task descriptions.

# Browser Research

Evidence-first flow: search → open → inspect → extract → cross-check →
store evidence with source URLs + timestamps. Page text stays labeled
untrusted; research findings are memory candidates (never credentials).

# Browser Agent

`POST /api/v1/browser/tasks` with `objective`, `max_steps` (≤500),
`timeout`, `risk_policy`, `allowed_domains`. The agent loop plans
bounded subgoals (`TaskPlanner`: step/token/time/cost budgets), compresses
observations, fingerprints state for loop detection (`url`/`dom`/`elements`
repetition ≥3 terminates/replans), and persists every step for crash recovery.

# Browser Workflows

Nodes: `browser_agent` (objective), `browser_action` (single gated action),
`browser_extract` (structured extraction). They desugar to `browser.*`
tools through Tool Runtime — no parallel execution semantics. High-risk
actions return `WAITING` for the human-approval hook.

# Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `403 … denied by policy` | Domain policy or SSRF gate; check `/policies`, URL scheme/host |
| `{requiresApproval: true}` | Risk gate; resubmit with `approved: true` after human review |
| `WAITING_FOR_HUMAN` | CAPTCHA/MFA/login/bot challenge; use takeover hook, never bypass |
| Stale element errors | DOM mutated; re-ground (extract observation) and retry with semantic selector |
| `Task step budget exhausted` | Increase `max_steps` (≤500) or split the objective |
| Session `EXPIRED` | Idle >5 min or age >30 min; heartbeat long tasks, recreate session |
| `Duplicate action` | Idempotency key replay; generate a fresh key per intent |
