"""MP26: enterprise controls (§47-63) — IP policy, session policy,
API-key governance, service accounts, secret rotation, data
classification/retention, policy presets, private runtime enrollment,
abuse signals, compliance hooks. Integrates existing models; adds only
missing control logic.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from openagent.control.types import DataClassification


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ------------------------------------------------------- IP policy (§48) ---
def ip_allowed(ip: str, *, allowlist: list[str],
               denylist: list[str]) -> tuple[bool, str]:
    """CIDR allow/deny. Empty allowlist = allow (feature is opt-in)."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False, "invalid source IP"
    for rule in denylist:
        try:
            if addr in ipaddress.ip_network(rule, strict=False):
                return False, f"denied by {rule}"
        except ValueError:
            continue
    if not allowlist:
        return True, "no allowlist configured"
    for rule in allowlist:
        try:
            if addr in ipaddress.ip_network(rule, strict=False):
                return True, f"allowed by {rule}"
        except ValueError:
            continue
    return False, "not in allowlist"


def trusted_source_ip(*, forwarded_for: str = "",
                      remote_addr: str = "",
                      trusted_proxies: list[str] | None = None) -> str:
    """Never trust client-supplied headers unless via trusted proxy chain."""
    proxies = trusted_proxies or []
    if not proxies:
        return remote_addr  # direct connection: only socket address counts
    try:
        remote = ipaddress.ip_address(remote_addr)
    except ValueError:
        return ""
    trusted = False
    for proxy in proxies:
        try:
            if remote in ipaddress.ip_network(proxy, strict=False):
                trusted = True
                break
        except ValueError:
            continue
    if not trusted:
        return remote_addr
    first = (forwarded_for.split(",")[0] or "").strip()
    try:
        ipaddress.ip_address(first)
        return first
    except ValueError:
        return remote_addr


# ------------------------------------------------- session policy (§49) ---
@dataclass
class SessionPolicy:
    lifetime_minutes: int = 60 * 24 * 7
    idle_timeout_minutes: int = 60
    max_concurrent: int = 5
    force_logout: bool = False

    def validate(self) -> tuple[bool, str]:
        if self.lifetime_minutes <= 0 or self.idle_timeout_minutes <= 0:
            return False, "lifetimes must be positive"
        if self.idle_timeout_minutes > self.lifetime_minutes:
            return False, "idle timeout cannot exceed lifetime"
        if self.max_concurrent < 1:
            return False, "max_concurrent must be >= 1"
        return True, "ok"

    def expired(self, created_at: datetime, last_seen: datetime,
                now: Optional[datetime] = None) -> tuple[bool, str]:
        moment = now or _utcnow()
        if self.force_logout:
            return True, "forced logout"
        if moment - created_at > timedelta(minutes=self.lifetime_minutes):
            return True, "session lifetime exceeded"
        if moment - last_seen > timedelta(minutes=self.idle_timeout_minutes):
            return True, "session idle timeout"
        return False, "active"


# ------------------------------------------------ API key governance (§50) ---
@dataclass
class ApiKeyPolicy:
    require_expiry: bool = False
    max_lifetime_days: int = 365
    require_scopes: bool = True

    def validate_new(self, *, scopes: list[str],
                     expires_at: Optional[datetime],
                     now: Optional[datetime] = None) -> tuple[bool, str]:
        moment = now or _utcnow()
        if self.require_scopes and not scopes:
            return False, "scopes are required"
        if self.require_expiry and expires_at is None:
            return False, "expiration is required"
        if expires_at is not None:
            if expires_at <= moment:
                return False, "expiration must be in the future"
            if (expires_at - moment).days > self.max_lifetime_days:
                return False, f"lifetime exceeds {self.max_lifetime_days}d"
        return True, "ok"


def key_preview(prefix: str, last_used_at: Optional[datetime]) -> dict[str, Any]:
    """Safe key descriptor — raw values never leave creation response."""
    return {"prefix": prefix,
            "last_used": last_used_at.isoformat() if last_used_at else None}


