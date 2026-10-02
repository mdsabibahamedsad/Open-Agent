# Private & Enterprise Marketplaces

Organizations create private marketplaces (`ORGANIZATION_MARKETPLACE`,
`TEAM_MARKETPLACE`, `PRIVATE_MARKETPLACE`, `LOCAL_CATALOG`) with an owner
org; listings inside inherit tenant isolation — public search can never
return them, and cross-org reads 404.

## Enterprise extension points (no SSO/SCIM built here)

- `marketplace_policies.rules` — allowlists/denylists per package type,
  category, license, dependency and permission, plus verification/review
  requirements and risk ceilings.
- Private publishers (org-bound profiles + member roles).
- Internal approval: review-required policies route every submit through
  `marketplace:manage` moderators before anything is visible.
- Audit: every lifecycle/moderation/pricing/entitlement/payout change
  writes `audit_logs` rows; moderation additionally writes
  `moderation_actions`.
- Deployment controls: marketplaces carry `configuration` (allowed orgs,
  teams, install policies) evaluated at install time alongside org policy.

Enterprise SSO/SCIM, if adopted later, plugs into the existing auth/RBAC
layer — the marketplace only consumes `AuthorizationContext` and platform
ownership, it never implements identity itself.
