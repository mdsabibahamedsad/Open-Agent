# Billing Providers

Provider-neutral seam: `openagent.commerce.providers.BillingProvider`.

## Modes

| `BILLING_MODE` | Behavior |
|---|---|
| `disabled` (default) | Paid operations raise `COMMERCE_DISABLED`. Free flows work. |
| `mock` | Deterministic `MockBillingProvider` for local dev/tests. Every id is `*_test_*`, every event carries `test_mode: true`. Never a real payment. |
| `live` | Requires `BILLING_PROVIDER` + `BILLING_WEBHOOK_SECRET`; startup fails closed without them. No adapter is bundled — implement `BillingProvider` for Stripe/Paddle/etc. |

## Security rules

- Provider-hosted checkout only. OpenAgent never sees card numbers.
- Store only provider references (`provider_customer_id`,
  `provider_subscription_id`, `provider_invoice_id`).
- Never mark checkout successful from frontend input — only the verified
  webhook path (`_apply_payment_succeeded`) completes checkouts.
- Webhooks: HMAC-SHA256 signature + timestamp window (default 300s) +
  persisted `event_id` replay protection + deterministic idempotency keys.
  Unsigned webhooks are rejected with `WEBHOOK_UNVERIFIED`.
- Retry: failures persist `retry_count`/`last_error`; rows stuck after 5
  attempts are flagged `dead_letter` for operators.

## Money

Integer minor units everywhere (`money.py`). `parse_amount("9.99", "USD")`
→ `999`. Floats are rejected. JPY-style zero-decimal currencies supported
via `CURRENCY_EXPONENTS`.

## Local development

```bash
BILLING_MODE=mock
BILLING_WEBHOOK_SECRET=mock-secret
```

Drive deterministic events through `MockBillingProvider.mock_event()` +
signed test webhooks (see `tests/test_commerce_security.py`).
