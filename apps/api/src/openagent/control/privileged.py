"""MP26: privileged actions + step-up auth + platform audit (§11-15).

Master Account is a platform identity (never just ``role=admin``):
platform permissions, platform audit trail, step-up authentication for
sensitive operations. Every privileged action records actor/action/
resource/before/after/timestamp/IP/request_id/reason/result — never
secret material.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from openagent.control.types import ActionRisk

# Operation -> risk class. Unknown operations default to SENSITIVE
# (fail-safe: stronger confirmation, never weaker).
OPERATION_RISK: dict[str, str] = {
    # Sensitive: region/quota/pool changes.
    "region.configure": ActionRisk.SENSITIVE,
    "quota.modify": ActionRisk.SENSITIVE,
    "worker_pool.modify": ActionRisk.SENSITIVE,
    "feature_flag.change": ActionRisk.SENSITIVE,
    "policy.change": ActionRisk.SENSITIVE,
    "deployment.create": ActionRisk.SENSITIVE,
    "maintenance.schedule": ActionRisk.SENSITIVE,
    # High risk: security posture changes.
    "security_policy.disable": ActionRisk.HIGH_RISK,
    "infra_config.delete": ActionRisk.HIGH_RISK,
    "credentials.rotate_critical": ActionRisk.HIGH_RISK,
    "connector.disable": ActionRisk.HIGH_RISK,
    "provider.disable": ActionRisk.HIGH_RISK,
    "region.drain": ActionRisk.HIGH_RISK,
    "rollback.execute": ActionRisk.HIGH_RISK,
    # Critical: platform-wide impact.
    "emergency.shutdown": ActionRisk.CRITICAL,
    "global_security.disable": ActionRisk.CRITICAL,
    "platform_owner.modify": ActionRisk.CRITICAL,
}


def classify_operation(operation: str) -> str:
    return OPERATION_RISK.get(operation, ActionRisk.SENSITIVE)


@dataclass
class StepUpRequirement:
    risk: str
    recent_auth_minutes: int = 0
    require_mfa: bool = False
    require_phrase: str = ""
    require_reauth: bool = False

    @staticmethod
    def for_operation(operation: str) -> "StepUpRequirement":
        risk = classify_operation(operation)
        if risk == ActionRisk.NORMAL:
            return StepUpRequirement(risk)
        if risk == ActionRisk.SENSITIVE:
            return StepUpRequirement(risk, recent_auth_minutes=30)
        if risk == ActionRisk.HIGH_RISK:
            return StepUpRequirement(risk, recent_auth_minutes=10,
                                     require_reauth=True)
        return StepUpRequirement(risk, recent_auth_minutes=5,
                                 require_mfa=True, require_reauth=True,
                                 require_phrase="CONFIRM")


def step_up_satisfied(requirement: StepUpRequirement, *,
                      last_auth_at: Optional[datetime],
                      mfa_verified: bool,
                      phrase: str = "",
                      reauthed: bool = False,
                      now: Optional[datetime] = None) -> tuple[bool, str]:
    """Verify step-up evidence. Old sessions alone never suffice."""
    moment = now or datetime.now(timezone.utc)
    if requirement.risk == ActionRisk.NORMAL:
        return True, "normal operation"
    if requirement.recent_auth_minutes:
        if last_auth_at is None:
            return False, "recent authentication required"
        age = (moment - last_auth_at).total_seconds() / 60.0
        if age > requirement.recent_auth_minutes:
            return False, "authentication too old; re-authenticate"
    if requirement.require_reauth and not reauthed:
        return False, "re-authentication required"
    if requirement.require_mfa and not mfa_verified:
        return False, "MFA verification required"
    if requirement.require_phrase and phrase != requirement.require_phrase:
        return False, "confirmation phrase mismatch"
    return True, "step-up satisfied"


@dataclass
class PrivilegedAuditRecord:
    record_id: str = field(default_factory=lambda: f"par_{uuid.uuid4().hex[:12]}")
    actor: str = ""
    action: str = ""
    resource: str = ""
    before: Any = None
    after: Any = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    ip: str = ""
    request_id: str = ""
    reason: str = ""
    result: str = ""

    def sanitized(self) -> dict[str, Any]:
        from openagent.control.observability import redact
        return {"record_id": self.record_id, "actor": self.actor,
                "action": self.action, "resource": self.resource,
                "before": redact(self.before), "after": redact(self.after),
                "timestamp": self.timestamp.isoformat(), "ip": self.ip,
                "request_id": self.request_id, "reason": self.reason,
                "result": self.result}


class AuditChain:
    """Tamper-evident in-memory audit chain (hash-linked; DB table is the
    durable store). Audit failure for critical ops fails safe per policy."""

    def __init__(self) -> None:
        self._records: list[dict[str, Any]] = []
        self._last_hash = "genesis"
        self.fail_open = False

    def append(self, record: PrivilegedAuditRecord) -> tuple[bool, str]:
        try:
            import hashlib
            import json
            body = record.sanitized()
            # Hash the FULL canonical body (not just ids): any mutation of
            # action/resource/before/after/result breaks the chain.
            canonical = json.dumps(
                {k: body[k] for k in sorted(body.keys())},
                sort_keys=True, default=str)
            digest = hashlib.sha256(
                f"{self._last_hash}:{canonical}".encode()).hexdigest()
            body["chain_hash"] = digest
            self._records.append(body)
            self._last_hash = digest
            return True, digest
        except Exception as exc:
            if self.fail_open:
                return True, f"audit degraded: {exc}"
            return False, f"audit write failed (fail-safe): {exc}"

    def verify(self) -> tuple[bool, str]:
        import hashlib
        import json
        prev = "genesis"
        for body in self._records:
            stored = body.get("chain_hash", "")
            canonical = json.dumps(
                {k: v for k, v in body.items() if k != "chain_hash"},
                sort_keys=True, default=str)
            expect = hashlib.sha256(
                f"{prev}:{canonical}".encode()).hexdigest()
            if stored != expect:
                return False, f"chain broken at {body['record_id']}"
            prev = stored
        return True, f"chain intact ({len(self._records)} records)"

    def records(self) -> list[dict[str, Any]]:
        return list(self._records)
