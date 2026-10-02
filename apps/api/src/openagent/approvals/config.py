"""Approval production configuration (MP19). Secure defaults; production
startup refuses silently-insecure combinations."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class ApprovalSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    APPROVALS_ENABLED: bool = Field(default=True)
    DEFAULT_APPROVAL_EXPIRATION: int = Field(default=4 * 3600, ge=60)
    MAX_APPROVAL_EXPIRATION: int = Field(default=7 * 24 * 3600, ge=300)
    DEFAULT_HIGH_RISK_POLICY: str = Field(default="REQUIRE_APPROVAL")
    REQUIRE_APPROVAL_FOR_EXTERNAL_SIDE_EFFECTS: bool = Field(default=True)
    REQUIRE_APPROVAL_FOR_PRODUCTION: bool = Field(default=True)
    ENABLE_MULTI_APPROVAL: bool = Field(default=True)
    ENABLE_DELEGATION: bool = Field(default=False)
    ENABLE_ESCALATION: bool = Field(default=True)
    ENABLE_BREAK_GLASS: bool = Field(default=False)

    def validate_production(self) -> list[str]:
        errors: list[str] = []
        if not self.APPROVALS_ENABLED:
            errors.append("APPROVALS_ENABLED must be true in production")
        if self.DEFAULT_HIGH_RISK_POLICY not in ("REQUIRE_APPROVAL", "DENY"):
            errors.append("DEFAULT_HIGH_RISK_POLICY must be REQUIRE_APPROVAL or DENY")
        if self.ENABLE_BREAK_GLASS:
            errors.append("ENABLE_BREAK_GLASS requires explicit multi-approved runbook; refusing silent enable")
        if self.MAX_APPROVAL_EXPIRATION > 30 * 24 * 3600:
            errors.append("MAX_APPROVAL_EXPIRATION is unreasonably long")
        return errors
