# Incidents

Lifecycle `DETECTED → ACKNOWLEDGED → INVESTIGATING → MITIGATING →
MONITORING → RESOLVED → CLOSED` with validated transitions and an
**append-only** timeline (every state change writes an event).
Incidents carry severity, affected services/regions, responders,
actions, resolution, postmortem ref. Command views: org (`/operations/
incidents`) and cross-org Master console (`/master/control/incidents`).
Maintenance windows mark expected behavior; the status page maps health
to operational/degraded/outage/maintenance without leaking internals.