# ------------------------------------------- service accounts (§51) ---
@dataclass
class ServiceAccountPolicy:
    allowed_scopes: list[str] = field(default_factory=list)
    max_lifetime_days: int = 365
    require_environment: bool = True

    def validate(self, *, scopes: list[str], environment: str = "",
                 expires_at: Optional[datetime] = None) -> tuple[bool, str]:
        unknown = [s for s in scopes if s not in self.allowed_scopes]
        if unknown:
            return False, f"scopes outside minimum-privilege set: {unknown}"
        if self.require_environment and not environment:
            return False, "environment binding is required"
        if expires_at is not None and expires_at <= _utcnow():
            return False, "expiration must be in the future"
        return True, "ok"


# ---------------------------------------------- secret rotation (§52) ---
ROTATION_STAGES = ("created", "propagating", "verifying", "retired", "failed")


@dataclass
class RotationJob:
    job_id: str = field(default_factory=lambda: f"rot_{uuid.uuid4().hex[:12]}")
    kind: str = ""  # credential|api_key|service_identity|cloud_secret
    ref: str = ""
    stage: str = "created"
    created_at: datetime = field(default_factory=_utcnow)
    verified_at: Optional[datetime] = None
    error: str = ""

    def advance(self, ok: bool, error: str = "") -> tuple[bool, str]:
        order = list(ROTATION_STAGES)
        if self.stage in ("retired", "failed"):
            return False, f"rotation already {self.stage}"
        if not ok:
            # Old secret stays live: rotation fails WITHOUT downtime.
            self.stage = "failed"
            self.error = error
            detail = f"{error} — old secret retained, no downtime" if error \
                else "rotation step failed — old secret retained, no downtime"
            return False, detail
        idx = order.index(self.stage)
        self.stage = order[min(idx + 1, order.index("retired"))]
        if self.stage == "retired":
            self.verified_at = _utcnow()
        return True, f"advanced to {self.stage}"


# ------------------------------- classification + retention (§53-54) ---
def classify(content_hint: str, requested: str = "") -> str:
    if requested in DataClassification.ALL:
        return requested
    lowered = content_hint.lower()
    if any(w in lowered for w in ("ssn", "private key", "biometric", "health record")):
        return DataClassification.RESTRICTED
    if any(w in lowered for w in ("credential", "token", "salary", "contract",
                                   "password", "secret")):
        return DataClassification.CONFIDENTIAL
    if any(w in lowered for w in ("internal", "employee", "roadmap")):
        return DataClassification.INTERNAL
    return DataClassification.PUBLIC


def merge_retention(platform_minimums: dict[str, int],
                    org_policy: dict[str, int]) -> tuple[dict[str, int], list[str]]:
    """Org policy applies, but platform minimums can never be bypassed."""
    merged: dict[str, int] = {}
    clamped: list[str] = []
    for resource, minimum in platform_minimums.items():
        wanted = org_policy.get(resource, minimum)
        if wanted < minimum:
            merged[resource] = minimum
            clamped.append(resource)
        else:
            merged[resource] = wanted
    for resource, wanted in org_policy.items():
        merged.setdefault(resource, wanted)
    return merged, clamped


# ------------------------------------------------ policy presets (§57) ---
POLICY_PRESETS: dict[str, dict[str, Any]] = {
    "standard": {"network_policy": "ALLOWLIST", "session_lifetime_minutes": 10080,
                 "mfa_required": False, "ip_restrictions": False,
                 "retention_days": 90, "audit_level": "standard"},
    "strict": {"network_policy": "RESTRICTED", "session_lifetime_minutes": 1440,
               "mfa_required": True, "ip_restrictions": True,
               "retention_days": 180, "audit_level": "detailed"},
    "high_security": {"network_policy": "INTERNAL_ONLY",
                      "session_lifetime_minutes": 480, "mfa_required": True,
                      "ip_restrictions": True, "retention_days": 365,
                      "audit_level": "detailed", "data_residency": "PRIVATE_REGION"},
}


