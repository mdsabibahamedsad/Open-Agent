# Browser Profiles

Profiles own persistent browser state (cookies, localStorage).

- Types: `EPHEMERAL` (default) | `PERSISTENT` | `SHARED` | `ORGANIZATION` | `USER`
- `POST /api/v1/browser/profiles` — non-ephemeral types require `policy`;
  without it creation is rejected.
- `storage_state` is server-side only: never in prompts, logs, screenshots
  metadata, or workflow JSON. Rotation happens through a dedicated flow
  (storage state cannot be patched via the generic profile update).
- Retention is conservative and configurable; deletion is secure.

Endpoints: `GET/POST /profiles`, `GET/PATCH/DELETE /profiles/{id}`.
