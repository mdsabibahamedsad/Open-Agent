# Payout Operations

Creator-facing: `/publisher/revenue` (overview, transactions, fees,
refunds, balance, payouts). Buyer-facing: `/settings/billing` (plan,
usage, subscriptions, invoices, payments, entitlements, credits).

## Requesting a payout

`POST /payouts` with a decimal-string amount (`"25.00"` — never float)
and a provider destination handle. The API checks ledger balance,
minimum, and holds before creating a `PENDING` payout.

## Lifecycle

- `PENDING` → `ELIGIBLE`: worker sweep (`commerce.sweep_payouts`) when the
  ledger covers the amount.
- `ELIGIBLE` → `PROCESSING`: executes the provider payout (mock in dev).
- `PROCESSING` → `PAID`: posts the `PAYOUT` ledger debit.
- Any hold: `→ HELD` with `hold_reason` (refund, dispute, verification,
  settlement rule). `HELD` → `ELIGIBLE` on release.
- `FAILED` → `ELIGIBLE` retry or `CANCELLED`.

Every transition writes a `commerce_payout_events` row and an audit log.
