"""Connector production configuration (MP21). Secure defaults; production
startup refuses silently-unsafe combinations."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConnectorSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    CONNECTORS_ENABLED: bool = Field(default=True)
    CONNECTOR_DEFAULT_TIMEOUT: int = Field(default=30, ge=1, le=300)
    CONNECTOR_MAX_TIMEOUT: int = Field(default=120, ge=5, le=600)
    CONNECTOR_MAX_PAGES: int = Field(default=10, ge=1, le=100)
    CONNECTOR_MAX_ITEMS: int = Field(default=500, ge=1, le=10000)
    CONNECTOR_MAX_BYTES: int = Field(default=5 * 1024 * 1024, ge=1024)
    CONNECTOR_ALLOW_PRIVATE_EGRESS: bool = Field(default=False)
    CONNECTOR_REQUIRE_HTTPS: bool = Field(default=True)
    CONNECTOR_WEBHOOK_TOLERANCE_SECONDS: int = Field(default=300, ge=30, le=3600)
    CONNECTOR_MAX_WEBHOOK_BYTES: int = Field(default=1024 * 1024, ge=1024)
    CONNECTOR_POLL_MIN_INTERVAL: int = Field(default=60, ge=10)
    CONNECTOR_CIRCUIT_THRESHOLD: int = Field(default=5, ge=2, le=50)
    CONNECTOR_QUOTA_PER_MINUTE: int = Field(default=120, ge=1, le=10000)
    CONNECTOR_ENABLE_COMMUNITY: bool = Field(default=False)
    CONNECTOR_ENABLE_CUSTOM_CODE: bool = Field(default=False)

    def validate_production(self) -> list[str]:
        errors: list[str] = []
        if self.CONNECTOR_ALLOW_PRIVATE_EGRESS:
            errors.append("CONNECTOR_ALLOW_PRIVATE_EGRESS requires explicit network policy; "
                          "refusing silent enable")
        if not self.CONNECTOR_REQUIRE_HTTPS:
            errors.append("CONNECTOR_REQUIRE_HTTPS must stay true in production")
        if self.CONNECTOR_ENABLE_CUSTOM_CODE:
            errors.append("CONNECTOR_ENABLE_CUSTOM_CODE requires sandbox review; "
                          "refusing silent enable")
        if self.CONNECTOR_MAX_ITEMS > 10000:
            errors.append("CONNECTOR_MAX_ITEMS is unreasonably high")
        return errors
