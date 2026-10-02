"""MP28: developer settings (§63) + deployment pipeline types (§38)."""

from __future__ import annotations

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


class DeveloperSettings(BaseSettings):
    model_config = {"env_prefix": "OPENAGENT_DEV_", "extra": "ignore"}

    local_registry_dir: str = Field(default=".openagent/registry")
    package_signing_required: bool = Field(default=False)
    allow_secret_override: bool = Field(default=False)
    default_sandbox_profile: str = Field(default="TOOL")
    deployment_health_timeout_s: int = Field(default=120, ge=5, le=900)
    webhook_replay_tolerance_s: int = Field(default=300, ge=60, le=3600)

    def validate_production(self) -> list[str]:
        problems: list[str] = []
        if self.allow_secret_override:
            problems.append(
                "OPENAGENT_DEV_ALLOW_SECRET_OVERRIDE must be false in production "
                "(published packages must never contain secrets)"
            )
        return problems


_DEPLOYMENT_STAGES: tuple[str, ...] = (
    "validate",
    "test",
    "build",
    "package",
    "security_scan",
    "compatibility_check",
    "sign",
    "deploy",
    "health_check",
    "activate",
)


class DeploymentPlan(BaseModel):
    extension: str = Field(min_length=1)
    version: str = Field(min_length=1)
    environment: str = Field(default="staging")
    stages: list[str] = Field(default_factory=lambda: list(_DEPLOYMENT_STAGES))

    model_config = {"extra": "forbid"}
