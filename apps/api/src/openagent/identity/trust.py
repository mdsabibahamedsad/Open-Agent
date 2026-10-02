"""MP27: devices, session risk, auth strength, revocation (§29-33,
§38-39). Extends existing sessions (device association, strength,
risk, revocation reason). Revocation is prompt: a version counter
invalidates cached session state instead of waiting out TTLs."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from openagent.identity.types import (
    AuthStrength, DeviceTrust, RiskLevel, strength_meets,
)


def _utcnow() -> float:
    return time.time()


# ---------------------------------------------------------------- devices ---
@dataclass
class Device:
    device_id: str = field(default_factory=lambda: f"dvc_{uuid.uuid4().hex[:12]}")
    user_id: str = ""
    type: str = ""       # desktop|mobile|tablet|api|unknown (minimal data)
    platform: str = ""
    browser: str = ""
    trust: str = DeviceTrust.UNKNOWN
    first_seen: float = field(default_factory=_utcnow)
    last_seen: float = field(default_factory=_utcnow)
    revoked_at: float = 0.0

    def validate(self) -> tuple[bool, str]:
        if self.trust not in DeviceTrust.ALL:
            return False, f"unknown trust state {self.trust}"
        if not self.user_id:
            return False, "device requires user_id"
        return True, "ok"

    def usable(self) -> tuple[bool, str]:
        if self.trust == DeviceTrust.REVOKED or self.revoked_at:
            return False, "device revoked"
        if self.trust == DeviceTrust.RESTRICTED:
            return False, "device restricted"
        return True, "ok"

    def revoke(self) -> None:
        self.trust = DeviceTrust.REVOKED
        self.revoked_at = _utcnow()


# ------------------------------------------------------------ session risk ---
@dataclass
class SessionContext:
    session_id: str
    user_id: str
    auth_strength: str = AuthStrength.AAL1
    device_trust: str = DeviceTrust.UNKNOWN
    new_device: bool = False
    failed_attempts: int = 0
    session_age_seconds: float = 0.0
    token_age_seconds: float = 0.0
    ip_allowed: bool = True
    mfa_verified: bool = False


def session_risk(context: SessionContext) -> dict[str, Any]:
    """Risk signals (never geolocation-alone decisions)."""
    score = 0.0
    signals: list[str] = []
    if context.new_device:
        score += 0.3
        signals.append("new_device")
    if context.device_trust == DeviceTrust.RESTRICTED:
        score += 0.4
        signals.append("device_restricted")
    if context.device_trust == DeviceTrust.UNKNOWN:
        score += 0.1
        signals.append("device_unknown")
    if context.failed_attempts >= 3:
        score += min(0.3, 0.1 * context.failed_attempts)
        signals.append("failed_attempts")
    if context.session_age_seconds > 12 * 3600:
        score += 0.1
        signals.append("long_session")
    if not context.ip_allowed:
        score += 0.5
        signals.append("ip_policy")
    if not context.mfa_verified and context.auth_strength == AuthStrength.AAL1:
        score += 0.1
        signals.append("single_factor")
    score = min(1.0, score)
    level = RiskLevel.LOW
    if score >= 0.7:
        level = RiskLevel.HIGH
    elif score >= 0.35:
        level = RiskLevel.MEDIUM
    return {"score": round(score, 3), "level": level, "signals": signals}


# --------------------------------------------------------------- step-up ---
@dataclass
class StepUpDecision:
    verdict: str  # ALLOW|DENY|STEP_UP
    required_strength: str = AuthStrength.AAL1
    reason: str = ""


STEP_UP_ACTIONS = ("billing_change", "credential_change",
                   "production_action", "security_config", "sso_change",
                   "scim_change", "platform_admin", "destructive")


def evaluate_step_up(*, action: str, have_strength: str,
                     risk_level: str,
                     configured_strength: str = "") -> StepUpDecision:
    """Policy-configured step-up (§28, §33). High-risk or sensitive
    actions escalate; never hard-coded per business object."""
    need = configured_strength or (
        AuthStrength.AAL2 if action in STEP_UP_ACTIONS else AuthStrength.AAL1)
    if risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL):
        need = AuthStrength.AAL2 if need == AuthStrength.AAL1 else need
    if not strength_meets(have_strength, need):
        return StepUpDecision("STEP_UP", required_strength=need,
                              reason=f"{action} requires {need}")
    return StepUpDecision("ALLOW", required_strength=need,
                          reason="authentication strength sufficient")


# -------------------------------------------------------------- revocation ---
class RevocationRegistry:
    """Prompt revocation: per-session version counters. Validators reject
    any token/session/device/credential whose version != current."""

    def __init__(self) -> None:
        self._versions: dict[str, int] = {}

    def current(self, key: str) -> int:
        return self._versions.get(key, 0)

    def revoke(self, key: str) -> int:
        self._versions[key] = self._versions.get(key, 0) + 1
        return self._versions[key]

    def valid(self, key: str, version: int) -> bool:
        return version == self.current(key)

    def revoke_user_everywhere(self, user_id: str) -> None:
        self.revoke(f"user:{user_id}")      # sessions
        self.revoke(f"devices:{user_id}")   # device trust cache
        self.revoke(f"tokens:{user_id}")    # cached token state
