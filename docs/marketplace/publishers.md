# Publishers

A publisher is an identity that distributes listings: `INDIVIDUAL`,
`ORGANIZATION`, `COMPANY`, `COMMUNITY` or `OPENAGENT_OFFICIAL` (platform
owners only). Profiles extend the MP22 `publisher_profiles` table; team
membership lives in `publisher_members` (OWNER/ADMIN/MEMBER, last-owner
protected).

## Verification

`UNVERIFIED -> PENDING -> VERIFIED|OFFICIAL`, with `SUSPENDED`/`REVOKED`
terminal-ish states (suspended publishers can be reinstated; revoked
cannot). Decisions require `publisher:manage` or platform ownership, are
audited, emit `PUBLISHER_VERIFIED`, and update the `verified` compatibility
flag. Verification never bypasses runtime security: verified packages are
still validated, scanned and policy-checked on every submit and install.

## Studio (`/publisher/*`)

- `packages` — reusable packages backing your listings (links to Template Center)
- `packages/new` — create a draft listing from a package + publisher
- `packages/[id]` — lifecycle (submit/publish/deprecate/revoke), version
  attach with structured changelog, analytics, event timeline
- `listings` — all listings with state filter
- `reviews` — received reviews + one authenticated response each
- `analytics` — aggregated totals + daily series (no user-level data)
- `security` — listing posture + advisories affecting you

Revenue/payout tabs stay visible only when rows exist; with no billing
provider configured they show the honest "unavailable (MP24)" note —
never fabricated numbers.
