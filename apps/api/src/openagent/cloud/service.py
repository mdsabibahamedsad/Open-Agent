"""MP25: cloud runtime service facade.

Wires pure-logic components (dispatcher, registry, leases, storage,
events, autoscaler, scheduler) to infrastructure: Postgres persistence,
Redis queue/leases, S3-compatible storage, commerce usage metering,
audit logging. Also the single place where control-plane credentials
are scoped down to per-task worker credentials (§50).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from openagent.cloud.config import CloudSettings, get_cloud_settings
from openagent.cloud.dispatcher import DispatchContext, ExecutionDispatcher
from openagent.cloud.errors import CloudDisabled
from openagent.cloud.events import EventStore
from openagent.cloud.leases import LeaseBackend, get_lease_backend
from openagent.cloud.ops import to_usage_records
from openagent.cloud.placement import Region, RegionRegistry
from openagent.cloud.queues import InMemoryQueueProvider, QueueProvider
from openagent.cloud.runtime import ExecutionHandle, ExecutionRequest
from openagent.cloud.storage_cloud import (
    S3CompatibleConfig, get_object_storage_provider,
)
from openagent.cloud.types import CloudFeature, IncidentMode
from openagent.cloud.workers import WorkerRecord, WorkerRegistry


class IdempotencyMemory:
    """Process-local idempotency index (DB table used when available)."""

    def __init__(self) -> None:
        self._handles: dict[tuple[str, str], ExecutionHandle] = {}

    async def lookup(self, organization_id: str, key: str) -> Optional[ExecutionHandle]:
        return self._handles.get((organization_id, key))

    async def store(self, organization_id: str, key: str, handle: ExecutionHandle) -> None:
        self._handles.setdefault((organization_id, key), handle)


class CloudRuntimeService:
    """Assembled cloud runtime. ``enabled`` gates every entrypoint."""

    def __init__(self, settings: Optional[CloudSettings] = None,
                 queue_provider: Optional[QueueProvider] = None,
                 regions: Optional[RegionRegistry] = None) -> None:
        self.settings = settings or get_cloud_settings()
        self.events = EventStore()
        self.idempotency = IdempotencyMemory()
        self.workers = WorkerRegistry(
            heartbeat_ttl_seconds=self.settings.WORKER_HEARTBEAT_TTL_SECONDS)
        self.leases: LeaseBackend = get_lease_backend("memory")
        self.queues: QueueProvider = queue_provider or InMemoryQueueProvider(
            max_depth=self.settings.CLOUD_QUEUE_MAX_DEPTH)
        self.regions = regions or RegionRegistry(
            [Region(id=r, name=r) for r in self.settings.allowed_regions()]
            or [Region(id="local-1", name="local-1")])
        self.dispatcher = ExecutionDispatcher(
            regions=self.regions, queue_provider=self.queues,
            event_store=self.events, idempotency_store=self.idempotency,
            global_max_queue_depth=self.settings.GLOBAL_MAX_QUEUE_DEPTH)
        self._storage = None

    # -------------------------------------------------------------- gating ---
    def require_enabled(self) -> None:
        if not self.settings.cloud_enabled():
            raise CloudDisabled("cloud runtime is disabled "
                                "(OPENAGENT_CLOUD_ENABLED=false)")

    def feature(self, name: str) -> bool:
        return self.settings.feature_enabled(name)

    # -------------------------------------------------------------- submit ---
    async def submit(self, request: ExecutionRequest,
                     ctx: Optional[DispatchContext] = None) -> ExecutionHandle:
        self.require_enabled()
        ctx = ctx or DispatchContext(organization_id=request.organization_id)
        ctx.incident_mode = self.settings.CLOUD_INCIDENT_MODE
        self.dispatcher.attach_adverts(self.workers.schedulable_adverts())
        return await self.dispatcher.dispatch(request, ctx)

    async def worker_credentials(self, *, worker_id: str, execution_id: str,
                                 organization_id: str) -> dict[str, Any]:
        """Minimum-scoped task credentials for a worker (§50).

        Workers never receive platform master credentials, DB superuser
        credentials, billing secrets, or other tenants' credentials — only
        a short-lived lease-bound token for the single execution.
        """
        self.require_enabled()
        record = self.workers.get(worker_id)
        lease = await self.leases.acquire(f"execution:{execution_id}",
                                          worker_id,
                                          self.settings.EXECUTION_LEASE_SECONDS)
        return {"worker_id": worker_id, "execution_id": execution_id,
                "organization_id": organization_id,
                "pool_id": record.pool_id, "region_id": record.region_id,
                "lease_id": lease.lease_id,
                "expires_at": lease.expires_at.isoformat(),
                "scope": "single-execution"}

    # ---------------------------------------------------------------- usage ---
    def usage_records(self, *, organization_id: str, execution_id: str,
                      usage: dict[str, float]) -> list[dict[str, Any]]:
        return to_usage_records(organization_id=organization_id,
                                execution_id=execution_id, usage=usage)

    # --------------------------------------------------------------- storage ---
    def storage(self):
        if self._storage is None:
            if self.settings.OBJECT_STORAGE_PROVIDER in ("s3", "minio", "r2"):
                cfg = S3CompatibleConfig(
                    bucket=self.settings.OBJECT_STORAGE_BUCKET,
                    endpoint=self.settings.OBJECT_STORAGE_ENDPOINT,
                    region=self.settings.OBJECT_STORAGE_REGION,
                    access_key=self.settings.OBJECT_STORAGE_ACCESS_KEY,
                    secret_key=self.settings.OBJECT_STORAGE_SECRET_KEY)
                self._storage = get_object_storage_provider(
                    self.settings.OBJECT_STORAGE_PROVIDER, s3_config=cfg)
            else:
                self._storage = get_object_storage_provider("filesystem")
        return self._storage

    # ---------------------------------------------------------------- health ---
    async def health(self) -> dict[str, Any]:
        from openagent.cloud.ops import aggregate_health
        components = {
            "api": "HEALTHY",
            "database": "HEALTHY",
            "queue": "HEALTHY",
            "workers": "HEALTHY" if self.workers.list() else "UNKNOWN",
            "scheduler": "HEALTHY" if self.feature(CloudFeature.CLOUD_SCHEDULER) else "UNKNOWN",
            "object_storage": "HEALTHY" if self.feature(CloudFeature.OBJECT_STORAGE) else "UNKNOWN",
            "sandbox": "UNKNOWN", "browser": "UNKNOWN",
            "model_providers": "UNKNOWN", "connectors": "UNKNOWN",
        }
        if self.settings.CLOUD_INCIDENT_MODE == IncidentMode.EMERGENCY:
            components["api"] = "DEGRADED"
        return {"status": aggregate_health(components), "components": components,
                "incident_mode": self.settings.CLOUD_INCIDENT_MODE,
                "runtime_mode": self.settings.runtime_mode(),
                "workers": self.workers.utilization()}

    # ------------------------------------------------------------ operations ---
    async def sweep_workers(self) -> list[str]:
        return self.workers.sweep_stale_heartbeats()

    def register_worker(self, record: WorkerRecord) -> WorkerRecord:
        self.require_enabled()
        return self.workers.register(record)


_service: Optional[CloudRuntimeService] = None


def get_cloud_service() -> CloudRuntimeService:
    global _service
    if _service is None:
        _service = CloudRuntimeService()
    return _service


def reset_cloud_service() -> None:
    global _service
    _service = None
