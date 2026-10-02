"""MP27: enterprise security policies (§66-71), simulator (§67-68),
audit/rollback (§69-70), compliance controls (§72-74), posture (§75-76),
drift (§144-146). Versioned, explainable, never leaking internals."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from openagent.identity.types import RiskLevel

POLICY_SECTIONS = ("authentication", "mfa", "session", "network",
                    "data", "ai", "tool", "workload", "environment",
                    "incident")


@dataclass
class SecurityPolicy:
    policy_id: str = field(
        default_factory=lambda: f"spol_{uuid.uuid4().hex[:12]}")
    scope: str = "organization"  # platform|organization|project|environment
    scope_id: str = ""
    sections: dict[str, dict[str, Any]] = field(default_factory=dict)
    version: int = 1
    created_by: str = ""
    reason: str = ""

    def validate(self) -> tuple[bool, str]:
        unknown = set(self.sections) - set(POLICY_SECTIONS)
        if unknown:
            return False, f"unknown policy sections {sorted(unknown)}"
        if self.scope not in ("platform", "organization", "project",
                              "environment"):
            return False, f"unknown scope {self.scope}"
        return True, "ok"

    def get(self, section: str, key: str, default: Any = None) -> Any:
        return self.sections.get(section, {}).get(key, default)


@dataclass
class PolicyVersion:
    version_id: str = field(
        default_factory=lambda: f"spv_{uuid.uuid4().hex[:12]}")
    policy_id: str = ""
    version: int = 1
    sections: dict[str, Any] = field(default_factory=dict)
    changed_by: str = ""
    reason: str = ""
    result: str = ""


class PolicyStore:
    """Versioned policies with audited rollback."""

    def __init__(self) -> None:
        self._policies: dict[str, SecurityPolicy] = {}
        self._history: dict[str, list[PolicyVersion]] = {}
        self._audit: list[dict[str, Any]] = []

    def put(self, policy: SecurityPolicy, *, actor: str,
            reason: str = "") -> SecurityPolicy:
        ok, why = policy.validate()
        if not ok:
            raise ValueError(why)
        previous = self._policies.get(policy.policy_id)
        policy.version = (previous.version + 1) if previous else 1
        self._policies[policy.policy_id] = policy
        self._history.setdefault(policy.policy_id, []).append(
            PolicyVersion(policy_id=policy.policy_id,
                          version=policy.version,
                          sections=dict(policy.sections),
                          changed_by=actor, reason=reason, result="applied"))
        self._audit.append({"actor": actor, "policy": policy.policy_id,
                            "from": previous.version if previous else None,
                            "to": policy.version, "reason": reason,
                            "result": "applied"})
        return policy

    def rollback(self, policy_id: str, to_version: int, *,
                 actor: str, reason: str,
                 confirmed: bool = False) -> SecurityPolicy:
        history = self._history.get(policy_id, [])
        target = next((v for v in history if v.version == to_version),
                      None)
        if target is None:
            raise ValueError(f"version {to_version} not found")
        current = self._policies[policy_id]
        if to_version >= current.version:
            raise ValueError("rollback needs an older version")
        risky = to_version < current.version - 1
        if risky and not confirmed:
            raise ValueError("confirmation required for multi-step rollback")
        rolled = SecurityPolicy(
            policy_id=policy_id, scope=current.scope,
            scope_id=current.scope_id, sections=dict(target.sections),
            created_by=actor, reason=f"rollback to v{to_version}: {reason}")
        return self.put(rolled, actor=actor,
                        reason=f"rollback to v{to_version}")

    def audit(self) -> list[dict[str, Any]]:
        return list(self._audit)


# --------------------------------------------------------- simulator (§67) ---
@dataclass
class SimulationInput:
    actor: str
    action: str
    resource: str
    environment: str = ""
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class SimulationResult:
    verdict: str  # ALLOW|DENY|STEP_UP
    explanation: str
    policy_id: str = ""
    required_strength: str = ""


class PolicySimulator:
    """Safe dry-run evaluation for administrators. Read-only: never
    mutates policy, never touches real resources."""

    def __init__(self, store: PolicyStore) -> None:
        self._store = store

    def evaluate(self, policy_id: str,
                 simulation: SimulationInput) -> SimulationResult:
        policy = self._store._policies.get(policy_id)
        if policy is None:
            return SimulationResult("DENY", "Unknown policy (deny-by-default)",
                                    policy_id)
        env = simulation.environment
        mfa_required = bool(policy.get("mfa", "required", False))
        mfa_ok = bool(simulation.context.get("mfa_verified", False))
        if mfa_required and not mfa_ok:
            return SimulationResult(
                "STEP_UP", "Production environment requires MFA.",
                policy_id, required_strength="AAL2")
        env_rules = policy.sections.get("environment", {})
        denied_envs = env_rules.get("deny_environments", [])
        if env in denied_envs:
            return SimulationResult(
                "DENY", f"Action not permitted in {env}.", policy_id)
        data_rules = policy.sections.get("data", {})
        need_purpose = data_rules.get("purpose_required_for", [])
        classification = str(simulation.context.get(
            "data_classification", "PUBLIC")).upper()
        if classification in need_purpose and \
                not simulation.context.get("purpose"):
            return SimulationResult(
                "DENY",
                f"{classification} data needs an access purpose.",
                policy_id)
        return SimulationResult("ALLOW",
                                "Simulation: policy allows this action.",
                                policy_id)


# ------------------------------------------------------- compliance (§72-76) ---
CONTROL_CATEGORIES = ("Access Control", "Authentication",
                      "Data Protection", "Logging", "Monitoring",
                      "Incident Response", "Change Management",
                      "Business Continuity", "Vendor Management")


@dataclass
class SecurityControl:
    control_id: str
    name: str
    description: str = ""
    category: str = "Access Control"
    status: str = "implemented"  # implemented|partial|planned|not_applicable
    owner: str = ""
    evidence: list[dict[str, str]] = field(default_factory=list)
    mappings: dict[str, list[str]] = field(default_factory=dict)

    def validate(self) -> tuple[bool, str]:
        if self.category not in CONTROL_CATEGORIES:
            return False, f"unknown category {self.category}"
        if self.status not in ("implemented", "partial", "planned",
                               "not_applicable"):
            return False, f"unknown status {self.status}"
        return True, "ok"


def posture_report(*, mfa: str, sso: str, scim: str, audit: str,
                   ip_restrictions: str,
                   open_issues: Optional[list[str]] = None) -> dict[str, Any]:
    """Factual posture: concrete control states, never a fake score."""
    return {"MFA": mfa, "SSO": sso, "SCIM": scim, "Audit": audit,
            "IP Restrictions": ip_restrictions,
            "Open Issues": list(open_issues or [])}


def detect_drift(desired: dict[str, Any],
                 active: dict[str, Any]) -> list[dict[str, str]]:
    """Policy drift: desired vs active. Reports only — never auto-applies."""
    drifts = []
    for key, want in desired.items():
        got = active.get(key)
        if got != want:
            drifts.append({"control": key, "desired": str(want),
                           "active": str(got),
                           "message": f"Drift detected: {key} "
                                      f"desired={want} active={got}"})
    return drifts
