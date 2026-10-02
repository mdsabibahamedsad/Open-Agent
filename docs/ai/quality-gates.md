# Quality Gates (MP20)

Reusable bundles of required checks + thresholds + failure behavior.

## Built-ins

`code_build_gate security_gate research_quality_gate workflow_success_gate
browser_completion_gate data_validation_gate production_deployment_gate`.

## Production Deployment Gate requires

- build passes, tests pass, security scan passes, no critical issues,
  **deployment approval exists** (verified via MP19, read-only here).

All required conditions must pass. `approval_required` gates additionally
need a granted MP19 approval; the gate never grants authorization itself.

## Failure behaviors

`FAIL CORRECT RETRY ESCALATE REQUEST_HUMAN STOP` — mapped onto the
correction loop or human review. Safety hits always STOP/FAIL regardless
of scores.

## Org gates

`GET/POST/PATCH /quality-gates` (evaluation:admin). Updates bump `version`
for reproducibility. Evaluate without side effects via
`POST /quality-gates/:id/evaluate`.
