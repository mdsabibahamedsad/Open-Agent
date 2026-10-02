# Troubleshooting

* `CLOUD_DISABLED` / 503 on `/cloud/*` → set `OPENAGENT_CLOUD_ENABLED=true`
  (or runtime mode `cloud`).
* Executions stuck `QUEUED` → check queue depth (`/cloud/queues`), worker
  heartbeats (`/cloud/workers`), region status, incident mode.
* `QUOTA_EXCEEDED` → org quotas in commerce; check `/cloud/usage`.
* `PLACEMENT_FAILED` → no compatible capacity: check worker
  capabilities/region/residency vs request.
* Duplicate executions → verify `Idempotency-Key` reuse and schedule
  dedup keys; inspect `schedule_dedup`.
* Worker `UNHEALTHY` → heartbeat TTL vs network; sweep recovers claims.
* Artifact 404 after upload → storage backend mismatch or checksum
  failure (see quarantined artifacts).
* Stream stalls → bounded buffers drop oldest; resubscribe with
  `from_sequence` cursor.
