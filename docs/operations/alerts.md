# Alerts

Rules are data (`metric`, `condition: gt|lt|eq`, `threshold`,
`duration`, `severity`, `destinations`) — conditions are never code.
`AlertEngine` fires once per rule+source (dedup key), auto-resolves on
clear, supports acknowledge. Covered signals: queue overload, worker
failure, region degradation, DB latency, storage failure, execution/API
failure spikes, auth-attack spikes, quota abuse, unusual consumption.
Destinations are provider-neutral (`Notifier`); real delivery reuses the
Connector framework. UI builder at `/operations/alerts`; alerting
outages degrade to local recording and never break execution.
