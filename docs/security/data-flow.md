# Data Flow

Where user data travels in a self-hosted OpenAgent deployment, and where it
can leave the operator's infrastructure. Read with `SECURITY.md` and
`docs/security/privacy.md`.

```text
User (browser)
  ↓ HTTPS (terminated at operator's reverse proxy)
OpenAgent Web (Next.js)
  ↓ HTTPS, Bearer auth (API key / session)
OpenAgent API (FastAPI, /api/v1)
  ├→ PostgreSQL ── agents, workflows, runs, memory, credentials (encrypted),
  │                 audit log, marketplace data. Stays on operator infra.
  ├→ Redis ── queues, worker heartbeats/leases, cache. Ephemeral job state.
  ├→ Object storage (MinIO/S3/R2/filesystem-dev) ── execution artifacts,
  │   uploads. Operator-controlled bucket.
  ├→ Agent / Workflow Runtime ── orchestration state in PG + Redis.
  │     ├→ Model Provider ── prompts + retrieved context LEAVE operator
  │     │   infra to OpenAI/Anthropic/Google/… (cloud models) or stay local
  │     │   (Ollama/self-hosted endpoint). Operator chooses per deployment.
  │     ├→ Tool / Connector / MCP ── data goes to the connected external
  │     │   service (Gmail, Slack, GitHub, …) under that connection's OAuth
  │     │   scopes. OAuth tokens stored encrypted; sent only to the provider.
  │     ├→ Browser agent ── navigates the public web on the user's behalf;
  │     │   page content returns into the run context (and possibly memory).
  │     └→ Sandbox (Docker, NO_NETWORK default) ── untrusted code executes
  │         isolated; only declared artifacts leave, via scanned storage refs.
  └→ Optional telemetry ── Sentry/OTel/webhooks ONLY if operator configures
      SENTRY_DSN / OTEL_EXPORTER_OTLP_ENDPOINT / OPS_ALERT_WEBHOOKS. Default:
      nothing leaves except the operator's own configured model providers
      and connectors.
```

## Boundary summary

| Boundary                 | Control                                                                                                                         |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------------------- |
| Browser ↔ Web/API        | TLS at operator proxy; secure cookies in production                                                                             |
| API ↔ Model providers    | Operator-selected; keys in encrypted credential store, never in logs (redaction engine)                                         |
| API ↔ External services  | Per-connection OAuth/API-key scopes; private-egress blocked by default (`CONNECTOR_ALLOW_PRIVATE_EGRESS=false`, HTTPS required) |
| Untrusted code → host    | Denied: Docker isolation, no socket, no privs, read-only rootfs, secret refs only                                               |
| Logs/telemetry/artifacts | Secret redaction precedes all three; retention per org policy over platform minimums                                            |

Secrets, tokens, and private keys never enter model context, logs, or events
(enforced by the DLP/redaction engine — see `docs/security/data-protection.md`
and the key-management docs).
