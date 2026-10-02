# Custom Connectors (MP21)

Two paths, both declarative:

## 1. UI builder (`/integrations/builder`)

Base URL (https only, private hosts blocked) + auth type + endpoints
(method + path). Mutations default to HIGH risk; registration validates
the manifest server-side. Execution uses the generic HTTP executor —
no custom code.

## 2. Manifest registration (`POST /connectors`)

Full control: capabilities, actions with JSON schemas, triggers
(webhook/polling), resources, rate limits, custom verification defs
(evaluated post-mutation via MP20).

```json
{
  "connector": "acme_crm",
  "version": "1.0.0",
  "capabilities": [],
  "credential": null
}
```

Export omits secrets; reconnect after import.

## Generic execution model

`{method, path_template, query_params, extract}` per action. Path params
are allowlisted, length-capped, traversal-rejected, URL-encoded. Bodies
are validated against the action schema before send. Unknown custom
mutations stay HIGH risk until policy explicitly classifies them safer —
custom APIs are never assumed safe.
