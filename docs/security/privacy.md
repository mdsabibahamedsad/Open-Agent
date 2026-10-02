# Privacy (Self-Hosted Deployments)

## What OpenAgent stores

- **Identity & access:** users, organizations, memberships, roles, API keys
  (hashes), OAuth grants. Passwords are bcrypt-hashed, never stored raw.
- **Work product:** agents, workflows, runs, execution logs, approvals,
  evaluations, memory entries, artifacts, marketplace packages.
- **Credentials:** provider API keys and connector tokens, encrypted with
  `ENCRYPTION_KEY`; referenced as `credential_ref` handles, never embedded
  in prompts, logs, or events.
- **Operational data:** audit log (security-relevant events), worker
  heartbeats, queue metadata, platform health.

## AI provider data flow

Prompts and retrieved context are sent to whichever model provider the
operator configures — cloud vendors receive prompt content by definition.
Use Ollama or another self-hosted endpoint when prompts must not leave the
building. There is no separate “training opt-out” inside OpenAgent; that
contract is between the operator and their provider.

## External integrations

Connectors transmit only what the workflow requests under the granted OAuth
scopes. Private-network egress is blocked by default. Review granted scopes
per connection; revoke in the provider console to cut access immediately.

## Telemetry

No telemetry leaves the deployment unless the operator configures it
(`SENTRY_DSN`, `OTEL_EXPORTER_OTLP_ENDPOINT`, `OPS_ALERT_WEBHOOKS`).
Defaults are fully local.

## Retention & deletion

Retention merges organization policy over unbypassable platform minimums
(audit data cannot be silently shortened). Deleting an organization removes
its work product per the documented retention rules; backups age out on the
operator's backup schedule — account for that in deletion requests.

## Operator responsibility

Self-hosting means **you** are the data controller for your users:
transport security, backup encryption, access to the host, and provider
contracts are yours. No compliance certifications (SOC 2, HIPAA, ISO 27001)
are claimed — see `SECURITY.md`.
