# Webhooks (MP21)

## Inbound routing

```http
POST /api/v1/webhooks/:connector/:connection/:endpoint
```

The route alone proves nothing: the handler resolves the registered,
tenant-scoped, active endpoint row first, then verifies the signature
(HMAC-SHA256, GitHub/Slack/Stripe/Telegram schemes), timestamp tolerance
(5 min), and delivery-ID dedupe (memory + persisted). Failures increment
counters and emit security events; filtered events still ack (no retry
storms).

## Endpoint management

Create returns the secret **once** (hash + prefix stored; encrypted copy
bound to the webhook id enables HMAC verification). Rotate/revoke/delete
from the connection page. Secrets never appear in list/detail responses.

## Normalization

Provider events become:

```json
{
  "event_type": "pull_request.created",
  "provider": "github",
  "resource_id": "...",
  "timestamp": "...",
  "payload_reference": "..."
}
```

Raw payloads are referenced, not stored, unless retention policy allows.
Normalized events publish to the existing event bus (`connector.*`),
which triggers workflows, agents, and tools — no second event bus.

## Polling alternative

Providers without webhooks use `PollingTrigger` cursors (interval ≥ 60s
configurable, dedupe by id, backoff on empty/error, rate-limit aware).
Bounded per cycle; no uncontrolled loops.
