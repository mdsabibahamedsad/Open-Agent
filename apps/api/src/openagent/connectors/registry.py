"""Connector registry: definitions, versions, capability discovery (MP21).

Definitions are loaded lazily and cached: discovery, search, and schema
loading never pull every connector into memory at once.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

import structlog

from openagent.connectors.manifest import (
    ManifestError,
    manifest_to_dict,
    validate_manifest,
)
from openagent.connectors.types import (
    ConnectorManifest,
    ConnectorStatus,
    ConnectorType,
    TrustTier,
    can_transition_connector,
)

logger = structlog.get_logger("openagent.connectors.registry")


class RegistryError(Exception):
    def __init__(self, message: str, code: str = "REGISTRY_ERROR"):
        super().__init__(message)
        self.code = code


class ConnectorRegistry:
    """In-memory definition registry. Persistence lives in DB tables;
    this registry is the execution-time view (populated at startup/sync)."""

    def __init__(self):
        self._manifests: dict[str, ConnectorManifest] = {}
        self._status: dict[str, ConnectorStatus] = {}
        self._capability_index: dict[str, str] = {}  # capability_id -> connector_id
        self._action_index: dict[str, tuple[str, str]] = {}  # action_id -> (connector, version)
        self._loaders: dict[str, Callable[[], dict[str, Any]]] = {}

    # -- registration ------------------------------------------------------
    def register_manifest(self, raw: dict[str, Any],
                          status: ConnectorStatus = ConnectorStatus.ACTIVE) -> ConnectorManifest:
        manifest = validate_manifest(raw)
        existing = self._manifests.get(manifest.id)
        if existing is not None and existing.content_hash == manifest.content_hash:
            return existing
        self._manifests[manifest.id] = manifest
        self._status[manifest.id] = status
        for capability in manifest.capabilities:
            self._capability_index[capability.id] = manifest.id
        for action in manifest.actions:
            self._action_index[action.id] = (manifest.id, manifest.version)
        logger.info("connector registered", connector=manifest.id,
                    version=manifest.version)
        return manifest

    def register_loader(self, connector_id: str,
                        loader: Callable[[], dict[str, Any]]) -> None:
        """Lazy manifest loading: fetched only when first requested."""
        self._loaders[connector_id] = loader

    def unregister(self, connector_id: str) -> bool:
        manifest = self._manifests.pop(connector_id, None)
        if manifest is None:
            self._loaders.pop(connector_id, None)
            return False
        self._status.pop(connector_id, None)
        for capability in manifest.capabilities:
            self._capability_index.pop(capability.id, None)
        for action in manifest.actions:
            self._action_index.pop(action.id, None)
        self._loaders.pop(connector_id, None)
        return True

    def set_status(self, connector_id: str, to: ConnectorStatus) -> None:
        manifest = self.get(connector_id)
        if manifest is None:
            raise RegistryError(f"Unknown connector '{connector_id}'", code="NOT_FOUND")
        frm = self._status.get(connector_id, ConnectorStatus.DRAFT)
        if not can_transition_connector(frm, to):
            raise RegistryError(f"Illegal transition {frm.value} -> {to.value}",
                                code="ILLEGAL_TRANSITION")
        self._status[connector_id] = to

    # -- discovery (lazy, cached) -------------------------------------------
    def get(self, connector_id: str) -> Optional[ConnectorManifest]:
        manifest = self._manifests.get(connector_id)
        if manifest is not None:
            return manifest
        loader = self._loaders.get(connector_id)
        if loader is None:
            return None
        try:
            return self.register_manifest(loader())
        except ManifestError as exc:
            logger.warning("connector lazy load failed", connector=connector_id,
                           error=str(exc))
            return None

    def list(self, *, category: Optional[str] = None,
             connector_type: Optional[ConnectorType] = None,
             trust: Optional[TrustTier] = None,
             status: Optional[ConnectorStatus] = None,
             include_disabled: bool = False) -> list[ConnectorManifest]:
        out = []
        for connector_id, manifest in self._manifests.items():
            state = self._status.get(connector_id, ConnectorStatus.DRAFT)
            if state == ConnectorStatus.DISABLED and not include_disabled:
                continue
            if status is not None and state != status:
                continue
            if category is not None and manifest.category != category:
                continue
            if connector_type is not None and manifest.connector_type != connector_type:
                continue
            if trust is not None and manifest.trust != trust:
                continue
            out.append(manifest)
        return sorted(out, key=lambda m: m.id)

    def search(self, query: str, *, limit: int = 20) -> list[ConnectorManifest]:
        needle = (query or "").strip().lower()
        if not needle:
            return []
        scored: list[tuple[int, ConnectorManifest]] = []
        for manifest in self._manifests.values():
            if self._status.get(manifest.id) == ConnectorStatus.DISABLED:
                continue
            haystack = f"{manifest.id} {manifest.name} {manifest.description} {manifest.category}"
            if needle == manifest.id:
                scored.append((0, manifest))
            elif needle in manifest.id or needle in manifest.name.lower():
                scored.append((1, manifest))
            elif needle in haystack.lower():
                scored.append((2, manifest))
        scored.sort(key=lambda item: (item[0], item[1].id))
        return [manifest for _, manifest in scored[:max(1, limit)]]

    # -- capability / action discovery (compact, least-privilege) ------------
    def capability_owner(self, capability_id: str) -> Optional[str]:
        return self._capability_index.get(capability_id)

    def action_owner(self, action_id: str) -> Optional[tuple[str, str]]:
        return self._action_index.get(action_id)

    def search_actions(self, query: str, *,
                       limit: int = 10) -> list[dict[str, Any]]:
        """Compact agent-facing descriptors — never full documentation dumps."""
        needle = (query or "").strip().lower().replace(" ", "_")
        if not needle:
            return []
        out: list[dict[str, Any]] = []
        for manifest in self._manifests.values():
            if self._status.get(manifest.id) == ConnectorStatus.DISABLED:
                continue
            for action in manifest.actions:
                haystack = f"{action.id} {action.name} {action.description}".lower()
                if needle in action.id.lower().replace(".", "_") or needle in haystack:
                    out.append({
                        "action": action.id,
                        "description": (action.description or action.name)[:160],
                        "risk_level": action.risk_level.value,
                        "connector": manifest.id,
                        "trust": manifest.trust.value,
                    })
                    if len(out) >= max(1, limit):
                        return out
        return out

    def action_definition(self, action_id: str) -> Optional[dict[str, Any]]:
        owner = self._action_index.get(action_id)
        if owner is None:
            return None
        manifest = self._manifests.get(owner[0])
        if manifest is None:
            return None
        for action in manifest.actions:
            if action.id == action_id:
                return {"connector": manifest.id, "version": manifest.version,
                        "trust": manifest.trust.value,
                        "action": manifest_to_dict(manifest)["actions"][
                            [a.id for a in manifest.actions].index(action_id)]}
        return None

    def to_dict(self, manifest: ConnectorManifest) -> dict[str, Any]:
        data = manifest_to_dict(manifest)
        data["status"] = self._status.get(manifest.id, ConnectorStatus.DRAFT).value
        return data


registry = ConnectorRegistry()
