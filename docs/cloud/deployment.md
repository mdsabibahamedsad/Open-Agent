# Cloud deployment

## Portable baseline (recommended)

Docker + PostgreSQL + Redis + S3-compatible storage (MinIO):

```bash
git clone <openagent>
cd openagent
cp .env.example .env   # set SECRET_KEY, ENCRYPTION_KEY, WORKER_SERVICE_TOKEN
docker compose up -d
docker compose logs -f api worker scheduler
```

Services: `postgres`, `redis`, `minio`, `api`, `worker` (cloud fleet),
`scheduler`, `web`. Cloud mode:

```env
OPENAGENT_RUNTIME_MODE=cloud
OPENAGENT_CLOUD_ENABLED=true
FEATURE_CLOUD_RUNTIME=true
WORKER_SERVICE_TOKEN=<random-32+>
```

## Production checklist

* Run Alembic migrations (`024_add_cloud_runtime` seeds `local-1`).
* Set `OBJECT_STORAGE_PROVIDER=s3|minio`, bucket + credentials.
* Pin sandbox image digests; run API/worker as non-root; health checks
  on `/api/v1/health` (API) and heartbeats (workers).
* Configure `GLOBAL_MAX_*` + autoscale bounds before opening traffic.
* Backups: Postgres (pg_basebackup/managed snapshots), object storage
  versioning/replication, config + KMS keys offline.

## Kubernetes (optional reference)

See `infrastructure/k8s/` for namespace, API/worker/scheduler/frontend
deployments, HPA, PDB, services, config + secret references. Kubernetes
is never required for self-hosting.
