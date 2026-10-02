# Guardrails (MP19)

Layers (independent; one failure never disables another): authentication,
authorization (RBAC), policy, risk, approval, rate limit, resource limit,
network security, data protection, audit.

## Precedence

`platform > organization > team > agent > workflow > tool > request`.
A child policy can only add restrictions, never weaken mandatory platform rules.

## Decisions

`ALLOW | DENY | REQUIRE_APPROVAL | REQUIRE_MULTI_APPROVAL | REQUIRE_ESCALATION`.

## Writing policies

Declarative only — no code execution. Example rule:

```json
{
  "decision": "REQUIRE_MULTI_APPROVAL",
  "when": { "environment": "production", "action_category": "DEPLOY" },
  "required_approvals": 2,
  "required_role": "organization_owner",
  "reason": "Two-person rule for production deploys"
}
```

Supported `when` keys: any `ActionContext` field (`environment`, `action_category`,
`tool_name`, `external_side_effect`, `financial_impact`, `destructive`,
`credential_usage`, `privilege_level`, `tenant_scope`, …) plus `risk_gte` /
`risk_lte` (`NONE | LOW | MEDIUM | HIGH | CRITICAL`).

## Platform baseline (always on)

- Production database deletion: `DENY`.
- Platform privilege: `REQUIRE_APPROVAL` by `platform_owner`.
- `HIGH+` risk, external side effects, financial actions, credential usage:
  `REQUIRE_APPROVAL` by `organization_owner`.

## Simulator

`POST /organizations/{id}/approvals/simulate` evaluates without executing —
use it in the Policy Testing UI before rolling out rules.
