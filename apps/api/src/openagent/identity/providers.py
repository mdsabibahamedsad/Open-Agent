"""MP27: enterprise IdP abstraction (§6). Provider-neutral; OIDC,
OAuth2, SAML, local auth, and future providers implement it. Never
hard-code a vendor."""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class AuthRequest:
    organization_id: str
    provider_id: str
    subject_hint: str = ""
    redirect_uri: str = ""
    state: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class AuthResult:
    subject: str  # stable provider-side user id (sub / NameID)
    email: str = ""
    email_verified: bool = False
    display_name: str = ""
    groups: list[str] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)
    auth_strength: str = "AAL1"
    raw_claims: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProvisioningResult:
    created: bool
    user_id: str
    detail: str = ""


class IdentityProvider(abc.ABC):
    provider_type: str = "local"

    @abc.abstractmethod
    async def authenticate(self, request: AuthRequest) -> str:
        """Begin login; returns the IdP redirect URL."""

    @abc.abstractmethod
    async def validate_assertion(self, payload: dict[str, Any],
                                 context: dict[str, Any]) -> AuthResult:
        """Validate the IdP response and return verified identity."""

    @abc.abstractmethod
    async def provision_user(self, result: AuthResult,
                             context: dict[str, Any]) -> ProvisioningResult:
        """JIT provisioning hook (policy decides role/teams)."""

    @abc.abstractmethod
    async def deprovision_user(self, subject: str,
                               context: dict[str, Any]) -> bool:
        """Disable access; never destroy audit history."""

    @abc.abstractmethod
    async def get_groups(self, subject: str,
                         context: dict[str, Any]) -> list[str]:
        """Authoritative group list for mapping."""


class LocalIdentityProvider(IdentityProvider):
    """Built-in provider: self-hosted OpenAgent works with no IdP."""

    provider_type = "local"

    async def authenticate(self, request: AuthRequest) -> str:
        return f"/login?org={request.organization_id}"

    async def validate_assertion(self, payload: dict[str, Any],
                                 context: dict[str, Any]) -> AuthResult:
        # Local password verification happens in services.auth; this path
        # only wraps an already-verified local principal.
        subject = str(payload.get("subject") or "")
        if not subject:
            raise ValueError("local assertion requires subject")
        return AuthResult(subject=subject,
                          email=str(payload.get("email", "")),
                          email_verified=True, auth_strength="AAL1")

    async def provision_user(self, result: AuthResult,
                             context: dict[str, Any]) -> ProvisioningResult:
        return ProvisioningResult(created=False, user_id=result.subject,
                                  detail="local users pre-exist")

    async def deprovision_user(self, subject: str,
                               context: dict[str, Any]) -> bool:
        return True

    async def get_groups(self, subject: str,
                         context: dict[str, Any]) -> list[str]:
        return []
