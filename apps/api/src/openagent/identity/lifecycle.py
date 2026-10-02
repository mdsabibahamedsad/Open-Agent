"""MP27: identity record + lifecycle (§4-5).

Security-critical records are never physically deleted while an audit
trail requires them: DELETED is a terminal tombstone, not row removal.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from openagent.identity.types import (
    IdentityStatus, IdentityType, is_valid_identity_transition,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Identity:
    id: str = field(default_factory=lambda: f"idn_{uuid.uuid4().hex[:16]}")
    type: str = IdentityType.HUMAN
    status: str = IdentityStatus.INVITED
    owner_id: str = ""
    organization_id: str = ""
    scope: str = ""
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)
    expires_at: Optional[datetime] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> tuple[bool, str]:
        if self.type not in IdentityType.ALL:
            return False, f"unknown identity type {self.type}"
        if self.status not in IdentityStatus.ALL:
            return False, f"unknown identity status {self.status}"
        if not self.id or not self.organization_id and self.type != IdentityType.PLATFORM:
            if self.type != IdentityType.PLATFORM and not self.organization_id:
                return False, "non-platform identity requires organization_id"
        return True, "ok"

    def transition(self, to_status: str) -> tuple[bool, str]:
        if not is_valid_identity_transition(self.status, to_status):
            return False, f"{self.status} -> {to_status} not allowed"
        if self.status == IdentityStatus.DELETED:
            return False, "tombstoned identity is immutable"
        self.status = to_status
        self.updated_at = _utcnow()
        return True, "ok"

    def usable(self, now: Optional[datetime] = None) -> tuple[bool, str]:
        if self.status != IdentityStatus.ACTIVE:
            return False, f"identity {self.status.lower()}"
        moment = now or _utcnow()
        if self.expires_at is not None and moment >= self.expires_at:
            return False, "identity expired"
        return True, "active"


class IdentityRegistry:
    """In-memory identity index (DB models are the durable store)."""

    def __init__(self) -> None:
        self._identities: dict[str, Identity] = {}

    def register(self, identity: Identity) -> Identity:
        ok, reason = identity.validate()
        if not ok:
            raise ValueError(reason)
        self._identities[identity.id] = identity
        return identity

    def get(self, identity_id: str) -> Optional[Identity]:
        return self._identities.get(identity_id)

    def transition(self, identity_id: str, to_status: str) -> Identity:
        identity = self._identities.get(identity_id)
        if identity is None:
            raise KeyError(f"unknown identity {identity_id}")
        ok, reason = identity.transition(to_status)
        if not ok:
            raise ValueError(reason)
        return identity

    def deactivate_preserve(self, identity_id: str) -> Identity:
        """SCIM deprovision: disable access, keep audit history (§17)."""
        identity = self.get(identity_id)
        if identity is None:
            raise KeyError(f"unknown identity {identity_id}")
        for target in (IdentityStatus.DISABLED, IdentityStatus.REVOKED,
                       IdentityStatus.SUSPENDED):
            ok, _ = identity.transition(target)
            if ok:
                return identity
        raise ValueError(f"cannot deactivate identity in {identity.status}")
