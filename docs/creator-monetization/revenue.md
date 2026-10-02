# Creator Monetization & Payouts

```text
Publisher → Product → Sale → Gross → Platform Fee → Adjustments
→ Creator Revenue → Payout
```

## Revenue

Immutable `marketplace_revenue` rows are created **only from verified
billing events** (`_record_sale_revenue`):

```text
Gross − Discounts − Refunds − Taxes = Net Base
Net Base − Platform Fee (bps + fixed) = Creator Net
```

Fee policy is configuration (`commerce_fee_policies`, most-specific wins:
product > publisher type > marketplace) — no hard-coded 70/30. Historical
rows are never mutated; corrections use adjustment/refund records.

## Ledger

`creator_ledger_entries` is the source of truth for balances:
`CREDIT|DEBIT|REFUND|FEE|ADJUSTMENT|PAYOUT`, immutable once `POSTED`,
idempotent keys on every entry. Balances are computed from the ledger,
never from a mutable `balance` column. Double-entry-ready (`account` +
`type` + `reference`) without claiming to be a full accounting system.

## Payouts

Lifecycle: `PENDING → ELIGIBLE → PROCESSING → PAID`, with `HELD`,
`FAILED`, `CANCELLED`. Eligibility: minimum balance, settlement window,
refund/dispute holds, publisher verification — all configurable, no
invented jurisdictional claims. `destination_reference` is a provider
handle; raw bank credentials are rejected (`RAW_CREDENTIALS`).

Master Account (`/master/billing`) can review/hold/release/reject with
every action audited. Publisher A can never see Publisher B's revenue
(membership-gated queries + tests).
