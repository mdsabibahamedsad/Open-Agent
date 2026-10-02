"""MP27: identity vocabulary. Pure constants + transition validation."""

from __future__ import annotations


class IdentityType:
    HUMAN = "human"
    SERVICE_ACCOUNT = "service_account"
    API_CLIENT = "api_client"
    WORKER = "worker"
    AGENT = "agent"
    CONNECTOR = "connector"
    MCP = "mcp"
    PLATFORM = "platform"
    ALL = ("human", "service_account", "api_client", "worker",
           "agent", "connector", "mcp", "platform")


class IdentityStatus:
    INVITED = "INVITED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DISABLED = "DISABLED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    DELETED = "DELETED"
    ALL = ("INVITED", "ACTIVE", "SUSPENDED", "DISABLED",
           "EXPIRED", "REVOKED", "DELETED")


_IDENTITY_TRANSITIONS: dict[str, frozenset[str]] = {
    IdentityStatus.INVITED: frozenset({IdentityStatus.ACTIVE,
                                       IdentityStatus.EXPIRED,
                                       IdentityStatus.REVOKED}),
    IdentityStatus.ACTIVE: frozenset({IdentityStatus.SUSPENDED,
                                      IdentityStatus.DISABLED,
                                      IdentityStatus.EXPIRED,
                                      IdentityStatus.REVOKED}),
    IdentityStatus.SUSPENDED: frozenset({IdentityStatus.ACTIVE,
                                         IdentityStatus.DISABLED,
                                         IdentityStatus.REVOKED}),
    IdentityStatus.DISABLED: frozenset({IdentityStatus.ACTIVE,
                                        IdentityStatus.REVOKED,
                                        IdentityStatus.DELETED}),
    IdentityStatus.EXPIRED: frozenset({IdentityStatus.ACTIVE,
                                       IdentityStatus.REVOKED,
                                       IdentityStatus.DELETED}),
    IdentityStatus.REVOKED: frozenset({IdentityStatus.DELETED}),
    IdentityStatus.DELETED: frozenset(),
}


def is_valid_identity_transition(frm: str, to: str) -> bool:
    if frm not in _IDENTITY_TRANSITIONS or to not in IdentityStatus.ALL:
        return False
    if frm == to:
        return True
    return to in _IDENTITY_TRANSITIONS[frm]


class IdentityProviderType:
    OIDC = "oidc"
    OAUTH2 = "oauth2"
    SAML = "saml"
    LOCAL = "local"
    ALL = ("oidc", "oauth2", "saml", "local")


class AuthMethod:
    PASSWORD = "password"
    OIDC = "oidc"
    SAML = "saml"
    TOTP = "totp"
    WEBAUTHN = "webauthn"
    RECOVERY_CODE = "recovery_code"
    API_KEY = "api_key"
    SERVICE_TOKEN = "service_token"
    WORKLOAD = "workload"
    ALL = ("password", "oidc", "saml", "totp", "webauthn",
           "recovery_code", "api_key", "service_token", "workload")


class AuthStrength:
    """Authentication Assurance Levels. Higher = stronger proof."""
    AAL1 = "AAL1"  # single factor
    AAL2 = "AAL2"  # MFA
    AAL3 = "AAL3"  # hardware-backed MFA
    RANK = {"AAL1": 1, "AAL2": 2, "AAL3": 3}
    ALL = ("AAL1", "AAL2", "AAL3")


def strength_meets(have: str, need: str) -> bool:
    return AuthStrength.RANK.get(have, 0) >= AuthStrength.RANK.get(need, 99)


class DeviceTrust:
    UNKNOWN = "UNKNOWN"
    TRUSTED = "TRUSTED"
    RESTRICTED = "RESTRICTED"
    REVOKED = "REVOKED"
    ALL = ("UNKNOWN", "TRUSTED", "RESTRICTED", "REVOKED")


class RiskLevel:
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"
    ALL = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
    RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}


class DataClassification:
    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    CONFIDENTIAL = "CONFIDENTIAL"
    RESTRICTED = "RESTRICTED"
    SECRET = "SECRET"
    ALL = ("PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED", "SECRET")
    RANK = {"PUBLIC": 0, "INTERNAL": 1, "CONFIDENTIAL": 2,
            "RESTRICTED": 3, "SECRET": 4}


class TokenKind:
    SESSION = "session"
    ACCESS = "access"
    REFRESH = "refresh"
    SCIM = "scim"
    ENROLLMENT = "enrollment"
    EMAIL = "email"
    RESET = "reset"
    INVITATION = "invitation"
    WORKLOAD = "workload"
    ALL = ("session", "access", "refresh", "scim", "enrollment",
           "email", "reset", "invitation", "workload")


# ABAC attribute names (§23). Fixed vocabulary, no arbitrary attrs.
ABAC_ATTRIBUTES = (
    "organization", "project", "environment", "resource_type",
    "resource_owner", "data_classification", "risk_level",
    "network_context", "identity_type", "device_trust",
)

# Policy scopes, most-restrictive-wins order (§25).
POLICY_PRECEDENCE = ("platform", "organization", "project",
                     "environment", "resource", "request")
