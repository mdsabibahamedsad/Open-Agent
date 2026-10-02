# Connector Authentication (MP21)

## Supported mechanisms

OAuth 2.0 (auth-code + PKCE, refresh, revocation), API keys, Basic auth,
JWT, service accounts, custom headers — always through credential
references, never raw material in tool calls, logs, or model context.

## Credential lifecycle

Create (encrypted envelope, Fernet/HKDF over `ENCRYPTION_KEY`, bound to
credential id) → attach to connection → test → rotate → revoke → delete
(ciphertext wiped first). List endpoints return masked metadata only.

Rules:

- Never store plaintext secrets; never log `Authorization` headers.
- Models receive `credential_id` handles, never values.
- OAuth client secrets live server-side (`client_secret_ref`); the browser
  flow only ever sees the authorization URL + state.
- Expiry is tracked (`expires_at`); refresh is attempted once, then
  `AUTH_EXPIRED` surfaces instead of silent failure.
- Service identities (`OpenAgent Production Bot`) use granular connector
  permissions — never a user's personal credentials.

## Scope discipline

Manifests declare minimal scopes; connect flows show them before
redirect; extras require explicit user action. `>64` scopes rejected.
