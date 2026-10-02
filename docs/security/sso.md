# SSO

Org admins configure IdPs (type, issuer, client ID, secret *reference*,
metadata, certs, domains, attribute/group mapping, status). Flow:
choose provider → metadata → verify domain (DNS TXT/file challenge)
→ test (preview identity/role/teams, no changes) → enable (requires a
verified domain) — never lock out: local auth remains. Domain routing
only fires for verified domains; one verified domain per org; JIT
provisions membership + default role/teams, never owner via claims.
