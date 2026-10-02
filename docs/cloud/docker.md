# Docker

Images: `api`, `worker` (fleet + scheduler + gc entrypoints), `scheduler`
(timer), `frontend`. All images:

* run as non-root where practical (`appuser`);
* pin base images and critical dependencies;
* expose health checks (`/api/v1/health`; workers via heartbeats);
* handle `SIGTERM` → graceful drain (workers finish safe work, requeue
  the rest) with configurable timeout;
* bake in no secrets (all via environment / secret references);
* build reproducibly (`pip freeze` / lockfiles; no `latest` tags).

See `apps/api/Dockerfile`, `apps/worker/Dockerfile`,
`infrastructure/docker/sandbox/`.
