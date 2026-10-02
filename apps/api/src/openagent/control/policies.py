"""MP26: policy integration (§9-10) + environments (§7).

No new policy engine: a common resolution interface chains the EXISTING
engines (RBAC authorization, sandbox profiles, connector policies,
approval policies, commerce entitlements) and returns a normalized
decision. Secrets never flow into decisions exposed to models.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from openagent.control.types import EnvironmentName, RiskLevel

ENVIRONMENT_POLICIES = ("execution", "model", "tool", "connector",
                        "network", "sandbox", "region", "quota",
                        "secret", "retention")


@dataclass
class PolicyDecision:
    allowed: bool
    reason: str = ""
    policy_id: str = ""
    policy_version: str = ""
    risk_level: str = RiskLevel.LOW
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from openagent.control.observability import redact
        return {"allowed": self.allowed, "reason": self.reason,
                "policy_id": self.policy_id,
                "policy_version": self.policy_version,
                "risk_level": self.risk_level,
                "metadata": redact(dict(self.metadata))}

    @classmethod
    def deny(cls, reason: str, **kwargs: Any) -> "PolicyDecision":
        return cls(allowed=False, reason=reason, **kwargs)

    @classmethod
    def allow(cls, reason: str = "policy allows", **kwargs: Any) -> "PolicyDecision":
        return cls(allowed=True, reason=reason, **kwargs)


PolicyCheck = Callable[[dict[str, Any]], PolicyDecision]


class PolicyResolver:
    """Chains registered checks; first deny wins (fail-closed default)."""

    def __init__(self, checks: Optional[list[tuple[str, PolicyCheck]]] = None,
                 fail_closed: bool = True) -> None:
        self._checks = list(checks or [])
        self.fail_closed = fail_closed

    def register(self, policy_id: str, check: PolicyCheck) -> None:
        self._checks.append((policy_id, check))

    def decide(self, context: dict[str, Any]) -> PolicyDecision:
        if not self._checks:
            if self.fail_closed:
                return PolicyDecision.deny("no policy checks registered")
            return PolicyDecision.allow("no policies configured (fail-open)")
        for policy_id, check in self._checks:
            try:
                decision = check(context)
            except Exception as exc:
                if self.fail_closed:
                    return PolicyDecision.deny(
                        f"policy {policy_id} errored (fail-closed)",
                        policy_id=policy_id, risk_level=RiskLevel.HIGH)
                continue
            decision.policy_id = decision.policy_id or policy_id
            if not decision.allowed:
                return decision
        return PolicyDecision.allow("all policies allow")


def environment_allows(*, resource_env: str, target_env: str) -> PolicyDecision:
    """Block accidental prod/dev mixing (§7)."""
    if resource_env not in EnvironmentName.ALL or target_env not in EnvironmentName.ALL:
        return PolicyDecision.deny("unknown environment",
                                   risk_level=RiskLevel.HIGH)
    if resource_env != target_env:
        return PolicyDecision.deny(
            f"environment mismatch: {resource_env} vs {target_env}",
            risk_level=RiskLevel.HIGH)
    return PolicyDecision.allow("environment matches")


@dataclass
class AsyncPolicyResolver:
    checks: list[tuple[str, Callable[[dict[str, Any]], Awaitable[PolicyDecision]]]] = field(
        default_factory=list)
    fail_closed: bool = True

    def register(self, policy_id: str, check: Any) -> None:
        self.checks.append((policy_id, check))

    async def decide(self, context: dict[str, Any]) -> PolicyDecision:
        for policy_id, check in self.checks:
            try:
                decision = await check(context)
            except Exception:
                if self.fail_closed:
                    return PolicyDecision.deny(
                        f"policy {policy_id} errored (fail-closed)",
                        policy_id=policy_id, risk_level=RiskLevel.HIGH)
                continue
            decision.policy_id = decision.policy_id or policy_id
            if not decision.allowed:
                return decision
        if not self.checks and self.fail_closed:
            return PolicyDecision.deny("no policy checks registered")
        return PolicyDecision.allow("all policies allow")
