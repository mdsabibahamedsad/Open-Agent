"""MP27: RBAC + ABAC authorization (§23-26). Existing RBAC stays the
role foundation; ABAC attributes refine decisions. Deny-by-default:
anything undeterminable is DENY. Server-side only."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from openagent.identity.types import (
    ABAC_ATTRIBUTES, POLICY_PRECEDENCE, RiskLevel,
)


@dataclass
class AuthzRequest:
    identity_id: str
    identity_type: str
    action: str
    resource_type: str = ""
    resource_id: str = ""
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class AuthzDecision:
    allowed: bool
    reason: str = ""
    policy_ids: list[str] = field(default_factory=list)
    risk: str = RiskLevel.LOW
    conditions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        from openagent.control.observability import redact
        return {"allowed": self.allowed, "reason": self.reason,
                "policy_ids": list(self.policy_ids), "risk": self.risk,
                "conditions": list(self.conditions),
                "_redacted": bool(redact({})) is False}


PolicyFn = Callable[[AuthzRequest], Optional[AuthzDecision]]


class Authorizer:
    """Layered authorizer: platform -> org -> project -> environment ->
    resource -> request. First explicit deny wins; an allow needs at
    least one allowing policy and zero denies. Unknown -> DENY."""

    def __init__(self) -> None:
        self._layers: dict[str, list[tuple[str, PolicyFn]]] = {
            scope: [] for scope in POLICY_PRECEDENCE
        }

    def add(self, scope: str, policy_id: str, fn: PolicyFn) -> None:
        if scope not in self._layers:
            raise ValueError(f"unknown policy scope {scope}")
        self._layers[scope].append((policy_id, fn))

    def decide(self, request: AuthzRequest) -> AuthzDecision:
        allowed_by: list[str] = []
        conditions: list[str] = []
        worst_risk = RiskLevel.LOW
        rank = RiskLevel.RANK
        for scope in POLICY_PRECEDENCE:
            for policy_id, fn in self._layers[scope]:
                try:
                    decision = fn(request)
                except Exception:
                    return AuthzDecision(
                        False, f"policy {policy_id} errored (deny-by-default)",
                        [policy_id], RiskLevel.HIGH)
                if decision is None:
                    continue
                if rank.get(decision.risk, 0) > rank.get(worst_risk, 0):
                    worst_risk = decision.risk
                if not decision.allowed:
                    return AuthzDecision(
                        False, decision.reason or f"denied by {policy_id}",
                        [*allowed_by, policy_id], worst_risk)
                allowed_by.append(policy_id)
                conditions.extend(decision.conditions)
        if not allowed_by:
            return AuthzDecision(False, "no policy allows (deny-by-default)",
                                 [], worst_risk)
        return AuthzDecision(True, "allowed by policy", allowed_by,
                             worst_risk, conditions)


def rbac_allow(policy_id: str, *, permissions: set[str],
               risk: str = RiskLevel.LOW) -> PolicyFn:
    """Adapt an RBAC permission set as one authorizer layer."""
    def _check(request: AuthzRequest) -> Optional[AuthzDecision]:
        if request.action in permissions:
            return AuthzDecision(True, f"RBAC grants {request.action}",
                                 [policy_id], risk)
        return None  # abstain: other layers (ABAC) may still allow
    return _check


def abac_rule(policy_id: str, *,
              require: Optional[dict[str, Any]] = None,
              forbid: Optional[dict[str, Any]] = None,
              risk: str = RiskLevel.LOW) -> PolicyFn:
    """Attribute rule over the fixed ABAC vocabulary (§23)."""
    require = require or {}
    forbid = forbid or {}
    unknown = (set(require) | set(forbid)) - set(ABAC_ATTRIBUTES)
    if unknown:
        raise ValueError(f"unknown ABAC attributes {sorted(unknown)}")

    def _check(request: AuthzRequest) -> Optional[AuthzDecision]:
        attrs = request.attributes
        for key, want in require.items():
            if attrs.get(key) != want:
                # Required attribute unmet: explicit deny (deny-by-default),
                # never silent abstain — this is what binds resources to
                # tenants, environments, and owners.
                return AuthzDecision(
                    False, f"ABAC requires {key}={want}", [policy_id],
                    risk)
        for key, banned in forbid.items():
            if attrs.get(key) == banned:
                return AuthzDecision(
                    False, f"ABAC forbids {key}={banned}", [policy_id],
                    risk)
        if require:
            return AuthzDecision(True, "ABAC attributes satisfy rule",
                                 [policy_id], risk)
        return None
    return _check


def classification_gate(policy_id: str = "data.classification",
                        max_public_action: str = "read") -> PolicyFn:
    """SECRET/RESTRICTED data needs explicit per-request justification."""
    from openagent.identity.types import DataClassification

    def _check(request: AuthzRequest) -> Optional[AuthzDecision]:
        level = str(request.attributes.get("data_classification",
                                           "PUBLIC")).upper()
        if level in (DataClassification.SECRET, DataClassification.RESTRICTED):
            if request.action != max_public_action or \
                    not request.attributes.get("purpose"):
                return AuthzDecision(
                    False, f"{level} data needs explicit purpose",
                    [policy_id], RiskLevel.HIGH)
        return None
    return _check
