# Marketplace Security

Marketplace security controls distribution; runtime security controls
execution. Neither bypasses the other (invariants 1–20 in the MP23 brief
are enforced by keeping these layers separate and tenant-scoped).

## Controls

- Authenticated, RBAC-gated endpoints (`marketplace:*`, `publisher:*`,
  `review:*` plus platform-owner gates for moderation/commerce truth).
- Tenant isolation in every query; private listings/packages 404 cross-org.
- Content sanitization: no active markup stored; only http(s) URLs with
  hosts; 20-link caps; bounded sizes. Rendered externally with
  `noopener noreferrer nofollow`.
- Security scans on submit (MP22 engine reused) + marketplace max-risk
  gate; advisories are first-class rows with affected-version specs.
- Revocation flow: listing REVOKE -> optional package-version revoke ->
  advisory -> installer/follower notify; history preserved; new installs
  blocked by the MP22 REVOKED gate; installed rows marked affected.
- Signature states shown honestly: VALID / INVALID / UNSIGNED / UNKNOWN —
  unsigned is never displayed as verified.
- Artifact pipeline: size/MIME/extension/hash/signature/manifest checks,
  traversal + zip-bomb guards; nothing downloadable before VERIFIED.
- Review/rating integrity: writer-maintained aggregates, eligibility,
  velocity + report thresholds, moderated removals with reasons.
- Billing webhooks: HMAC signature + 5-minute freshness + persisted
  replay/idempotency; unsigned or unconfigured providers rejected (counted).
- Analytics privacy: aggregated counters only; event metadata strips
  configuration/values/bodies; publisher views never expose user-level rows.
- Abuse hooks: rate limits on search/detail/install/review/report/follow/
  webhooks, pagination caps, anomaly signals (velocity, spam, report
  clustering) without surveillance.
