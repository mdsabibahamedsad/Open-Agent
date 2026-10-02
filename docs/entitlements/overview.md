# Entitlements

Commercial access only — never a security permission.

## Flow

```text
Payment / Subscription → Entitlement → has_access(subject, feature) → install / feature use
```

`entitlements.has_access(subject, feature)` checks live status, validity
window, subject match, and quantity (`used < quantity`). It does NOT bypass
authentication, RBAC, tool permissions, sandbox policies, human approval,
or organization policy — those enforce independently downstream.

## Model

`commerce_entitlements`: subject (user/org) · product · feature(s) ·
source (`PURCHASE|SUBSCRIPTION|GRANT|PROMOTION|ENTERPRISE|ADMIN|TRIAL`) ·
status (`PENDING|ACTIVE|EXPIRED|REVOKED|SUSPENDED`) · validity window ·
quantity/used · `inherited` (org→member only when explicit).

Paid marketplace installs dual-write to `marketplace_entitlements` (MP23
gate) in the same transaction.

## Rules

- Free packages install with no billing (`OK_FREE`).
- Paid packages without a provider return `COMMERCE_DISABLED` — never
  silently free, never silently granted.
- `GRANT`/`ADMIN` sources are manual; `PURCHASE`/`SUBSCRIPTION` sources can
  only be created from verified payment events (the API rejects forged
  sources with `FORGED_SOURCE`).
- Refunds revoke the install grant created by that payment (history kept).
- Package revocation blocks new installs, preserves purchase history, and
  never auto-refunds without configured policy.
- Commercial entitlement attaches to the **product**, not a single package
  artifact, so v1→v2→v3 keep working unless the product says otherwise.
