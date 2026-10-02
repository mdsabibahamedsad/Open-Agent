# Disaster recovery

Backups: Postgres (managed snapshots or `pg_basebackup` + WAL), object
storage (versioning + cross-region replication), config in version
control, encryption/KMS keys in offline vaults. Restore order: database
→ object storage → queues (requeue from execution state) → workers →
scheduler (dedup keys make replay safe). RPO/RTO are documented per
deployment after testing — no production values are claimed here
without benchmarks. Queue recovery replays from execution/attempt state;
object recovery re-verifies checksums.
