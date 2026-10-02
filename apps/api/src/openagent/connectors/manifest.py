"""Declarative connector manifest validation (MP21).

Manifests are data, never code. Validation is strict and fail-closed:
unknown auth types, missing schemas, bad versions, or excessive scope
requests are rejected before a connector can activate.
"""

from __future__ import annotations

import json
import re
from typing import Any

from openagent.connectors.types import (
    ActionDef,
    AuthType,
    CapabilityDef,
    ConnectorManifest,
    ConnectorType,
    ResourceDef,
    RiskLevel,
    TriggerDef,
    TriggerKind,
    TrustTier,
)

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{1,63}$")
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+([-.+][0-9A-Za-z.-]+)?$")
_ACTION_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{1,127}$")

CATEGORIES = {"ai", "communication", "developer", "productivity", "storage",
              "database", "crm", "marketing", "analytics", "finance",
              "commerce", "automation", "infrastructure"}

NORMALIZED_RESOURCES = {"user", "message", "file", "folder", "repository",
                        "issue", "pull_request", "task", "ticket", "customer",
                        "invoice", "order", "calendar_event", "document",
                        "database_row"}


class ManifestError(Exception):
    def __init__(self, message: str, code: str = "MANIFEST_INVALID"):
        super().__init__(message)
        self.code = code


def _require_str(mapping: dict[str, Any], key: str, what: str,
                 max_len: int = 256) -> str:
    value = mapping.get(key, "")
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"{what} requires non-empty '{key}'")
    if len(value) > max_len:
        raise ManifestError(f"{what} '{key}' exceeds {max_len} chars")
    return value.strip()


def _risk(value: Any, what: str) -> RiskLevel:
    try:
        return RiskLevel(str(value or "MEDIUM").upper())
    except ValueError:
        raise ManifestError(f"{what} has unknown risk_level '{value}'") from None


def validate_manifest(raw: dict[str, Any]) -> ConnectorManifest:
    """Validate a raw manifest dict into a ConnectorManifest. Raises ManifestError."""
    if not isinstance(raw, dict):
        raise ManifestError("Manifest must be an object")
    connector_id = _require_str(raw, "id", "connector", 64).lower()
    if not _SLUG_RE.match(connector_id):
        raise ManifestError(f"Invalid connector id '{connector_id}'")
    version = _require_str(raw, "version", "connector", 32)
    if not _VERSION_RE.match(version):
        raise ManifestError(f"Invalid semantic version '{version}'")
    try:
        connector_type = ConnectorType(str(raw.get("type", "OFFICIAL")).upper())
    except ValueError:
        raise ManifestError(f"Unknown connector type '{raw.get('type')}'") from None
    try:
        trust = TrustTier(str(raw.get("trust", "UNTRUSTED")).upper())
    except ValueError:
        raise ManifestError(f"Unknown trust tier '{raw.get('trust')}'") from None
    category = str(raw.get("category", "automation")).lower()
    if category not in CATEGORIES:
        raise ManifestError(f"Unknown category '{category}'")

    auth = raw.get("auth", {}) or {}
    if not isinstance(auth, dict):
        raise ManifestError("'auth' must be an object")
    try:
        auth_type = AuthType(str(auth.get("type", "none")).lower())
    except ValueError:
        raise ManifestError(f"Unknown auth type '{auth.get('type')}'") from None
    if auth_type == AuthType.OAUTH2:
        for key in ("authorize_url", "token_url"):
            if not auth.get(key):
                raise ManifestError(f"oauth2 auth requires '{key}'")
        for url_key in ("authorize_url", "token_url"):
            url = str(auth[url_key])
            if not url.startswith("https://"):
                raise ManifestError(f"oauth2 '{url_key}' must be https")
    if auth_type == AuthType.NONE and connector_type not in (
            ConnectorType.INTERNAL, ConnectorType.WEBHOOK_ONLY):
        raise ManifestError("Only INTERNAL/WEBHOOK_ONLY connectors may use auth:none")

    capabilities = _capabilities(raw.get("capabilities", []) or [], connector_id)
    actions = _actions(raw.get("actions", []) or [], connector_id, capabilities)
    triggers = _triggers(raw.get("triggers", []) or [], connector_id)
    resources = _resources(raw.get("resources", []) or [])

    scopes = raw.get("scopes", []) or []
    if not isinstance(scopes, list) or any(not isinstance(s, str) for s in scopes):
        raise ManifestError("'scopes' must be a list of strings")
    if len(scopes) > 64:
        raise ManifestError("Excessive scope request (>64 scopes) rejected")

    manifest = ConnectorManifest(
        id=connector_id, name=_require_str(raw, "name", "connector", 120),
        version=version, category=category, connector_type=connector_type,
        trust=trust, description=str(raw.get("description", ""))[:2000],
        publisher=str(raw.get("publisher", ""))[:120],
        license=str(raw.get("license", ""))[:64],
        documentation_url=str(raw.get("documentation_url", ""))[:500],
        auth={k: v for k, v in auth.items() if k != "client_secret"},
        capabilities=capabilities, actions=actions, triggers=triggers,
        resources=resources, scopes=[s[:128] for s in scopes],
        rate_limits=dict(raw.get("rate_limits", {}) or {}),
        supported_environments=list(raw.get("supported_environments",
                                            ["production"]) or ["production"]),
        signature=str(raw.get("signature", ""))[:2000])
    manifest.content_hash = manifest_hash(manifest)
    return manifest


