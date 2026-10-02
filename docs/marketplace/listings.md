# Listings

A listing references an MP22 package and pins published versions; it never
duplicates package identity. Listing <-> version mapping is explicit in
`marketplace_listing_versions` (one current version; no ambiguous identity).

## Lifecycle

`DRAFT -> SUBMITTED -> VALIDATING -> UNDER_REVIEW -> APPROVED -> PUBLISHED`,
with `SUSPENDED`, `DEPRECATED`, `REVOKED`, `ARCHIVED`, `REJECTED` branches.
Every transition is authorization-checked and audited; moderated targets
(APPROVE/REJECT/SUSPEND/REVOKE/PUBLISH) need `marketplace:manage` or
platform ownership.

## Publishing flow

Create listing -> attach version (+ structured changelog: added, changed,
fixed, security, breaking, dependencies, permissions) -> submit, which runs:
content sanitization, MP22 package validation (reused, never duplicated),
security scan with marketplace max-risk gate, compatibility/policy/license
checks, publisher standing check -> UNDER_REVIEW (or APPROVED when the
marketplace policy disables review) -> moderator approve -> publisher
publishes. Blocking failures return the listing to DRAFT with reasons.

## Badges

`featured`, `editorial`, `official`, `new`, `trending` are explicit labels
stored on the listing with reasons. Featured placement is rendered in a
separate labeled section — never a hidden organic-ranking boost.
