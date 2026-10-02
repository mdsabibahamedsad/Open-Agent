# Usage Metering & Quotas

```text
Raw Event → Usage Aggregator → Usage Summary → Invoice/Billing
```

## Meters

Seeded: `agent_runs`, `workflow_runs`, `tokens`, `browser_minutes`,
`sandbox_seconds`, `storage_gb`, `api_requests`. Aggregation per meter:
`SUM|COUNT|MAX|UNIQUE|DURATION`. Raw `usage_records` are append-only and
idempotent (`idempotency_key`); the worker (queue `commerce`,
`commerce.aggregate_usage`) rolls them into `usage_summaries` — totals are
never recomputed from raw events per request.

## Quotas

`Entitlement → Usage → Quota` are separate concepts. Example: entitlement
“AI Pro” + quota “1000 workflow runs/month”. `quota.check` is cheap and
cache-friendly; `quota.consume` is transactional (`SELECT … FOR UPDATE`),
idempotent-safe, and auditable. Overage (`INCLUDED + OVERAGE`) is computed
but never auto-charged without explicit product configuration.

## Credits

Optional `credit_accounts` / `credit_transactions` (append-only):
`GRANT|PURCHASE|CONSUME|REFUND|EXPIRE|ADJUSTMENT` with deterministic
`expires_at`. Balances derive from transactions. Credits never bypass
entitlement/security rules.