def apply_preset(name: str, overrides: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    base = POLICY_PRESETS.get(name)
    if base is None and name != "custom":
        raise ValueError(f"unknown policy preset {name}")
    merged = dict(base or {})
    merged.update(overrides or {})
    return merged


# --------------------------------------- private runtime (§58-61) ---
@dataclass
class PrivateEnrollment:
    enrollment_id: str = field(default_factory=lambda: f"enr_{uuid.uuid4().hex[:12]}")
    organization_id: str = ""
    # One-time bootstrap token (hash stored; raw shown once, never again).
    token_hash: str = ""
    expires_at: datetime = field(default_factory=lambda: _utcnow() + timedelta(hours=1))
    used: bool = False
    worker_id: str = ""

    @staticmethod
    def mint(organization_id: str, ttl_hours: int = 1) -> tuple["PrivateEnrollment", str]:
        raw = f"enr_{secrets.token_hex(24)}"
        digest = hashlib.sha256(raw.encode()).hexdigest()
        enrollment = PrivateEnrollment(
            organization_id=organization_id, token_hash=digest,
            expires_at=_utcnow() + timedelta(hours=max(1, ttl_hours)))
        return enrollment, raw

    def redeem(self, raw_token: str, worker_id: str,
               now: Optional[datetime] = None) -> tuple[bool, str]:
        moment = now or _utcnow()
        if self.used:
            return False, "enrollment token already used"
        if moment > self.expires_at:
            return False, "enrollment token expired"
        digest = hashlib.sha256(raw_token.encode()).hexdigest()
        if not hmac.compare_digest(digest, self.token_hash):
            return False, "invalid enrollment token"
        self.used = True
        self.worker_id = worker_id
        return True, "enrolled (short-lived identity issued)"


# --------------------------------------------- abuse signals (§43) ---
ABUSE_SIGNALS = ("execution_volume_spike", "api_request_spike",
                 "credential_abuse", "auth_failure_spike",
                 "resource_exhaustion", "suspicious_tool_usage",
                 "abnormal_egress", "artifact_creation_spike")


def risk_score(signals: dict[str, float],
               weights: Optional[dict[str, float]] = None) -> dict[str, Any]:
    """Operational risk signal (0..1). Never auto-accuses from one signal."""
    weights = weights or {}
    total_w, weighted = 0.0, 0.0
    for signal, strength in signals.items():
        if signal not in ABUSE_SIGNALS:
            continue
        w = weights.get(signal, 1.0)
        total_w += w
        weighted += w * min(1.0, max(0.0, float(strength)))
    score = (weighted / total_w) if total_w else 0.0
    active = [s for s, v in signals.items() if float(v) >= 0.7 and s in ABUSE_SIGNALS]
    level = "LOW"
    if score >= 0.8 and len(active) >= 2:
        level = "HIGH"
    elif score >= 0.5:
        level = "MEDIUM"
    return {"score": round(score, 3), "level": level,
            "signals": len(active),
            "note": "operational signal only; requires human review"}


# ------------------------------------------ compliance hooks (§62) ---
COMPLIANCE_FRAMEWORKS = ("SOC2", "ISO27001", "GDPR")


def compliance_checklist(framework: str) -> dict[str, Any]:
    """Technical-foundation checklist. NEVER a certification claim."""
    if framework not in COMPLIANCE_FRAMEWORKS:
        raise ValueError(f"unknown framework {framework}")
    return {"framework": framework,
            "certified": False,
            "disclaimer": "technical foundations only; no certification claimed",
            "controls": {"audit_trail": True, "data_residency": True,
                         "retention": True, "access_review": True,
                         "log_redaction": True, "encryption": "configurable"}}
