"""OpenAgent Enterprise Identity & Zero-Trust layer (Master Prompt 27).

Authentication (who), authorization (what allowed), zero-trust (should
this request be trusted now, in context), and compliance (demonstrate +
enforce controls) stay SEPARATE concepts. Every enterprise feature is
modular: core auth keeps working self-hosted with no IdP, no cloud.
"""

from openagent.identity.types import (
    IdentityType,
    IdentityStatus,
    IdentityProviderType,
    AuthMethod,
    AuthStrength,
    DeviceTrust,
    RiskLevel,
    DataClassification,
)

__all__ = [
    "IdentityType",
    "IdentityStatus",
    "IdentityProviderType",
    "AuthMethod",
    "AuthStrength",
    "DeviceTrust",
    "RiskLevel",
    "DataClassification",
]
