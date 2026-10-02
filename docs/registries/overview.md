# Registries

Provider-neutral: `RegistryClient → RegistryProvider → metadata →
artifact → integrity → signature → installation`.

## Types

`LOCAL|PUBLIC|PRIVATE|ORGANIZATION|ENTERPRISE|GIT|OBJECT_STORAGE|CLOUD`.
The public registry URL comes from `PUBLIC_REGISTRY_URL` — no hard-coded
domain.

## Trust

`CORE|OFFICIAL|VERIFIED|ORGANIZATION|COMMUNITY|UNKNOWN|UNTRUSTED`. Trust
drives install warnings and signature requirements, never security
bypasses. Nothing is implicitly trusted.

## Auth

`PUBLIC|API_KEY|OAUTH|SERVICE_ACCOUNT|SIGNED_REQUEST|PRIVATE_NETWORK`.
Non-public registries bind a `credential_ref` (existing credential
system); plaintext secrets in registry config are rejected at validation.

## Offline & mirrors

- Offline: downloaded artifacts + `commerce_registry_cache` (TTL, SHA-256,
  registry identity) → local registry → offline install. No cloud needed.
- Mirrors: `mirror_of` chains + `commerce_registry_syncs` track metadata /
  version / advisory freshness. No CDN build-out in this phase.
- Private registries are org-scoped in listings; `list_visible_registries`
  never exposes other orgs' private endpoints.
