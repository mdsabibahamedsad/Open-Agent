# Browser Sessions

Sessions are tenant-isolated browser contexts with lifecycle, heartbeat,
idle expiry, and leases for multi-agent coordination.

## States

`CREATED → STARTING → READY ⇄ BUSY ⇄ WAITING → PAUSED → READY → CLOSING → CLOSED`,
plus `ERROR` and `EXPIRED` (idle timeout 5 min, absolute timeout 30 min).

## Endpoints

```text
POST   /api/v1/browser/sessions
GET    /api/v1/browser/sessions
GET    /api/v1/browser/sessions/{id}
PATCH  /api/v1/browser/sessions/{id}
POST   /api/v1/browser/sessions/{id}/pause
POST   /api/v1/browser/sessions/{id}/resume
POST   /api/v1/browser/sessions/{id}/heartbeat
DELETE /api/v1/browser/sessions/{id}
GET    /api/v1/browser/sessions/{id}/pages
POST   /api/v1/browser/sessions/{id}/pages
DELETE /api/v1/browser/sessions/{id}/pages/{page_id}
GET    /api/v1/browser/sessions/{id}/events
```

Default profile is isolated/ephemeral. Persistent profiles require explicit
policy authorization (see `profiles.md`).

## Leases

`BrowserService.acquire_lease()` prevents two agents from driving the same
page simultaneously (`holder_type`: `agent` | `workflow` | `human`).
Human takeover parks the task in `WAITING_FOR_HUMAN`
(`POST /tasks/{id}/human`); MP19 consumes this hook.
