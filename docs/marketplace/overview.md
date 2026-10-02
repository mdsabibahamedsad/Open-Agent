# OpenAgent Marketplace — Overview

The marketplace distributes and manages reusable AI workforce packages. It
never executes packages: installs delegate to the MP22 installer and
execution stays in the runtime systems (Agent Runtime, Workflow Engine,
Tool Runtime, Sandbox, approvals).

## Layering

```
OpenAgent Core
  -> Package System (MP22: definitions, versions, validation, install)
    -> Marketplace Registry (this phase: publishers, listings, trust config)
      -> Marketplace Catalog (discovery: search, categories, featured)
        -> Distribution (artifacts: content-addressed, verified, signed)
          -> Commerce Layer (products, prices, entitlements, billing seam)
```

Core works without any marketplace. A self-hosted deployment gets the
default public marketplace row plus a local registry and can import,
browse, install, update and export fully offline.

## User journey

DISCOVER (`/marketplace`, `/marketplace/search`, categories) -> UNDERSTAND
(listing detail: resources, requirements, compatibility) -> INSPECT SECURITY
(scan report, signature, advisories, health) -> INSTALL (entitlement gate,
MP22 wizard semantics) -> CONFIGURE -> RUN (runtimes) -> REVIEW
(verified-use preferred) -> UPDATE (changelog, permission diffs) -> SHARE
(favorite, follow, report).

## Creator journey

BUILD (MP22 package) -> PACKAGE (manifest) -> VALIDATE (MP22 engine, reused)
-> SECURITY CHECK (scan + policy) -> PUBLISH (listing lifecycle with review)
-> DISTRIBUTE (verified artifacts) -> GROW (analytics, reviews, follows) ->
MONETIZE (products/entitlements; billing providers plug in at MP24).

## Key invariants

- Private listings never appear in public search (tenant isolation in SQL).
- Revoked versions cannot be newly installed (MP22 installer gate).
- Invalid artifacts cannot install (hash + archive verification first).
- Publishers cannot edit rating aggregates (writer-maintained only).
- Moderation requires `marketplace:manage`/`review:manage` or platform
  ownership, and every action is audited.
- Billing webhooks must be signed, fresh and idempotent; unsigned events
  are rejected and counted.
- No fake metrics: counts start at zero and only move on real events.

## Extension points (MP24)

Cloud registry, CDN sync, billing providers (Stripe-style), payouts,
private-registry mirroring, semantic search providers. All seams exist as
protocols with honest `disabled` defaults — no fake payments, no invented
transactions.
