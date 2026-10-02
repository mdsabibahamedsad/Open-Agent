"""MP25: cloud runtime settings + feature flags + safety limits.

Cloud modules are optional: with ``OPENAGENT_CLOUD_ENABLED=false``
(default) the self-hosted/local path keeps working and cloud services
raise a clear ``CloudDisabled`` instead of crashing at import time.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from openagent.cloud.types import CloudFeature, IncidentMode, RuntimeMode


class CloudSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", case_sensitive=True,
                                      extra="ignore")

    OPENAGENT_RUNTIME_MODE: str = Field(default=RuntimeMode.SELF_HOSTED)
    OPENAGENT_CLOUD_ENABLED: bool = Field(default=False)

    # Object storage (S3-compatible baseline: MinIO locally).
    OBJECT_STORAGE_PROVIDER: str = Field(default="filesystem")
    OBJECT_STORAGE_BUCKET: str = Field(default="openagent-artifacts")
    OBJECT_STORAGE_ENDPOINT: str = Field(default="")
    OBJECT_STORAGE_REGION: str = Field(default="us-east-1")
    OBJECT_STORAGE_ACCESS_KEY: str = Field(default="")
    OBJECT_STORAGE_SECRET_KEY: str = Field(default="")
    ARTIFACT_MAX_BYTES: int = Field(default=536870912)  # 512 MiB
    ARTIFACT_DEFAULT_TTL_SECONDS: int = Field(default=2592000)  # 30d

    # Queue baseline.
    CLOUD_QUEUE_PROVIDER: str = Field(default="redis")
    CLOUD_QUEUE_MAX_DEPTH: int = Field(default=100000)

    # Workers / autoscaling safety.
    WORKER_HEARTBEAT_SECONDS: int = Field(default=30)
    WORKER_HEARTBEAT_TTL_SECONDS: int = Field(default=90)
    WORKER_LEASE_SECONDS: int = Field(default=300)
    EXECUTION_LEASE_SECONDS: int = Field(default=600)
    AUTOSCALE_MIN_WORKERS: int = Field(default=1)
    AUTOSCALE_MAX_WORKERS: int = Field(default=20)
    AUTOSCALE_COOLDOWN_SECONDS: int = Field(default=120)
    AUTOSCALE_SCALE_UP_STEP: int = Field(default=2)
    AUTOSCALE_SCALE_DOWN_STEP: int = Field(default=1)

    # Global safety limits (Master Account configurable at runtime too).
    GLOBAL_MAX_WORKERS: int = Field(default=100)
    GLOBAL_MAX_EXECUTIONS: int = Field(default=10000)
    GLOBAL_MAX_QUEUE_DEPTH: int = Field(default=100000)
    GLOBAL_MAX_SANDBOX_COUNT: int = Field(default=200)
    GLOBAL_MAX_BROWSER_COUNT: int = Field(default=100)
    GLOBAL_MAX_STORAGE_BYTES: int = Field(default=1099511627776)  # 1 TiB
    MAX_EXECUTION_SECONDS: int = Field(default=3600)
    MAX_EXECUTIONS_PER_MINUTE_PER_ORG: int = Field(default=120)

    # Regions / placement.
    CLOUD_DEFAULT_REGION: str = Field(default="local-1")
    CLOUD_ALLOWED_REGIONS: str = Field(default="local-1")

    # Distributed scheduler.
    SCHEDULER_LOCK_TTL_SECONDS: int = Field(default=60)
    SCHEDULER_POLL_SECONDS: int = Field(default=15)
    SCHEDULER_MISFIRE_GRACE_SECONDS: int = Field(default=300)

    # Retention (seconds; 0 = keep forever where allowed).
    RETENTION_EXECUTION_EVENTS_SECONDS: int = Field(default=7776000)  # 90d
    RETENTION_LOGS_SECONDS: int = Field(default=2592000)  # 30d
    RETENTION_ARTIFACTS_SECONDS: int = Field(default=2592000)
    RETENTION_HEARTBEATS_SECONDS: int = Field(default=604800)  # 7d

    # Operational mode.
    CLOUD_INCIDENT_MODE: str = Field(default=IncidentMode.NORMAL)

    # Feature flags (single source of truth; avoid scattered booleans).
    FEATURE_CLOUD_RUNTIME: bool = Field(default=False)
    FEATURE_DISTRIBUTED_WORKERS: bool = Field(default=False)
    FEATURE_MULTI_REGION: bool = Field(default=False)
    FEATURE_AUTOSCALING: bool = Field(default=False)
    FEATURE_OBJECT_STORAGE: bool = Field(default=False)
    FEATURE_CLOUD_SCHEDULER: bool = Field(default=False)
    FEATURE_CLOUD_ARTIFACTS: bool = Field(default=False)

    def runtime_mode(self) -> str:
        return str(self.OPENAGENT_RUNTIME_MODE or RuntimeMode.SELF_HOSTED).lower()

    def cloud_enabled(self) -> bool:
        if self.runtime_mode() == RuntimeMode.CLOUD:
            return True
        return bool(self.OPENAGENT_CLOUD_ENABLED or self.FEATURE_CLOUD_RUNTIME)

    def allowed_regions(self) -> list[str]:
        return [r.strip() for r in str(self.CLOUD_ALLOWED_REGIONS or "").split(",") if r.strip()]

    def feature_enabled(self, feature: str) -> bool:
        mapping = {
            CloudFeature.CLOUD_RUNTIME: self.FEATURE_CLOUD_RUNTIME or self.cloud_enabled(),
            CloudFeature.DISTRIBUTED_WORKERS: self.FEATURE_DISTRIBUTED_WORKERS or self.cloud_enabled(),
            CloudFeature.MULTI_REGION: self.FEATURE_MULTI_REGION,
            CloudFeature.AUTOSCALING: self.FEATURE_AUTOSCALING,
            CloudFeature.OBJECT_STORAGE: self.FEATURE_OBJECT_STORAGE or self.cloud_enabled(),
            CloudFeature.CLOUD_SCHEDULER: self.FEATURE_CLOUD_SCHEDULER or self.cloud_enabled(),
            CloudFeature.CLOUD_ARTIFACTS: self.FEATURE_CLOUD_ARTIFACTS or self.cloud_enabled(),
        }
        return bool(mapping.get(feature, False))

    def validate_production(self) -> list[str]:
        problems: list[str] = []
        if self.cloud_enabled() and self.runtime_mode() not in (
                RuntimeMode.CLOUD, RuntimeMode.HYBRID, RuntimeMode.SELF_HOSTED):
            problems.append(f"unknown OPENAGENT_RUNTIME_MODE={self.OPENAGENT_RUNTIME_MODE!r}")
        if self.AUTOSCALE_MIN_WORKERS < 0:
            problems.append("AUTOSCALE_MIN_WORKERS must be >= 0")
        if self.AUTOSCALE_MAX_WORKERS < self.AUTOSCALE_MIN_WORKERS:
            problems.append("AUTOSCALE_MAX_WORKERS must be >= AUTOSCALE_MIN_WORKERS")
        if self.GLOBAL_MAX_WORKERS <= 0:
            problems.append("GLOBAL_MAX_WORKERS must be > 0")
        if self.WORKER_HEARTBEAT_TTL_SECONDS <= self.WORKER_HEARTBEAT_SECONDS:
            problems.append("WORKER_HEARTBEAT_TTL_SECONDS must exceed WORKER_HEARTBEAT_SECONDS")
        if self.CLOUD_INCIDENT_MODE not in IncidentMode.ALL:
            problems.append(f"unknown CLOUD_INCIDENT_MODE={self.CLOUD_INCIDENT_MODE!r}")
        if self.ARTIFACT_MAX_BYTES <= 0:
            problems.append("ARTIFACT_MAX_BYTES must be > 0")
        return problems


@lru_cache
def get_cloud_settings() -> CloudSettings:
    return CloudSettings()
