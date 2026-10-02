"""MP26: unified resource model + hierarchy (§5-6).

One ownership abstraction for every platform resource. Permissions
inherit Platform -> Organization -> Project -> Environment following the
existing RBAC rules (this module computes the inheritance path; the
AuthorizationService remains the enforcement point — never duplicated).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from openagent.control.types import RESOURCE_TYPES


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class ResourceRef:
    """Canonical resource handle (control-plane view, never a second store)."""

    id: str
    type: str
    organization_id: str = ""
    project_id: str = ""
    environment: str = ""
    owner_id: str = ""
    status: str = ""
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> tuple[bool, str]:
        if self.type not in RESOURCE_TYPES:
            return False, f"unknown resource type {self.type}"
        if not self.id:
            return False, "resource id is required"
        org_scoped = self.type not in ("organization", "region", "storage")
        if org_scoped and not self.organization_id:
            return False, f"{self.type} requires organization_id"
        return True, "ok"


@dataclass
class HierarchyPath:
    platform: str = "platform"
    organization_id: str = ""
    project_id: str = ""
    environment: str = ""

    def scopes(self) -> list[tuple[str, str]]:
        """Ordered broad -> narrow scope chain for permission inheritance."""
        chain = [("platform", self.platform)]
        if self.organization_id:
            chain.append(("organization", self.organization_id))
        if self.project_id:
            chain.append(("project", self.project_id))
        if self.environment:
            chain.append(("environment", self.environment))
        return chain


def hierarchy_for(resource: ResourceRef) -> HierarchyPath:
    return HierarchyPath(organization_id=resource.organization_id,
                         project_id=resource.project_id,
                         environment=resource.environment)


def permission_scope_chain(path: HierarchyPath) -> list[str]:
    """Scope strings a grant at any level resolves against, broad first."""
    scopes = ["platform"]
    if path.organization_id:
        scopes.append(f"org:{path.organization_id}")
    if path.project_id:
        scopes.append(f"project:{path.project_id}")
    if path.environment:
        scopes.append(f"env:{path.environment}")
    return scopes


def check_inheritance(grant_scope: str, required: HierarchyPath) -> bool:
    """A broad grant covers narrower resources; never the reverse."""
    chain = permission_scope_chain(required)
    if grant_scope == "platform":
        return True
    if grant_scope.startswith("org:"):
        gid = grant_scope[4:]
        return required.organization_id == gid
    if grant_scope.startswith("project:"):
        pid = grant_scope[8:]
        return required.project_id == pid
    if grant_scope.startswith("env:"):
        env = grant_scope[4:]
        return required.environment == env
    _ = chain
    return False


def environment_isolated(resource_env: str, credential_env: str) -> bool:
    """Production credentials never leak into development and vice versa."""
    if not resource_env or not credential_env:
        return False
    return resource_env == credential_env
