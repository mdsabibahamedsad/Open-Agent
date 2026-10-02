# OpenAgent Control Plane Architecture (Master Prompt 26)

## 1. What existed before this phase

* **Execution plane (MP25)**: `openagent/cloud/` — dispatcher, queues
  (Redis/in-memory), worker fleet + leases, scheduler tick, placement +
  residency, object storage, artifacts, event streams, usage staging into
  commerce billing. Health endpoint + incident mode already existed.
* **Platform**: auth/sessions, Master Account (`platform_owners`),
  RBAC + teams, audit logs, security events, metrics collector,
  correlation middleware, API keys, service accounts, connectors with
  SSRF guard, sandbox profiles, approval/evaluator policies, commerce
  billing/entitlements/quotas.
* **Gaps this phase closes**: no unified resource model, no layered
  configuration, no policy resolution interface, no flag platform, no
  alerting/incident/deploy tracking, no SLI/SLO, no operation locks,
  no enterprise controls (IP, rotation, private enrollment), no
  diagnostics/support bundles, no runbooks.

## 2. Control plane vs execution plane

The control plane decides **what may run, where, who may run it, how
much may run, whether infra is healthy, what happened, what is
consumed, how incidents are handled**. It never executes workflows,
agents, tools, or host commands. Enforcement lives in `openagent/
control/` (pure logic) + `db/models/control.py` + `api/v1/operations|
platform|enterprise`.

## 3. Module map

| Module | Responsibility | Reuses |
|---|---|---|
| `resources` | unified refs, hierarchy, inheritance paths | RBAC (enforcement) |
| `configuration` | layered config, restrictive-wins, versions, preview/dry-run | — |
| `policies` | chain existing engines, normalized decisions, env isolation | RBAC, sandbox, connectors, approvals, entitlements |
| `feature_flags` | scoped flags, deterministic rollout, kill switches, security guard | — |
| `observability` | correlation, redacted logs, metric catalog, OTel spans, events, SLI/budget | metrics collector, correlation middleware |
| `reliability` | health, alerts+notifiers, incidents, maintenance, deployments, rollback checks, reconcile/controllers, op locks | cloud leases (pattern), events |
| `enterprise` | IP policy, sessions, keys, rotation, classification, retention floors, presets, private enrollment, abuse signals, compliance hooks | ApiKey/ServiceAccount models, audit |
| `privileged` | risk classification, step-up, tamper-evident audit chain | platform_owners, audit_logs |
| `diagnostics` | checks, support bundles, permission-scoped exports | — |
| `service` | facade (`get_control_service`) | — |

## 4. Data flow

```text
Request (request_id/trace) → RBAC → control checks (policy/flags/quota)
→ execution plane (MP25) → telemetry (metrics/spans/events, redacted)
→ alerts → incidents → audit → ops UI / status page
```

## 5. Failure semantics

Telemetry/alerter/metrics failures degrade to no-ops; execution never
depends on observability. Audit failure on critical ops fails safe
(configurable fail-open only for non-critical). Control restart holds
no phantom state (verified by test).

## 6. Security boundaries

Master Account = platform identity + step-up + audit (never a plain
admin role). Tenant isolation at every layer. Flags cannot weaken
security. Kill switches/containment are scoped, audited, reversible —
never arbitrary execution. Frontend authZ is never trusted; all checks
are server-side.

## 7. Self-hosting

All control logic runs without cloud services. Diagnostics, health,
incidents, flags, and audit work on Docker Compose defaults.
