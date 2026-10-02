# Backup & restore (self-hosted)

OpenAgent does not provision managed backups itself — there is no cloud
backup service to "just enable". For self-hosted deployments, back up the
three stateful layers below. The control plane tracks backup reports and
**measured** RPO/RTO (see [disaster recovery](./disaster-recovery.md));
never claim an RPO/RTO you have not measured with a restore test.

## 1. PostgreSQL (system of record — the one you must not lose)

```bash
# Nightly logical backup (example; schedule with cron / systemd timer)
pg_dump "postgresql://openagent:<password>@localhost:5432/openagent" \
  -Fc -f "/backups/openagent-$(date +%F).dump"

# Restore to an isolated database and verify — never test against prod
pg_restore -d openagent_restore_test /backups/openagent-<date>.dump
# then: alembic heads match, row counts sane, app boots against it
```

- Retain per your policy (suggested starting point: 7 daily + 4 weekly, in `docs/database.md` retention notes: 90d operational / 7y audit where applicable).
- For larger deployments prefer `pg_basebackup` + WAL archiving (point-in-time recovery); the logical dump above is the floor, not the ceiling.
- Verify every backup: a backup without a restore test is a hope, not a backup. Record results where your incident process tracks them.

## 2. Object storage (artifacts, sandbox outputs, uploads)

- Filesystem provider (`OBJECT_STORAGE_PROVIDER=filesystem`): snapshot the artifact directory with the same schedule as the database.
- MinIO/S3 (`OBJECT_STORAGE_PROVIDER=minio|s3`): enable bucket versioning + cross-region replication where available, and test restores.
- Artifacts are content-addressed by checksum; after restore, spot-check that referenced keys still resolve.

## 3. Redis (queues, leases, caches — ephemeral by design)

- Redis is NOT the system of record. PostgreSQL holds executions, leases expire by TTL, and workers re-claim.
- RDB/AOF persistence is optional and only shortens warm-up after a restart; document your choice (`appendonly yes` vs snapshot) in your deployment notes.
- After a Redis loss: restart workers, confirm `sweep_stale_heartbeats` marks dead workers and expired in-flight messages get requeued (`requeue_expired`), then watch queue depth return to baseline.

## 4. Configuration & secrets (most-forgotten, most-painful)

- Back up `.env` values (or your secret-manager entries), `WORKER_SERVICE_TOKEN`, OAuth client secrets, and signing keys **separately from data backups**, encrypted at rest.
- Without `SECRET_KEY`/`ENCRYPTION_KEY`, database contents are unreadable/unusable — losing secrets IS losing data.

## Recovery order

```text
1. PostgreSQL restore + alembic upgrade head (verify single head)
2. Secrets / environment restore
3. Object storage restore / re-attach
4. Redis (fresh is acceptable) + infra up
5. API → verify /health/ready == 200 → workers → scheduler
6. Operations dashboard: executions resume, queue depth drains
```
