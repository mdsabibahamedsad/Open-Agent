# Sandbox — Credential Security

## Flow

```text
Credential Reference (API: {"credential_refs": {"GITHUB_TOKEN": "cred_…"}})
      ↓ authorization (resolver)
Sandbox Credential Adapter (server-side resolve)
      ↓
Temporary Runtime Secret (container env only)
      ↓ execution
Credential removed (revocation event; nothing persisted)
```

## Rules

- The API **never accepts raw secret values** — refs only.
- The model receives the ref, never the value (value never enters
  prompts, tools args echo, logs, events, telemetry, artifacts).
- Base env is minimal and fixed; host env never inherited. `ALLOW` only
  whitelists non-sensitive names; `FORBIDDEN_ENV_NAMES` can never be
  plain values or inherited.
- Secrets are minimum-scope and short-lived; resolution failures deny.
- Redaction reuses the canonical `redact_text/redact_dict` (no second
  implementation) on stdout/stderr/tails/refs/events/audit/errors.
- Injection requires a configured, authorized resolver
  (`SandboxManager(credential_resolver=…)`); otherwise credentialed
  execution is denied — never silently run without the secret.

## Operator setup

Wire the platform credential store as the resolver (decrypt server-side,
enforce org scope + expiry), e.g. alongside the Code Agent's
`credential_resolver`. Test the negative: unconfigured resolver +
`credential_refs` must yield `POLICY_DENIED`, and output containing a
canary secret must arrive redacted in tails, refs, and events.
