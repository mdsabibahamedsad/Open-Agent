# Moderation & Governance

Moderators (`marketplace:manage`, `review:manage`, `publisher:manage`, or
platform ownership) work from `/master/marketplace`: real counts (zeros
are zeros), pending-review / reports / flagged-review / advisory / revoked
queues, a generic audited action endpoint, category management, and the
platform event stream.

## Capabilities

Inspect listing + version + dependency graph (via MP22 diff/security
endpoints) -> approve / reject / suspend / revoke / restore / request
changes / flag publisher / flag package / feature / verify or suspend
publishers / hide-remove-restore reviews / triage reports. Every action
requires a reason, writes `moderation_actions` + `audit_logs`, emits an
outbox event, and notifies affected users (subject to their prefs).

## Governance extension points

`marketplace_policies.rules` is the machine-readable home for community,
publisher, security, package, review, moderation and commerce policy
evolution: allowed types/categories/licenses, risk ceilings, verification
and review requirements, blocked dependencies/permissions. Policies only
add requirements — they can never weaken platform, RBAC, org, tool,
sandbox or approval security.

## Content reporting

Packages, publishers, reviews and security issues report into
`marketplace_reports` (OPEN/INVESTIGATING/ACTION_REQUIRED/RESOLVED/
DISMISSED) plus review-specific `review_reports`. Copyright/trademark,
malicious-package, impersonation and policy-violation reasons are
first-class; resolutions record the action taken without asserting
jurisdiction-specific legal conclusions.
