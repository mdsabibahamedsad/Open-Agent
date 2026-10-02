# Connector SDK (MP21)

`@openagent/connector-sdk` lets third parties build connectors without
touching core: `Core → SDK → Connector Package`.

```ts
import { validateManifest, scaffoldConnector, compactAction } from '@openagent/connector-sdk';

const manifest = validateManifest(require('./manifest.json'));
const files = scaffoldConnector('acme_crm', 'Acme CRM');
```

## Package layout

```text
connectors/
└── acme/
    ├── manifest.json
    ├── auth.py
    ├── client.py
    ├── actions/
    ├── triggers/
    ├── schemas/
    ├── tests/
    └── README.md
```

Or generate it: `python scripts/connector-new.py acme_crm "Acme CRM"`.

## Rules for contributors

1. Manifests are data: no code execution, no privileged types.
2. Use the shared HTTP stack (SSRF, retries, pooling, error mapping).
3. Declare least-privilege capabilities; mutations need verification defs.
4. Tests on `ConnectorTestHarness` (mock provider/auth/webhooks/limits).
5. Document auth, actions, triggers, limits, security notes.
6. Never request secrets in schemas; use `credential_id` references.
7. Versions are immutable; pin behavior; provide migration notes.

Marketplace metadata (publisher, license, version, signature, trust) is
collected now; commerce comes later.
