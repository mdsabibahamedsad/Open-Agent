# Commerce Architecture (MP24)

Commercial infrastructure underneath OpenAgent. Layers are strict:

```text
OPEN SOURCE → PACKAGE → MARKETPLACE → PRODUCT → PRICE → CHECKOUT
→ PAYMENT → ENTITLEMENT → INSTALLATION → USAGE → REVENUE → CREATOR → PAYOUT
```

## Separation of concerns

| Concept | Answers | Lives in |
|---|---|---|
| Package | what can be installed | `packages/` + `reusable_packages` |
| Listing | how it is presented | `marketplace/` + `marketplace_listings` |
| Product | what is sold | `commerce/` + `marketplace_products` |
| Price | what it costs | `commerce/` + `marketplace_prices` |
| Payment | what was paid (verified) | `commerce/` + `billing_payments` |
| Entitlement | commercial access | `commerce/` + `commerce_entitlements` |
| Installation | tenant materialization | `packages/installer` |
| Usage | what was consumed | `commerce/` + `usage_records` |
| Revenue | creator earnings | `commerce/` + `marketplace_revenue` + `creator_ledger_entries` |
| Payout | money movement | `commerce/` + `commerce_payouts` |

Billing never executes agents. Entitlements never grant security
permissions. Marketplace distributes capabilities; runtime executes them;
security controls them; billing controls commercial access.

## Self-hosted guarantee

`BILLING_MODE=disabled` (default): everything works — local registry, free
packages, offline install. Paid operations return `COMMERCE_DISABLED`
instead of fabricating success.
