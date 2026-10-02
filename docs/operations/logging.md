# Logging

Structured records via `log_event(service, event, **fields)`:
timestamp, level, service, event + full correlation context, redacted
**before** persistence. Never logged: passwords, tokens, API keys,
cookies, auth headers, secret env vars, raw credentials, private keys.
Central patterns live in `control/observability.redact` (key + value
patterns); reuse it everywhere instead of inventing local redaction.
