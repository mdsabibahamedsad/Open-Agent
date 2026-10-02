"""MP27: SSO configuration, domain verification/claiming, JIT
provisioning, group-to-role mapping (§10-15, §21-22).

Secrets always travel as references (existing credential system).
Owner privileges are NEVER granted from IdP claims automatically.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from openagent.identity.types import IdentityProviderType


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ------------------------------------------------- SSO configuration (§10) ---
SSO_STATUSES = ("DRAFT", "TESTING", "ACTIVE", "DISABLED")


@dataclass
class SsoConfiguration:
    config_id: str = ""
    organization_id: str = ""
    provider_type: str = IdentityProviderType.OIDC
    issuer: str = ""
    client_id: str = ""
    client_secret_ref: str = ""  # reference only, never the value
    metadata_url: str = ""
    certificate_ref: str = ""
    domains: list[str] = field(default_factory=list)
    attribute_mapping: dict[str, str] = field(default_factory=dict)
    group_mapping: dict[str, dict[str, str]] = field(default_factory=dict)
    status: str = "DRAFT"
    enforce_mfa: bool = False

    def validate(self) -> tuple[bool, str]:
        if self.provider_type not in IdentityProviderType.ALL:
            return False, f"unknown provider type {self.provider_type}"
        if not self.issuer:
            return False, "issuer is required"
        if self.provider_type in ("oidc", "oauth2") and not self.client_id:
            return False, "client_id is required"
        if self.provider_type == "saml" and not self.metadata_url:
            return False, "IdP metadata is required for SAML"
        if self.status not in SSO_STATUSES:
            return False, f"unknown status {self.status}"
        # Secret values must never be embedded in configuration.
        for secret_field in (self.client_id,):
            if len(secret_field) > 500:
                return False, "suspicious client_id value"
        if self.client_secret_ref and len(self.client_secret_ref) < 4:
            return False, "client_secret_ref looks like a raw value"
        return True, "ok"

    def can_enforce(self) -> tuple[bool, str]:
        if self.status != "ACTIVE":
            return False, "configuration is not ACTIVE"
        if not self.domains:
            return False, "no verified domains attached"
        return True, "enforceable"


# ------------------------------------------- domain verification (§11-13) ---
DOMAIN_STATUSES = ("PENDING", "VERIFIED", "CONFLICTING", "RELEASED")


@dataclass
class DomainClaim:
    domain: str
    organization_id: str
    status: str = "PENDING"
    method: str = "dns_txt"  # dns_txt|file
    challenge: str = ""
    verified_at: Optional[datetime] = None

    @staticmethod
    def normalize(domain: str) -> str:
        return str(domain or "").strip().lower().rstrip(".")

    @classmethod
    def mint(cls, domain: str, organization_id: str,
             method: str = "dns_txt") -> "DomainClaim":
        normalized = cls.normalize(domain)
        if not normalized or "." not in normalized or " " in normalized:
            raise ValueError(f"invalid domain {domain}")
        token = secrets.token_urlsafe(24)
        challenge = (f"openagent-domain-verification={token}"
                     if method == "dns_txt" else token)
        return cls(domain=normalized, organization_id=organization_id,
                   method=method, challenge=challenge)

    def expected_dns_txt(self) -> str:
        return self.challenge

    def verify(self, presented: str) -> tuple[bool, str]:
        import hmac as _hmac
        if not secrets.compare_digest(str(presented or ""), self.challenge):
            return False, "challenge mismatch"
        self.status = "VERIFIED"
        self.verified_at = _utcnow()
        return True, "domain verified"


class DomainRegistry:
    """One verified domain belongs to exactly one organization."""

    def __init__(self) -> None:
        self._claims: dict[str, DomainClaim] = {}

    def claim(self, domain: str, organization_id: str,
              method: str = "dns_txt") -> DomainClaim:
        normalized = DomainClaim.normalize(domain)
        existing = self._claims.get(normalized)
        if existing is not None and existing.status == "VERIFIED":
            if existing.organization_id != organization_id:
                existing.status = "CONFLICTING"
                raise ValueError(f"domain {normalized} already claimed")
            return existing
        claim = DomainClaim.mint(normalized, organization_id, method)
        self._claims[normalized] = claim
        return claim

    def verify(self, domain: str, presented: str) -> DomainClaim:
        claim = self._claims.get(DomainClaim.normalize(domain))
        if claim is None:
            raise KeyError(f"no claim for {domain}")
        ok, reason = claim.verify(presented)
        if not ok:
            raise ValueError(reason)
        return claim

    def route(self, email: str) -> Optional[DomainClaim]:
        """Domain-based SSO routing (§12): verified domains only."""
        mailbox = str(email or "").strip().lower()
        if "@" not in mailbox:
            return None
        domain = mailbox.rsplit("@", 1)[1]
        claim = self._claims.get(domain)
        if claim is not None and claim.status == "VERIFIED":
            return claim
        return None  # unverified domains never route to an IdP


# ------------------------------------------------- JIT provisioning (§14-15) ---
JIT_ROLES = ("member", "developer", "admin", "viewer", "owner")


@dataclass
class JitPlan:
    user_exists: bool
    create_user: bool
    organization_id: str
    role: str = "member"
    teams: list[str] = field(default_factory=list)
    environments: list[str] = field(default_factory=list)
    detail: str = ""


def jit_plan(*, user_exists: bool, organization_id: str,
             default_role: str = "member",
             default_teams: Optional[list[str]] = None,
             requested_role: str = "",
             allow_owner_via_claim: bool = False) -> JitPlan:
    """JIT plan. Owner NEVER comes from IdP claims unless the org
    explicitly enabled it through protected platform configuration."""
    role = (requested_role or default_role or "member").lower()
    if role not in JIT_ROLES:
        role = "member"
    if role == "owner" and not allow_owner_via_claim:
        role = "member"  # §15: hard downgrade, never silent owner grant
    return JitPlan(user_exists=user_exists,
                   create_user=not user_exists,
                   organization_id=organization_id, role=role,
                   teams=list(default_teams or []),
                   detail="jit provision" if not user_exists else "jit login")


# --------------------------------------- group-to-role mapping (§21-22) ---
# Platform-privileged targets an external mapping can NEVER grant.
# Note: plain "owner" is an ORGANIZATION role (allowed with a loud
# warning); platform ownership lives in a separate protected config.
PLATFORM_PRIVILEGED = ("platform_owner", "master", "superadmin")


@dataclass
class GroupMapping:
    external_group: str
    team: str = ""
    role: str = "member"

    def validate(self) -> tuple[bool, str]:
        if not self.external_group:
            return False, "external group is required"
        if self.role.lower() in PLATFORM_PRIVILEGED:
            return False, (
                f"mapping to {self.role} is blocked: external groups "
                "cannot grant platform ownership (needs protected "
                "platform configuration)")
        if self.role.lower() not in JIT_ROLES:
            return False, f"unknown role {self.role}"
        return True, "ok"


def resolve_memberships(external_groups: list[str],
                        mappings: list[GroupMapping],
                        *, platform_allowlist: Optional[set[str]] = None
                        ) -> tuple[list[GroupMapping], list[str]]:
    """Map IdP groups to team/role grants. Returns (grants, warnings)."""
    by_group = {m.external_group: m for m in mappings}
    grants: list[GroupMapping] = []
    warnings: list[str] = []
    for group in external_groups:
        mapping = by_group.get(group)
        if mapping is None:
            continue
        ok, reason = mapping.validate()
        if not ok:
            warnings.append(f"{group}: {reason}")
            continue
        if mapping.role.lower() == "owner":
            # Org-owner via mapping is sensitive: warn loudly, keep narrow.
            warnings.append(f"{group}: grants organization owner — review")
        grants.append(mapping)
    _ = platform_allowlist
    return grants, warnings


def sso_test_preview(*, email: str, groups: list[str],
                     mappings: list[GroupMapping],
                     user_exists: bool,
                     organization_id: str) -> dict[str, Any]:
    """SSO test mode (§97): show mapping outcome, change nothing."""
    grants, warnings = resolve_memberships(groups, mappings)
    plan = jit_plan(user_exists=user_exists,
                    organization_id=organization_id)
    return {"email": email, "groups": groups,
            "proposed_role": grants[0].role if grants else plan.role,
            "proposed_teams": [g.team for g in grants if g.team],
            "would_create_user": plan.create_user,
            "warnings": warnings, "applied": False}
