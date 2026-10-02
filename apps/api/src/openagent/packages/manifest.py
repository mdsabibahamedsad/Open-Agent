"""MP22: canonical package manifest model.

The manifest is the stable on-disk / on-wire representation of a package
version (``manifest.json`` inside an ``openagent-package/`` bundle, and the
``manifest`` JSON column of ``package_versions``). Secrets are never part of
a manifest — only ``credential_reference`` / ``connection_reference``
descriptors (see :mod:`openagent.packages.config_schema`).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator

from openagent.packages.types import (
    PACKAGE_FORMAT,
    PACKAGE_FORMAT_VERSION,
    STANDARD_CATEGORIES,
    SUPPORTED_LICENSES,
    PackageType,
    PresetKind,
    ResourceType,
    TrustLevel,
    Visibility,
)
from openagent.packages.versioning import (
    VersionError,
    is_valid_version,
    validate_constraint,
)

_SLUG_RE = r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$"


class ManifestAuthor(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(default="", max_length=255)
    url: str = Field(default="", max_length=500)


class ManifestDependency(BaseModel):
    type: str = Field(min_length=1, max_length=64)
    package: str = Field(min_length=1, max_length=160, pattern=_SLUG_RE)
    version: str = Field(default="*", max_length=64)
    optional: bool = False
    peer: bool = False

    @field_validator("version")
    @classmethod
    def _version_must_parse(cls, value: str) -> str:
        try:
            validate_constraint(value)
        except VersionError as exc:
            raise ValueError(str(exc)) from exc
        return value


class ManifestResource(BaseModel):
    kind: str = Field(min_length=1, max_length=64)
    slug: str = Field(min_length=1, max_length=160, pattern=_SLUG_RE)
    name: str = Field(min_length=1, max_length=255)
    payload: dict[str, Any] = Field(default_factory=dict)


class ManifestSecurity(BaseModel):
    required_approvals: list[str] = Field(default_factory=list)
    network: str = Field(default="restricted")
    sandbox_profile: str = Field(default="")
    risk_notes: str = Field(default="", max_length=2000)


class ManifestCompatibility(BaseModel):
    openagent_version: str = Field(default="*")
    api_version: str = Field(default="v1")
    runtime_version: str = Field(default="*")
    feature_requirements: list[str] = Field(default_factory=list)


class PackageIdentity(BaseModel):
    id: str = Field(min_length=1, max_length=160, pattern=_SLUG_RE)
    name: str = Field(min_length=1, max_length=255)
    version: str = Field(min_length=1, max_length=32)
    type: str = Field(default=ResourceType.TEMPLATE_PACKAGE.value)

    @field_validator("version")
    @classmethod
    def _semver(cls, value: str) -> str:
        if not is_valid_version(value):
            raise ValueError(f"invalid semantic version: {value!r}")
        return value.lstrip("v")

    @field_validator("type")
    @classmethod
    def _known_type(cls, value: str) -> str:
        valid = {t.value for t in ResourceType}
        if value not in valid:
            raise ValueError(f"unknown package type: {value!r}")
        return value


class PackageManifest(BaseModel):
    """Validated in-memory manifest."""

    format: str = Field(default=PACKAGE_FORMAT)
    format_version: str = Field(default=PACKAGE_FORMAT_VERSION)
    package: PackageIdentity
    author: ManifestAuthor = Field(default_factory=lambda: ManifestAuthor(name="unknown"))
    license: str = Field(default="Apache-2.0")
    visibility: str = Field(default=Visibility.ORGANIZATION.value)
    trust: str = Field(default=TrustLevel.UNTRUSTED.value)
    description: str = Field(default="", max_length=5000)
    categories: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    icon: str = Field(default="")
    dependencies: list[ManifestDependency] = Field(default_factory=list)
    resources: list[ManifestResource] = Field(default_factory=list)
    configuration: dict[str, Any] = Field(default_factory=dict)
    security: ManifestSecurity = Field(default_factory=ManifestSecurity)
    compatibility: ManifestCompatibility = Field(default_factory=ManifestCompatibility)
    model_requirements: dict[str, Any] = Field(default_factory=dict)
    memory_requirements: dict[str, Any] = Field(default_factory=dict)
    browser_requirements: dict[str, Any] = Field(default_factory=dict)
    code_requirements: dict[str, Any] = Field(default_factory=dict)
    evaluation: dict[str, Any] = Field(default_factory=dict)
    changelog: str = Field(default="", max_length=10000)


class ManifestError(ValueError):
    """Raised when raw manifest data fails structural validation."""


def parse_manifest(raw: dict[str, Any]) -> PackageManifest:
    """Parse and structurally validate raw manifest data."""
    if not isinstance(raw, dict):
        raise ManifestError("manifest must be a JSON object")
    if raw.get("format", PACKAGE_FORMAT) != PACKAGE_FORMAT:
        raise ManifestError(
            f"unsupported package format: {raw.get('format')!r} "
            f"(expected {PACKAGE_FORMAT!r})"
        )
    if str(raw.get("format_version", PACKAGE_FORMAT_VERSION)) != PACKAGE_FORMAT_VERSION:
        raise ManifestError(
            "unsupported format_version "
            f"{raw.get('format_version')!r} (expected {PACKAGE_FORMAT_VERSION!r})"
        )
    try:
        return PackageManifest.model_validate(raw)
    except Exception as exc:
        raise ManifestError(f"invalid manifest: {exc}") from exc


def normalize_package_type(raw: str) -> str:
    try:
        return PackageType(raw).value
    except ValueError:
        upper = str(raw).upper()
        valid = {t.value for t in ResourceType}
        if upper in valid:
            return upper
        raise ManifestError(f"unknown package type: {raw!r}")


def normalize_preset_kind(raw: str) -> str:
    try:
        return PresetKind(raw).value
    except ValueError:
        upper = str(raw).upper()
        valid = {k.value for k in PresetKind}
        if upper in valid:
            return upper
        raise ManifestError(f"unknown preset kind: {raw!r}")


def manifest_summary(manifest: PackageManifest) -> dict[str, Any]:
    """Small JSON-serializable summary used by catalog entries and previews."""
    return {
        "id": manifest.package.id,
        "name": manifest.package.name,
        "version": manifest.package.version,
        "type": manifest.package.type,
        "description": manifest.description,
        "license": manifest.license,
        "categories": manifest.categories,
        "tags": manifest.tags,
        "dependencies": [d.model_dump() for d in manifest.dependencies],
        "resource_count": len(manifest.resources),
        "resource_kinds": sorted({r.kind for r in manifest.resources}),
    }


def validate_marketplace_metadata(manifest: PackageManifest) -> list[str]:
    """Return non-blocking metadata warnings for marketplace readiness."""
    warnings: list[str] = []
    if not manifest.description:
        warnings.append("description is empty; marketplace listings require one")
    if not manifest.categories:
        warnings.append("no categories assigned")
    elif any(c not in STANDARD_CATEGORIES for c in manifest.categories):
        warnings.append("uses non-standard categories")
    if manifest.license not in SUPPORTED_LICENSES:
        warnings.append(f"unusual license: {manifest.license!r}")
    if not manifest.icon:
        warnings.append("no icon defined")
    return warnings
