# Repositories — Providers, Connections, Credentials

## Provider abstraction

`openagent/code/providers.py` defines the `RepositoryProvider` protocol:

```python
class RepositoryProvider(Protocol):
    async def connect(...)      # validate access, read default branch
    async def list_repositories(...)  # remote listing via credential_ref
    async def get_repository(...)
    async def clone(...)        # into a workspace root (sandboxed target)
    async def fetch(...)
    async def push(...)         # policy-gated, never force by default
```

Adapters: `github`, `gitlab`, `bitbucket`, `generic` (any git remote),
`local` (server-side path, allow-listed). No GitHub-only logic in the core;
forge differences live in adapters.

## Repository entity

```text
Repository: id, organization_id, provider, external_id, name, full_name,
  clone_url, default_branch, visibility, status, created_at, updated_at
```

`status`: `connected | syncing | error | disconnected`. Tenant isolation is
enforced at the query layer (`organization_id` on every access).

## Connecting

```bash
POST /api/v1/repositories            # {provider, name, full_name, clone_url, credential_ref?}
POST /api/v1/repositories/{id}/connect
POST /api/v1/repositories/{id}/sync
POST /api/v1/repositories/remote/list  # {provider, credential_ref}
```

## Credential security

Supported: SSH credentials, personal access tokens, OAuth tokens, app
credentials, service accounts — all stored in the existing credential
system. The API accepts **only** `credential_ref` (a handle). The model
receives the ref, never the secret:

```text
model sees:  credential_ref = "cred_abc123"
server does: resolve → inject into git URL / SSH env at clone/fetch/push time
never:       raw token, private key, password, cookie in prompts, logs, events
```

`has_credential` (boolean) is the only credential fact exposed over the API.
Audit events record `repository.connected` / `repository.accessed` without
secret material. See `docs/code-agent/security.md`.
