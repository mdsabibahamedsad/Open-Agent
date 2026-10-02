# Connectors (MP21)

## Concepts

- **Connector**: versioned definition (manifest) — e.g. `github@1.0.0`.
- **Connection**: tenant-scoped instance bound to a credential reference.
- **Capability**: granular permission (`github.issues.write`) for least privilege.
- **Action**: typed operation with JSON schemas, risk level, idempotency flags.
- **Trigger**: webhook / polling / schedule / event / manual activation.
- **Resource**: normalized external object (user, message, file, …).

## Lifecycle

Definitions: `DRAFT → ACTIVE ⇄ DISABLED → DEPRECATED`.
Instances: `UNCONNECTED → CONNECTING → CONNECTED ⇄ DEGRADED → …`.

## Scopes and sharing

Definitions are catalog-global; **instances are always tenant-scoped**
(`PLATFORM | ORGANIZATION | TEAM | USER | WORKFLOW | AGENT`). Sharing
policies (`PRIVATE | TEAM | ORGANIZATION | WORKFLOW_ONLY`) default to
`PRIVATE` — personal credentials are never globally accessible.

## Trust tiers

`CORE > VERIFIED > ORGANIZATION > COMMUNITY / CUSTOM > UNTRUSTED`.
Trust influences installation (community opt-in), permissions, network
posture, credential access, and approval requirements. Trust never grants
capabilities by itself.

## Versioning

Manifests are content-hashed; versions are immutable snapshots. Workflows
pin `connector@version`, so connector updates never silently change
workflow behavior. Export omits secrets (`"credential": null`) —
reconnect after import.

## Writing a connector

```bash
python scripts/connector-new.py acme_crm "Acme CRM"
```

Then fill `manifest.json`, protocol code (using the shared HTTP stack —
never your own), actions, triggers, schemas, tests on
`ConnectorTestHarness`, and README. Register via
`POST /connectors` (`connector:admin`); privileged types
(`OFFICIAL`, `INTERNAL`) cannot be self-registered.
