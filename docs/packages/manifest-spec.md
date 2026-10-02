# Package Manifest Specification (`openagent-package`, format v1)

## Bundle layout

```
openagent-package/
├── manifest.json
├── resources/<kind>/<slug>.json
├── schemas/configuration.json
├── schemas/<model_requirements|memory_requirements|browser_requirements|code_requirements|evaluation>.json
├── assets/<file>                    # icons, screenshots (validated, never executables)
└── integrity.json
```

`integrity.json`:

```json
{
  "files": {
    "<relative-path>": "<sha256 hex>",
    "manifest.json#content": "<sha256 of canonical manifest>"
  },
  "manifest_hash": "<sha256 of canonical manifest>"
}
```

Canonical form: JSON with sorted keys, compact separators, UTF-8 — so hashes
reproduce across runtimes.

## Manifest fields

```json
{
  "format": "openagent-package",
  "format_version": "1",
  "package": { "id": "acme.research", "name": "Research", "version": "1.0.0", "type": "WORKFORCE" },
  "author": { "name": "Acme", "email": "", "url": "" },
  "license": "Apache-2.0",
  "visibility": "ORGANIZATION",
  "trust": "UNTRUSTED",
  "description": "...",
  "categories": ["Research"],
  "tags": ["research"],
  "icon": "",
  "dependencies": [
    { "type": "skill", "package": "web-research", "version": "^1.2.0" },
    { "type": "connector", "package": "github", "version": "^2.0.0" },
    { "type": "tool", "package": "browser-search", "version": "^1.4.0", "optional": true }
  ],
  "resources": [
    { "kind": "AGENT", "slug": "research-manager", "name": "Research Manager", "payload": { "...": "..." } }
  ],
  "configuration": {
    "inputs": {
      "company_name": { "type": "text", "required": true },
      "tone": { "type": "text", "default": "professional" },
      "notify_channel": { "type": "connector_reference", "credential_type": "slack", "required_scope": "chat:write" }
    }
  },
  "security": { "required_approvals": ["publish_content"], "network": "restricted", "sandbox_profile": "", "risk_notes": "" },
  "compatibility": { "openagent_version": ">=0.1.0", "api_version": "v1", "runtime_version": "*", "feature_requirements": [] },
  "model_requirements": {},
  "memory_requirements": {},
  "browser_requirements": {},
  "code_requirements": {},
  "evaluation": { "minimum_quality_score": 0.7, "required_checks": ["factuality"] },
  "changelog": "1.0.0: initial release."
}
```

## Types

Package/resource `type` / `kind` (extensible): `AGENT`, `AGENT_TEAM`,
`WORKFORCE`, `WORKFLOW`, `SKILL`, `PROMPT`, `TOOL_BUNDLE`,
`CONNECTOR_BUNDLE`, `MODEL_PRESET`, `AGENT_PRESET`, `WORKFLOW_PRESET`,
`MEMORY_PRESET`, `AUTOMATION_RECIPE`, `TEMPLATE_PACKAGE`.

Dependency `type`: `skill`, `prompt`, `tool`, `connector`, `model`,
`memory`, `workflow`, `agent`, `package`, `mcp`, `preset`.

## Configuration field types

`text`, `number`, `boolean`, `enum` (+`options`), `secret_reference`,
`credential_reference`, `connector_reference`, `tool_reference`,
`model_preset`, `agent_reference`, `workflow_reference`, `file`, `json`,
`array`, `object`.

Reference types store IDs only. Inline defaults on reference types are
rejected; raw secret values anywhere in a bundle block export and fail
validation with `SECRET_LEAK` (BLOCKER).

## Version constraints

Exact (`1.2.3`), caret (`^1.2.0`), tilde (`~1.2.0`), ranges
(`>=1.2.0 <2.0.0`), wildcards (`1.2.x`, `*`), unions (`^1.0.0 || ^2.0.0`).

## Compatibility

Packages declare `openagent_version` / `api_version` / `runtime_version` /
`feature_requirements`. Incompatible packages are rejected at validation
and install time — never force-installed.

## Signing

`PACKAGE_FORMAT` bundles support detached signatures:

```
canonical manifest bytes → sha256 → HMAC-SHA256 (self-hosted) or Ed25519 (publishers)
```

Official/CORE publication requires a verified signature. Verification needs
no central marketplace: any trusted key registry works.
