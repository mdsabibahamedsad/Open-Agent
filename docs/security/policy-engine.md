# Policy Engine

Layered RBAC (existing) + ABAC (fixed attribute vocabulary) with
platform → org → project → environment → resource → request
precedence; restrictive wins, unknown denies. Normalized decisions
carry policy IDs, risk, and conditions. The simulator dry-runs
actor/action/resource/environment/context to ALLOW/DENY/STEP-UP with
safe explanations (no internals). Changes are versioned, audited, and
rollback requires confirmation for multi-step reverts.
