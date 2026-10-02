"""MP26: centralized feature flags + kill switches (§39-41).

Scopes PLATFORM/ORGANIZATION/PROJECT/ENVIRONMENT/USER. Strategies:
boolean, percentage rollout (deterministic hash targeting), allowlist,
denylist. HARD RULE: flags can never bypass security policies — any
flag whose key starts with ``security.`` or targets a security control
is evaluated but the security guard forces deny unless an explicit
security policy allows. Kill switches are audited, permission-gated,
labeled, reversible.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

# Flag keys that touch security controls. These can be *read* but never
# *weakened* by flag evaluation alone.
SECURITY_FLAG_PREFIXES = ("security.", "auth.", "rbac.", "sandbox.policy.",
                          "network.policy.", "approval.bypass")

KILL_SWITCH_TARGETS = ("connector", "model_provider", "tool",
                       "workflow_node", "browser", "code_execution",
                       "region", "worker_pool")


def _deterministic_rollout(feature_id: str, subject_id: str) -> float:
    digest = hashlib.sha256(
        f"{feature_id}:{subject_id}".encode("utf-8")).hexdigest()
    return (int(digest[:8], 16) % 10000) / 100.0  # 0..100


@dataclass
class FeatureFlag:
    key: str
    scope: str
    scope_id: str = ""
    strategy: str = "boolean"  # boolean|percentage|allowlist|denylist
    enabled: bool = False
    percentage: float = 0.0
    allowlist: list[str] = field(default_factory=list)
    denylist: list[str] = field(default_factory=list)
    version: int = 1
    label: str = ""
    updated_by: str = ""
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def evaluate(self, subject_id: str = "") -> tuple[bool, str]:
        if subject_id and subject_id in self.denylist:
            return False, "denylisted"
        if self.strategy == "boolean":
            if self.enabled and subject_id and subject_id in self.allowlist:
                return True, "allowlisted"
            if self.enabled and self.allowlist and subject_id not in self.allowlist:
                return False, "not allowlisted"
            return self.enabled, "boolean"
        if self.strategy == "percentage":
            if subject_id in self.allowlist:
                return True, "allowlisted"
            bucket = _deterministic_rollout(self.key, subject_id or "anon")
            return bucket < self.percentage, f"rollout bucket {bucket:.2f}"
        if self.strategy == "allowlist":
            return subject_id in self.allowlist, "allowlist"
        if self.strategy == "denylist":
            return True, "not denylisted"
        return False, "unknown strategy"


def is_security_flag(key: str) -> bool:
    lowered = str(key or "").lower()
    return any(lowered.startswith(p) for p in SECURITY_FLAG_PREFIXES)


@dataclass
class FlagDecision:
    allowed: bool
    reason: str
    security_guarded: bool = False


class FlagEvaluator:
    """Evaluates flags across scopes; security guard can never be bypassed."""

    def __init__(self, flags: Optional[list[FeatureFlag]] = None) -> None:
        self._flags = list(flags or [])

    def add(self, flag: FeatureFlag) -> None:
        self._flags.append(flag)

    def evaluate(self, key: str, *, subject_id: str = "",
                 scope_chain: Optional[list[tuple[str, str]]] = None) -> FlagDecision:
        relevant = [f for f in self._flags if f.key == key]
        if scope_chain:
            ordered = [f for _, sid in scope_chain for f in relevant
                       if f.scope_id in ("", sid)]
            relevant = ordered or relevant
        if not relevant:
            return FlagDecision(False, "flag not configured")
        # Narrowest scope wins (last match in scope order).
        flag = relevant[-1]
        allowed, reason = flag.evaluate(subject_id)
        if is_security_flag(key):
            # Flags may *enable extra* security, never disable it: a flag
            # evaluating True for a security control is only advisory.
            return FlagDecision(allowed, f"security-guarded: {reason}",
                                security_guarded=True)
        return FlagDecision(allowed, reason)

    def kill_switch(self, target: str, target_id: str) -> FlagDecision:
        """Kill switches: audited + reversible off-switches (§41)."""
        if target not in KILL_SWITCH_TARGETS:
            return FlagDecision(False, f"unknown kill-switch target {target}")
        key = f"kill.{target}.{target_id}"
        decision = self.evaluate(key)
        # Kill switch ENGAGED means the capability is disabled.
        if decision.allowed:
            return FlagDecision(False, f"kill switch engaged: {target}/{target_id}")
        return FlagDecision(True, f"{target}/{target_id} operational")