def _capabilities(raw: list, connector_id: str) -> list[CapabilityDef]:
    out: list[CapabilityDef] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise ManifestError("Capability entries must be objects")
        capability_id = str(item.get("id", "")).strip().lower()
        if not capability_id.startswith(connector_id + ".") or len(capability_id) > 160:
            raise ManifestError(
                f"Capability '{capability_id}' must be namespaced '{connector_id}.*'")
        if capability_id in seen:
            raise ManifestError(f"Duplicate capability '{capability_id}'")
        seen.add(capability_id)
        out.append(CapabilityDef(id=capability_id,
                                 description=str(item.get("description", ""))[:500],
                                 risk_level=_risk(item.get("risk_level", "LOW"),
                                                  f"capability '{capability_id}'")))
    if not out:
        raise ManifestError("Manifest must declare at least one capability")
    return out


def _actions(raw: list, connector_id: str,
             capabilities: list[CapabilityDef]) -> list[ActionDef]:
    known = {c.id for c in capabilities}
    out: list[ActionDef] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise ManifestError("Action entries must be objects")
        action_id = str(item.get("id", "")).strip().lower()
        if not _ACTION_ID_RE.match(action_id) or "." not in action_id:
            raise ManifestError(f"Invalid action id '{action_id}'")
        if not action_id.startswith(connector_id + "."):
            raise ManifestError(f"Action '{action_id}' must be namespaced '{connector_id}.*'")
        if action_id in seen:
            raise ManifestError(f"Duplicate action '{action_id}'")
        seen.add(action_id)
        required = item.get("required_capabilities", []) or []
        if not isinstance(required, list) or not required:
            raise ManifestError(f"Action '{action_id}' needs required_capabilities")
        for capability in required:
            if capability not in known:
                raise ManifestError(
                    f"Action '{action_id}' requires unknown capability '{capability}'")
        input_schema = item.get("input_schema", {}) or {}
        if not isinstance(input_schema, dict) or input_schema.get("type") != "object":
            raise ManifestError(f"Action '{action_id}' input_schema must be a JSON object schema")
        timeout = item.get("timeout_seconds", 30)
        if not isinstance(timeout, int) or not 1 <= timeout <= 300:
            raise ManifestError(f"Action '{action_id}' timeout must be 1..300s")
        rate = item.get("rate_limit_per_minute", 60)
        if not isinstance(rate, int) or not 1 <= rate <= 10000:
            raise ManifestError(f"Action '{action_id}' rate limit must be 1..10000/min")
        verification = item.get("verification", {}) or {}
        if not isinstance(verification, dict):
            raise ManifestError(f"Action '{action_id}' verification must be an object")
        http_spec = item.get("http", {}) or {}
        if not isinstance(http_spec, dict):
            raise ManifestError(f"Action '{action_id}' http must be an object")
        if http_spec:
            method = str(http_spec.get("method", "GET")).upper()
            if method not in ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"):
                raise ManifestError(
                    f"Action '{action_id}' http.method '{method}' not allowed")
            path = str(http_spec.get("path", "") or "")
            if not path.startswith("/") or len(path) > 512 or " " in path:
                raise ManifestError(
                    f"Action '{action_id}' http.path must be a relative path")
            if ".." in path or "\\" in path:
                raise ManifestError(
                    f"Action '{action_id}' http.path must not traverse")
            extract = http_spec.get("extract", "")
            if extract and not isinstance(extract, str):
                raise ManifestError(
                    f"Action '{action_id}' http.extract must be a dotted path")
            if len(str(extract or "")) > 256:
                raise ManifestError(
                    f"Action '{action_id}' http.extract too long")
        out.append(ActionDef(
            id=action_id, name=_require_str(item, "name", f"action '{action_id}'", 120),
            description=str(item.get("description", ""))[:1000],
            input_schema=input_schema,
            output_schema=item.get("output_schema", {}) or {},
            required_capabilities=[str(c) for c in required],
            risk_level=_risk(item.get("risk_level", "MEDIUM"), f"action '{action_id}'"),
            supports_idempotency=bool(item.get("supports_idempotency", False)),
            idempotency_strategy=str(item.get("idempotency_strategy", ""))[:128],
            supports_async=bool(item.get("supports_async", False)),
            timeout_seconds=timeout, rate_limit_per_minute=rate,
            verification=verification,
            mutation=bool(item.get("mutation", True)),
            http=http_spec))
    return out


