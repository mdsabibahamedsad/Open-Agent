# OAuth Guide (MP21)

## Connect flow

```text
Connect GitHub
  ↓  (server builds authorize URL: PKCE S256 + signed state + minimal scopes)
Provider authorization
  ↓
OpenAgent callback
  ↓  (verify state signature + freshness + connection binding; single-use code)
Exchange code (server-side, redirect-allowlisted)
  ↓
Encrypt tokens (credential row, Fernet envelope)
  ↓
Connection CONNECTED
```

Requested scopes are shown before redirect; excessive requests are
rejected. Callback hosts must be allowlisted (`OAUTH_REDIRECT_HOSTS`,
app URL implicit).

## Defenses

| Attack | Mitigation |
|---|---|
| CSRF | HMAC-signed state + `connection_id` binding + 10-min expiry |
| State fixation | Fresh nonce per flow; single-use verifier cleared pre-exchange |
| Redirect manipulation | Callback host allowlist |
| Token leakage | Server-side exchange; tokens encrypted at rest; masked everywhere |
| Code replay | Verifier cleared before exchange; replayed callbacks 409 |
| Scope creep | Manifest minimum + explicit extras only; grant validated |

## Refresh / revoke / disconnect

Refresh tokens rotate when providers rotate them; expiry surfaces as
`AUTH_EXPIRED` health. Disconnect revokes provider-side (best effort)
and always clears local state. Anomalies (refresh storms) emit
security events.
