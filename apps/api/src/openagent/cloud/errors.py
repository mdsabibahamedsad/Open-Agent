"""MP25: cloud runtime errors (stable codes for API + worker + tests)."""

from __future__ import annotations


class CloudError(Exception):
    code = "CLOUD_ERROR"


class CloudDisabled(CloudError):
    code = "CLOUD_DISABLED"


class InvalidExecutionTransition(CloudError):
    code = "INVALID_EXECUTION_TRANSITION"


class InvalidWorkerTransition(CloudError):
    code = "INVALID_WORKER_TRANSITION"


class QuotaExceeded(CloudError):
    code = "QUOTA_EXCEEDED"


class EntitlementDenied(CloudError):
    code = "ENTITLEMENT_DENIED"


class PlacementFailed(CloudError):
    code = "PLACEMENT_FAILED"


class QueueFull(CloudError):
    code = "QUEUE_FULL"


class IncidentBlocked(CloudError):
    code = "INCIDENT_BLOCKED"


class LeaseConflict(CloudError):
    code = "LEASE_CONFLICT"


class WorkerNotFound(CloudError):
    code = "WORKER_NOT_FOUND"


class RegionNotAvailable(CloudError):
    code = "REGION_NOT_AVAILABLE"


class ArtifactRejected(CloudError):
    code = "ARTIFACT_REJECTED"


class StorageError(CloudError):
    code = "STORAGE_ERROR"
