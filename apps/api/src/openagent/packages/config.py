"""MP22: domain configuration (env-driven, production-safe defaults)."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class PackageSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PACKAGES_", extra="ignore")

    MAX_ASSET_BYTES: int = Field(default=5 * 1024 * 1024)
    ALLOWED_ASSET_MIME: str = Field(
        default="image/png,image/jpeg,image/svg+xml,image/webp,text/markdown"
    )
    REQUIRE_SIGNATURE_FOR_CORE: bool = Field(default=True)
    DEFAULT_TRUST: str = Field(default="UNTRUSTED")
    CATALOG_PAGE_SIZE: int = Field(default=20)
    INSTALL_TIMEOUT_SECONDS: int = Field(default=600)
    RATE_LIMIT_PUBLISH_PER_HOUR: int = Field(default=20)
    RATE_LIMIT_INSTALL_PER_HOUR: int = Field(default=100)

    def validate_production(self) -> list[str]:
        problems: list[str] = []
        if self.MAX_ASSET_BYTES > 25 * 1024 * 1024:
            problems.append("PACKAGES_MAX_ASSET_BYTES is excessively large")
        return problems


@lru_cache
def get_package_settings() -> PackageSettings:
    return PackageSettings()


def validate_asset(filename: str, mime: str, size: int) -> list[str]:
    """Validate an uploaded package asset (no executables, bounded size)."""
    settings = get_package_settings()
    problems: list[str] = []
    lowered = filename.lower()
    if ".." in filename or "/" in filename or "\\" in filename:
        problems.append("asset filename must not contain path separators")
    if lowered.endswith((".exe", ".dll", ".so", ".dylib", ".sh", ".bat", ".ps1", ".js", ".html")):
        problems.append(f"executable asset type not allowed: {filename!r}")
    allowed = {item.strip() for item in settings.ALLOWED_ASSET_MIME.split(",")}
    if mime not in allowed:
        problems.append(f"asset MIME {mime!r} not in allow-list")
    if size > settings.MAX_ASSET_BYTES:
        problems.append(f"asset exceeds {settings.MAX_ASSET_BYTES} bytes")
    return problems
