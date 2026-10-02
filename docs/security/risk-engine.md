# Risk Engine (MP19)

Deterministic, explainable, dependency-free (`evaluate_risk(ctx)`).

## Levels

`NONE (0) | LOW (1–39) | MEDIUM (40–69) | HIGH (70–89) | CRITICAL (90–100)`.

## Signals

Action type/category, target + environment, data sensitivity, external side
effects, financial impact, destructive potential, credential usage, network
access, privilege level, tenant scope, production environment, reversibility,
affected resources, agent/tool/MCP trust (platform-assigned, never
model-assigned), sandbox profile, org policy floor.

## Conservative floors

Category minimums (`HIGH_RISK_DEFAULTS`), unknown categories (`HIGH+`),
unknown tool origins (`HIGH+`), low trust escalating above the floor.

## Output

```json
{
  "risk_level": "HIGH",
  "risk_score": 82,
  "reasons": ["Production environment", "Destructive operation", "External side effect"]
}
```

Only structured safety reasons are exposed — never model chain-of-thought.
