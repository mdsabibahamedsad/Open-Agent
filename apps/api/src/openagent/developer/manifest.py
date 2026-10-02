"""MP28: canonical extension manifest (§12).

Single manifest schema for every extension type. Strict validation:
unknown extension types, unknown permissions, secret values embedded in
config, and unsafe network declarations are rejected with actionable
errors. Never silently defaults into broader permissions.
"""

from __future__ import annotations

import re
from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from openagent.developer.types import (
    EXTENSION_TYPES,
    MANIFEST_VERSION,
    PERMISSION_CATALOG,
)
from openagent.developer.versioning import (
    VersionError,
    validate_constraint,
    validate_semver,
)

_SLUG_RE = r"^[a-z0-9]+(?:[._\-/@][a-z0-9]+)*$"
_NAME_RE = r"^[a-z0-9][a-z0-9._\-/@]{1,127}$"


class ManifestAuthor(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(default="", max_length=255)
    url: str = Field(default="", max_length=500)


class ManifestRuntime(BaseModel):
    language: str = Field(default="typescript", pattern="^(typescript|python|wasm|docker)$")
    entrypoint: str = Field(min_length=1, max_length=512)
    version: str = Field(default="", max_length=64)


class ManifestCapability(BaseModel):
    name: str = Field(min_length=1, max_length=128)


class ManifestCompatibility(BaseModel):
    openagent: str = Field(default=">=1.0.0 <2.0.0")
    sdk: str = Field(default=">=1.0.0 <2.0.0")
    extension_api: str = Field(default="1.x")
    api_version: str = Field(default="v1")

    @field_validator("openagent", "sdk")
    @classmethod
    def _constraint_must_parse(cls, value: str) -> str:
        try:
            validate_constraint(value)
        except VersionError as exc:
            raise ValueError(str(exc)) from exc
        return value


class ManifestSecurity(BaseModel):
    trust_level: str = Field(default="UNTRUSTED")
    network_policy: str = Field(default="restricted", pattern="^(none|restricted|allowlisted)$")
    allowed_hosts: list[str] = Field(default_factory=list)
    sandbox_profile: str = Field(default="")
    risk_notes: str = Field(default="", max_length=4000)

    @field_validator("trust_level")
    @classmethod
    def _trust_known(cls, value: str) -> str:
        allowed = {"CORE", "VERIFIED", "ORGANIZATION", "COMMUNITY", "UNTRUSTED"}
        if value not in allowed:
            raise ValueError(f"unknown trust_level '{value}'")
        return value


class ManifestDependency(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    version: str = Field(default="*")
    optional: bool = False

    @field_validator("version")
    @classmethod
    def _version_constraint(cls, value: str) -> str:
        try:
            validate_constraint(value)
        except VersionError as exc:
            raise ValueError(str(exc)) from exc
        return value


class ExtensionManifest(BaseModel):
    """Canonical on-disk / on-wire extension manifest (openagent.yaml)."""

    manifest_version: str = Field(default=MANIFEST_VERSION)
    name: str = Field(min_length=2, max_length=128, pattern=_NAME_RE)
    namespace: str = Field(default="", max_length=128)
    version: str = Field(min_length=5, max_length=32)
    display_name: str = Field(default="", max_length=200)
    description: str = Field(min_length=1, max_length=2000)
    author: ManifestAuthor
    license: str = Field(min_length=1, max_length=64)
    repository: str = Field(default="", max_length=500)
    documentation: str = Field(default="", max_length=500)
    type: str = Field(min_length=1, max_length=64)
    runtime: ManifestRuntime
    permissions: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    required_services: list[str] = Field(default_factory=list)
    config_schema: dict[str, Any] = Field(default_factory=dict)
    secrets: list[str] = Field(default_factory=list)
    network: dict[str, Any] = Field(default_factory=dict)
    storage: dict[str, Any] = Field(default_factory=dict)
    compatibility: ManifestCompatibility = Field(default_factory=ManifestCompatibility)
    dependencies: list[ManifestDependency] = Field(default_factory=list)
    optional_dependencies: list[ManifestDependency] = Field(default_factory=list)
    ui: dict[str, Any] = Field(default_factory=dict)
    commands: list[str] = Field(default_factory=list)
    events: list[str] = Field(default_factory=list)
    hooks: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    security: ManifestSecurity = Field(default_factory=ManifestSecurity)

    @field_validator("version")
    @classmethod
    def _semver(cls, value: str) -> str:
        try:
            validate_semver(value)
        except VersionError as exc:
            raise ValueError(str(exc)) from exc
        return value

    @field_validator("type")
    @classmethod
    def _known_type(cls, value: str) -> str:
        if value not in EXTENSION_TYPES:
            raise ValueError(
                f"unknown extension type '{value}'. "
                f"Supported: {', '.join(sorted(EXTENSION_TYPES))}"
            )
        return value

    @field_validator("permissions")
    @classmethod
    def _known_permissions(cls, values: list[str]) -> list[str]:
        unknown = [p for p in values if p not in PERMISSION_CATALOG]
        if unknown:
            raise ValueError(
                f"unknown permission(s): {', '.join(unknown)}. "
                "Declare only permissions from the permission catalog."
            )
        if len(set(values)) != len(values):
            raise ValueError("duplicate permissions declared")
        return values

    @model_validator(mode="after")
    def _cross_field_rules(self) -> ExtensionManifest:
        # Secrets are references (names), never values: reject mapping shapes.
        if isinstance(self.secrets, dict):  # type: ignore[unreachable]
            raise ValueError("secrets must be a list of secret reference names, never values")
        for secret in self.secrets:
            if not re.match(r"^[A-Z][A-Z0-9_]{2,63}$", secret):
                raise ValueError(
                    f"secret reference '{secret}' must look like ENV_VAR_NAME "
                    "(uppercase, underscores) and must not contain a value"
                )
        # Network allowlist required when outbound access is requested.
        if "network:outbound" in self.permissions:
            hosts = self.network.get("allowed_hosts", self.security.allowed_hosts)
            if not hosts:
                raise ValueError(
                    "permission 'network:outbound' requires "
                    "network.allowed_hosts (or security.allowed_hosts) to be non-empty"
                )
        if "network:restricted" in self.permissions and self.security.network_policy != "allowlisted":
            raise ValueError(
                "permission 'network:restricted' requires "
                "security.network_policy='allowlisted' with explicit allowed_hosts"
            )
        # Config schema must not embed secret values.
        schema_text = str(self.config_schema).lower()
        for marker in ("AKIA", "BEGIN PRIVATE KEY", "BEGIN RSA PRIVATE KEY"):
            if marker.lower() in schema_text:
                raise ValueError("config_schema must not embed credential material")
        return self


class ManifestError(ValueError):
    pass


def load_manifest_dict(data: dict[str, Any]) -> ExtensionManifest:
    try:
        return ExtensionManifest.model_validate(data)
    except Exception as exc:
        raise ManifestError(f"invalid extension manifest: {exc}") from exc


def load_manifest_text(text: str) -> ExtensionManifest:
    """Parse openagent.yaml / openagent.json manifest text."""
    stripped = text.strip()
    try:
        if stripped.startswith("{"):
            import json

            data = json.loads(text)
        else:
            data = yaml.safe_load(text)
    except Exception as exc:
        raise ManifestError(f"manifest parse error: {exc}") from exc
    if not isinstance(data, dict):
        raise ManifestError("manifest root must be a mapping")
    return load_manifest_dict(data)


def manifest_to_canonical_json(manifest: ExtensionManifest) -> str:
    import json

    return json.dumps(manifest.model_dump(), sort_keys=True, separators=(",", ":"))
