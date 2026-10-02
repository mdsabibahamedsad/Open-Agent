# Connector Testing (MP21)

## Harness (`openagent.connectors.testing`)

- `MockProviderHTTP`: scripted routes (responses, error sequences,
  exceptions), call recording, secret-leak assertions.
- `MockAuth`: capability-scoped fake credential bundles (no real secrets).
- `mock_ctx`: engine-shaped context dicts.
- `paged`: cursor fixtures for paginator tests.
- `validate_manifest_contract`: manifest + schema + trigger/limit gate.

## What every official connector tests

Manifest validity, each action (happy path + validation rejects +
unauthorized mapping + rate-limit surfacing), connection test, webhook
normalization, upload/type/size guards where applicable.

## Contract checklist

Manifest, schemas, authentication, actions, triggers, errors,
pagination, rate limits. Provider contract drift is caught by re-running
these suites — no live credentials required.

## Local development

Mock OAuth (state builders), mock APIs (harness), mock webhooks
(signature helpers), mock rate limits/errors. `scripts/connector-new.py`
scaffolds a passing manifest test for every new connector.
