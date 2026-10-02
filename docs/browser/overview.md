# Browser Engine — Overview

OpenAgent's Browser Engine lets agents and workflows interact with real
websites through controlled, policy-gated browser sessions.

```text
Agent / Workflow
      ↓
Browser Tool (browser.* via Tool Runtime)
      ↓
Browser Task Manager (persistent tasks, budgets, recovery)
      ↓
Browser Session Manager (tenant-isolated sessions, leases)
      ↓
Playwright Adapter (provider-neutral interface)
      ↓
Chromium
      ↓
Website (UNTRUSTED)
```

## Invariants

1. Browser actions cannot bypass Tool Runtime (`browser.*` tools).
2. Browser actions cannot bypass RBAC or organization isolation.
3. Webpage content is **untrusted** and can never override system/security policy.
4. Credentials never enter model prompts — only `credential_ref` handles,
   resolved server-side via the existing credential system.
5. Unsafe navigation (SSRF, localhost, private IPs, cloud metadata,
   `file:`/`javascript:`/`data:` schemes) is blocked fail-closed.
6. High-risk actions expose risk metadata + approval hooks (`WAITING_FOR_HUMAN`).
7. Crashes never trigger silent replay of non-idempotent actions.

## Components

| Area | Python (API) | TypeScript (`@openagent/browser`) |
|---|---|---|
| Sessions/pages/tasks | `openagent/browser/service.py` | `session/manager.ts`, `tasks/manager.ts` |
| Provider | worker-driven Playwright | `providers/playwright.ts` (+`types.ts`) |
| URL/SSRF gates | `openagent/browser/security.py` | `security/url-validator.ts` |
| Redaction/injection | `security.py` | `security/hardening.ts` |
| Observation budgets | `observations.py` | `observation/compression.ts`, `extraction/dom.ts` |
| Tool Runtime | `browser/tools.py` (`BROWSER_TOOLS`) | `api/tool-adapter.ts` |
| Workflow nodes | `runtime/executors/nodes/browser.py` | — |
| OCR/visual grounding | hooks (noop default) | `vision/providers.ts` |
| Research | evidence-first flow | `research/service.ts` |
| Artifacts/metrics | `browser_artifacts` table | `artifacts/store.ts`, `metrics/telemetry.ts` |
| SDK | `packages/sdk` (Python) | `sdk/client.ts` |

## API

Base: `/api/v1/browser` — see `docs/browser/sessions.md`, `actions.md`,
`profiles.md`, `research.md`, `agent.md`, `workflows.md`, `security.md`,
`troubleshooting.md`. Frontend: `/browser` workspace, `/browser/playground`.

## Local development

```bash
docker compose up            # postgres, redis, api, worker, web
# Playwright/Chromium for real driving:
pnpm --filter @openagent/browser exec playwright install chromium
```

Run the smoke test without a browser (policy gates + task state machine):

```bash
pytest apps/api/tests/test_browser_security.py \
       apps/api/tests/test_browser_tools.py \
       apps/api/tests/test_browser_api.py
```