def _triggers(raw: list, connector_id: str) -> list[TriggerDef]:
    out: list[TriggerDef] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ManifestError("Trigger entries must be objects")
        trigger_id = str(item.get("id", "")).strip().lower()
        if not trigger_id.startswith(connector_id + "."):
            raise ManifestError(f"Trigger '{trigger_id}' must be namespaced '{connector_id}.*'")
        try:
            kind = TriggerKind(str(item.get("kind", "webhook")).lower())
        except ValueError:
            raise ManifestError(f"Unknown trigger kind '{item.get('kind')}'") from None
        out.append(TriggerDef(
            id=trigger_id, name=_require_str(item, "name", f"trigger '{trigger_id}'", 120),
            kind=kind, description=str(item.get("description", ""))[:1000],
            event_types=[str(e)[:128] for e in (item.get("event_types", []) or [])],
            payload_schema=item.get("payload_schema", {}) or {},
            poll_config=_validate_poll_config(
                item.get("poll_config", {}) or {}, trigger_id)))
    return out


def _validate_poll_config(raw: Any, trigger_id: str) -> dict[str, Any]:
    """Bounded polling declarations: interval floor, caps, no code refs."""
    if not raw:
        return {}
    if not isinstance(raw, dict):
        raise ManifestError(f"Trigger '{trigger_id}' poll_config must be an object")
    interval = raw.get("interval_seconds", 300)
    if not isinstance(interval, int) or not 60 <= interval <= 86400:
        raise ManifestError(
            f"Trigger '{trigger_id}' poll_config.interval_seconds must be 60..86400")
    for key in ("max_items", "max_pages"):
        if key in raw:
            value = raw[key]
            if not isinstance(value, int) or not 1 <= value <= 500:
                raise ManifestError(
                    f"Trigger '{trigger_id}' poll_config.{key} must be 1..500")
    for key in ("action", "cursor_field", "id_field"):
        if key in raw and raw[key] is not None and not isinstance(raw[key], str):
            raise ManifestError(
                f"Trigger '{trigger_id}' poll_config.{key} must be a string")
    for banned in ("code", "exec", "eval", "command", "script", "url", "base_url"):
        if banned in raw:
            raise ManifestError(
                f"Trigger '{trigger_id}' poll_config must not contain '{banned}'")
    return dict(raw)


def _resources(raw: list) -> list[ResourceDef]:
    out: list[ResourceDef] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ManifestError("Resource entries must be objects")
        kind = str(item.get("kind", "")).strip().lower()
        if kind not in NORMALIZED_RESOURCES:
            raise ManifestError(f"Unknown normalized resource '{kind}'")
        out.append(ResourceDef(kind=kind,
                               provider_kind=str(item.get("provider_kind", ""))[:128],
                               schema=item.get("schema", {}) or {}))
    return out


def manifest_hash(manifest: ConnectorManifest) -> str:
    canonical = json.dumps({
        "id": manifest.id, "version": manifest.version,
        "capabilities": sorted(c.id for c in manifest.capabilities),
        "actions": sorted(a.id for a in manifest.actions),
        "triggers": sorted(t.id for t in manifest.triggers),
    }, sort_keys=True, separators=(",", ":"))
    import hashlib
    return hashlib.sha256(canonical.encode()).hexdigest()


def manifest_to_dict(manifest: ConnectorManifest) -> dict[str, Any]:
    return {
        "id": manifest.id, "name": manifest.name, "version": manifest.version,
        "category": manifest.category, "type": manifest.connector_type.value,
        "trust": manifest.trust.value, "description": manifest.description,
        "publisher": manifest.publisher, "license": manifest.license,
        "documentation_url": manifest.documentation_url, "auth": manifest.auth,
        "capabilities": [{"id": c.id, "description": c.description,
                          "risk_level": c.risk_level.value} for c in manifest.capabilities],
        "actions": [{"id": a.id, "name": a.name, "description": a.description,
                     "input_schema": a.input_schema, "output_schema": a.output_schema,
                     "required_capabilities": a.required_capabilities,
                     "risk_level": a.risk_level.value,
                     "supports_idempotency": a.supports_idempotency,
                     "idempotency_strategy": a.idempotency_strategy,
                     "supports_async": a.supports_async,
                     "timeout_seconds": a.timeout_seconds,
                     "rate_limit_per_minute": a.rate_limit_per_minute,
                     "verification": a.verification,
                     "mutation": a.mutation, "http": a.http} for a in manifest.actions],
        "triggers": [{"id": t.id, "name": t.name, "kind": t.kind.value,
                      "description": t.description, "event_types": t.event_types,
                      "payload_schema": t.payload_schema,
                      "poll_config": t.poll_config} for t in manifest.triggers],
        "resources": [{"kind": r.kind, "provider_kind": r.provider_kind,
                       "schema": r.schema} for r in manifest.resources],
        "scopes": manifest.scopes, "rate_limits": manifest.rate_limits,
        "supported_environments": manifest.supported_environments,
        "signature": manifest.signature, "content_hash": manifest.content_hash,
    }
