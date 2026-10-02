# Commerce (Interfaces Only — No Real Payments in This Phase)

```
Marketplace -> Product -> Price -> Billing Provider -> Entitlement -> Installation
```

The marketplace never touches card data and stores no payment secrets —
only provider references (`transaction_reference`, `provider_reference`).

## What exists

- `Product` (listing, type, pricing model, currency) + `Price`
  (integer minor units, interval, tiers) with audited, versioned changes.
- `Entitlement` (org/user, product, ACTIVE/EXPIRED/REVOKED/TRIAL,
  validity window, source). Install gating: FREE always passes; paid
  requires a live entitlement; unconfigured commerce yields an explicit
  `COMMERCE_DISABLED` (402), never silent access.
- `BillingProvider` protocol (products, prices, checkout, payment
  verification, entitlements, refunds, payouts, webhooks) with a
  `DisabledBillingProvider` default that raises instead of fabricating
  success.
- Webhook intake with HMAC verification, timestamp freshness, persisted
  replay protection and idempotency keys. Unknown/unconfigured providers
  get 503; bad signatures get 400 (counted).
- `RevenueRecord`/`Payout` rows are created only from verified billing
  events — with no provider configured they stay empty, and the UI says
  so. Revenue splits compute from explicit platform policy
  (`split_revenue`, basis points), with a zero-fee default; nothing
  permanent is hard-coded.
- Feature gates (`can_install_listing`) are separate from runtime
  authorization: entitlements never grant tool/sandbox/approval bypass.

## Deferred to MP24

Provider integrations, checkout UX, real payouts, tax handling, revenue
sharing transfers, usage metering hooks. The seams above are the
integration surface.
