"""MP27: workload identity + credential broker (§43-47).

Every workload (worker, sandbox, browser, code run, scheduled task,
connector execution) gets a scoped, short-lived credential. The broker
resolves authorized credentials from the EXISTING credential store,
issues leases, redacts output, audits usage, and revokes. Raw secrets
(API keys, refresh tokens, private keys, DB passwords, cloud creds,
cookies) NEVER reach models — tools receive them only through the
controlled execution boundary.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

WORKLOAD_KINDS = ("worker", "sandbox", "browser", "code_execution",
                  "scheduled_task", "connector_execution")

MODEL_FORBIDDEN_HINTS = ("api_key", "refresh_token", "private_key",
                         "db_password", "database_url", "cloud_credential",
                         "session_cookie", "oauth_token", "secret_key")


@dataclass
class WorkloadIdentity:
    workload_id: str = field(
        default_factory=lambda: f"wkl_{uuid.uuid4().hex[:12]}")
    kind: str = "worker"
    organization_id: str = ""
    execution_id: str = ""
    region: str = ""
    pool: str = ""
    scopes: list[str] = field(default_factory=list)
    issued_at: float = field(default_factory=time.time)
    expires_at: float = 0.0
    revoked: bool = False

    def validate(self) -> tuple[bool, str]:
        if self.kind not in WORKLOAD_KINDS:
            return False, f"unknown workload kind {self.kind}"
        if not self.organization_id or not self.execution_id:
            return False, "workload needs organization_id + execution_id"
        return True, "ok"

    def live(self, now: Optional[float] = None) -> tuple[bool, str]:
        moment = now if now is not None else time.time()
        if self.revoked:
            return False, "workload identity revoked"
        if self.expires_at and moment >= self.expires_at:
            return False, "workload credential expired"
        return True, "live"


@dataclass
class CredentialLease:
    lease_id: str = field(
        default_factory=lambda: f"cls_{uuid.uuid4().hex[:12]}")
    workload_id: str = ""
    credential_ref: str = ""  # reference only, never the value
    scopes: list[str] = field(default_factory=list)
    issued_at: float = field(default_factory=time.time)
    expires_at: float = 0.0
    uses: int = 0
    max_uses: int = 1
    revoked: bool = False

    def usable(self, now: Optional[float] = None) -> tuple[bool, str]:
        moment = now if now is not None else time.time()
        if self.revoked:
            return False, "lease revoked"
        if self.expires_at and moment >= self.expires_at:
            return False, "lease expired"
        if self.uses >= self.max_uses:
            return False, "lease exhausted"
        return True, "usable"


def assert_model_safe(payload: Any) -> Any:
    """Boundary guard: anything model-bound must not carry raw secrets."""
    if isinstance(payload, dict):
        for key, value in payload.items():
            lowered = str(key).lower()
            if any(hint in lowered for hint in MODEL_FORBIDDEN_HINTS):
                raise ValueError(
                    f"secret-bearing field {key!r} blocked from model context")
            assert_model_safe(value)
    elif isinstance(payload, (list, tuple)):
        for item in payload:
            assert_model_safe(item)
    return payload


class CredentialBroker:
    """Issues and polices short-lived credential leases."""

    def __init__(self, default_ttl_seconds: float = 600.0) -> None:
        self.default_ttl = default_ttl_seconds
        self._leases: dict[str, CredentialLease] = {}
        self._audit: list[dict[str, Any]] = []

    def _log(self, event: str, **fields: Any) -> None:
        from openagent.control.observability import redact
        entry = {"event": event, "at": time.time()}
        entry.update(redact(fields))
        self._audit.append(entry)

    def issue(self, workload: WorkloadIdentity, credential_ref: str,
              *, scopes: Optional[list[str]] = None,
              credential_org: str = "",
              ttl_seconds: float = 0.0,
              max_uses: int = 1) -> CredentialLease:
        ok, reason = workload.live()
        if not ok:
            raise ValueError(f"workload not live: {reason}")
        if credential_org and credential_org != workload.organization_id:
            # A worker must not freely request another org's resources.
            raise ValueError(
                "credential organization does not match workload "
                "organization")
        wanted = set(scopes or [])
        allowed = set(workload.scopes)
        if not wanted.issubset(allowed):
            raise ValueError(
                f"lease scopes exceed workload grant: "
                f"{sorted(wanted - allowed)}")
        lease = CredentialLease(
            workload_id=workload.workload_id,
            credential_ref=credential_ref,
            scopes=sorted(wanted),
            expires_at=time.time() + (ttl_seconds or self.default_ttl),
            max_uses=max(1, max_uses))
        self._leases[lease.lease_id] = lease
        self._log("credential.leased", workload=workload.workload_id,
                  ref=credential_ref, scopes=lease.scopes)
        return lease

    def consume(self, lease_id: str) -> CredentialLease:
        lease = self._leases.get(lease_id)
        if lease is None:
            raise ValueError("unknown credential lease")
        ok, reason = lease.usable()
        if not ok:
            raise ValueError(reason)
        lease.uses += 1
        self._log("credential.used", lease=lease_id, uses=lease.uses)
        return lease

    def revoke(self, lease_id: str, reason: str = "") -> bool:
        lease = self._leases.get(lease_id)
        if lease is None:
            return False
        lease.revoked = True
        self._log("credential.revoked", lease=lease_id, reason=reason)
        return True

    def revoke_workload(self, workload_id: str) -> int:
        count = 0
        for lease in self._leases.values():
            if lease.workload_id == workload_id and not lease.revoked:
                lease.revoked = True
                count += 1
        self._log("workload.revoked", workload=workload_id,
                  leases=count)
        return count

    def audit(self) -> list[dict[str, Any]]:
        return list(self._audit)
