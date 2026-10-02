# Service Identities

Service accounts, API clients, and platform identities carry
minimal scopes, environment binding, expiry, rotation, last-used tracking,
and audit. API keys never exceed owner privileges unless explicitly
configured; raw values shown once. SCIM and worker credentials are
separate kinds with their own revocation paths. Least privilege is
enforced at issuance (subset checks), not just at use.
