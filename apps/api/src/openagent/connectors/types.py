"""Universal connector domain types (MP21).

Pure, dependency-light. DB enums live in db/models/connector.py and mirror
these. Trust is a first-class input to policy: community/custom connectors
are treated as potentially untrusted code and data.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any


class ConnectorType(str, enum.Enum):
    OFFICIAL = "OFFICIAL"
    COMMUNITY = "COMMUNITY"
    CUSTOM = "CUSTOM"
    INTERNAL = "INTERNAL"
    MCP_BACKED = "MCP_BACKED"
    HTTP_GENERIC = "HTTP_GENERIC"
    DATABASE = "DATABASE"
    WEBHOOK_ONLY = "WEBHOOK_ONLY"


class ConnectorStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"
    DEPRECATED = "DEPRECATED"
    SUSPENDED = "SUSPENDED"
    ERROR = "ERROR"


CONNECTOR_TRANSITIONS: dict[ConnectorStatus, frozenset[ConnectorStatus]] = {
    ConnectorStatus.DRAFT: frozenset({ConnectorStatus.ACTIVE, ConnectorStatus.DISABLED}),
    ConnectorStatus.ACTIVE: frozenset({ConnectorStatus.DISABLED, ConnectorStatus.DEPRECATED,
                                       ConnectorStatus.SUSPENDED, ConnectorStatus.ERROR}),
    ConnectorStatus.DISABLED: frozenset({ConnectorStatus.ACTIVE, ConnectorStatus.DEPRECATED}),
    ConnectorStatus.DEPRECATED: frozenset({ConnectorStatus.DISABLED}),
    ConnectorStatus.SUSPENDED: frozenset({ConnectorStatus.ACTIVE, ConnectorStatus.DISABLED,
                                          ConnectorStatus.ERROR}),
    ConnectorStatus.ERROR: frozenset({ConnectorStatus.DISABLED, ConnectorStatus.ACTIVE}),
}


def can_transition_connector(frm: ConnectorStatus, to: ConnectorStatus) -> bool:
    return to in CONNECTOR_TRANSITIONS.get(frm, frozenset())


class InstanceStatus(str, enum.Enum):
    UNCONNECTED = "UNCONNECTED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    DEGRADED = "DEGRADED"
    AUTH_EXPIRED = "AUTH_EXPIRED"
    ERROR = "ERROR"
    DISCONNECTED = "DISCONNECTED"


INSTANCE_TRANSITIONS: dict[InstanceStatus, frozenset[InstanceStatus]] = {
    InstanceStatus.UNCONNECTED: frozenset({InstanceStatus.CONNECTING, InstanceStatus.DISCONNECTED}),
    InstanceStatus.CONNECTING: frozenset({InstanceStatus.CONNECTED, InstanceStatus.AUTH_EXPIRED,
                                          InstanceStatus.ERROR, InstanceStatus.DISCONNECTED}),
    InstanceStatus.CONNECTED: frozenset({InstanceStatus.DEGRADED, InstanceStatus.AUTH_EXPIRED,
                                         InstanceStatus.ERROR, InstanceStatus.DISCONNECTED}),
    InstanceStatus.DEGRADED: frozenset({InstanceStatus.CONNECTED, InstanceStatus.AUTH_EXPIRED,
                                        InstanceStatus.ERROR, InstanceStatus.DISCONNECTED}),
    InstanceStatus.AUTH_EXPIRED: frozenset({InstanceStatus.CONNECTING, InstanceStatus.DISCONNECTED,
                                            InstanceStatus.ERROR}),
    InstanceStatus.ERROR: frozenset({InstanceStatus.CONNECTING, InstanceStatus.DISCONNECTED}),
    InstanceStatus.DISCONNECTED: frozenset({InstanceStatus.CONNECTING}),
}


def can_transition_instance(frm: InstanceStatus, to: InstanceStatus) -> bool:
    return to in INSTANCE_TRANSITIONS.get(frm, frozenset())


class ConnectorScope(str, enum.Enum):
    PLATFORM = "PLATFORM"
    ORGANIZATION = "ORGANIZATION"
    TEAM = "TEAM"
    USER = "USER"
    WORKFLOW = "WORKFLOW"
    AGENT = "AGENT"


class SharingPolicy(str, enum.Enum):
    PRIVATE = "PRIVATE"
    TEAM = "TEAM"
    ORGANIZATION = "ORGANIZATION"
    WORKFLOW_ONLY = "WORKFLOW_ONLY"


class AuthType(str, enum.Enum):
    OAUTH2 = "oauth2"
    API_KEY = "api_key"
    BASIC = "basic"
    JWT = "jwt"
    SERVICE_ACCOUNT = "service_account"
    CUSTOM_HEADER = "custom_header"
    NONE = "none"


class TrustTier(str, enum.Enum):
    CORE = "CORE"
    VERIFIED = "VERIFIED"
    ORGANIZATION = "ORGANIZATION"
    COMMUNITY = "COMMUNITY"
    CUSTOM = "CUSTOM"
    UNTRUSTED = "UNTRUSTED"


# Trust rank: higher wins in policy blending; unknown/community never
# outranks organization policy.
TRUST_RANK: dict[TrustTier, int] = {
    TrustTier.CORE: 5,
    TrustTier.VERIFIED: 4,
    TrustTier.ORGANIZATION: 3,
    TrustTier.COMMUNITY: 1,
    TrustTier.CUSTOM: 1,
    TrustTier.UNTRUSTED: 0,
}


class HealthState(str, enum.Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    AUTH_EXPIRED = "AUTH_EXPIRED"
    RATE_LIMITED = "RATE_LIMITED"
    ERROR = "ERROR"
    UNKNOWN = "UNKNOWN"


class TriggerKind(str, enum.Enum):
    WEBHOOK = "webhook"
    POLLING = "polling"
    SCHEDULE = "schedule"
    EVENT = "event"
    MANUAL = "manual"


class RiskLevel(str, enum.Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


@dataclass
class CapabilityDef:
    """Granular least-privilege capability, e.g. github.issues.write."""
    id: str  # fully qualified: <connector>.<resource>.<verb>
    description: str = ""
    risk_level: RiskLevel = RiskLevel.LOW


@dataclass
class ActionDef:
    id: str  # <connector>.<action>, e.g. github.create_issue
    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    required_capabilities: list[str] = field(default_factory=list)
    risk_level: RiskLevel = RiskLevel.MEDIUM
    supports_idempotency: bool = False
    idempotency_strategy: str = ""  # e.g. "header:Idempotency-Key"
    supports_async: bool = False
    timeout_seconds: int = 30
    rate_limit_per_minute: int = 60
    verification: dict[str, Any] = field(default_factory=dict)  # custom verify defs (§88)
    mutation: bool = True
    # Generic HTTP connectors only: declarative request template.
    http: dict[str, Any] = field(default_factory=dict)


@dataclass
class TriggerDef:
    id: str
    name: str
    kind: TriggerKind = TriggerKind.WEBHOOK
    description: str = ""
    event_types: list[str] = field(default_factory=list)
    payload_schema: dict[str, Any] = field(default_factory=dict)
    poll_config: dict[str, Any] = field(default_factory=dict)


@dataclass
class ResourceDef:
    kind: str  # normalized kind: user|message|file|repository|...
    provider_kind: str = ""  # provider-specific name
    schema: dict[str, Any] = field(default_factory=dict)


@dataclass
class ConnectorManifest:
    id: str
    name: str
    version: str
    category: str = "automation"
    connector_type: ConnectorType = ConnectorType.OFFICIAL
    trust: TrustTier = TrustTier.VERIFIED
    description: str = ""
    publisher: str = ""
    license: str = ""
    documentation_url: str = ""
    auth: dict[str, Any] = field(default_factory=dict)
    capabilities: list[CapabilityDef] = field(default_factory=list)
    actions: list[ActionDef] = field(default_factory=list)
    triggers: list[TriggerDef] = field(default_factory=list)
    resources: list[ResourceDef] = field(default_factory=list)
    scopes: list[str] = field(default_factory=list)
    rate_limits: dict[str, Any] = field(default_factory=dict)
    supported_environments: list[str] = field(default_factory=lambda: ["production"])
    signature: str = ""  # publisher signature (marketplace-ready, optional pre-marketplace)
    content_hash: str = ""


@dataclass
class ConnectorExecutionContext:
    """Standardized execution context. Credential references only — no raw secrets."""
    organization_id: str
    user_id: str = ""
    agent_id: str = ""
    workflow_id: str = ""
    execution_id: str = ""
    tool_id: str = ""
    connector_id: str = ""
    connection_id: str = ""
    credential_reference: str = ""  # credential_id, never secret material
    policy_context: dict[str, Any] = field(default_factory=dict)
    risk_context: dict[str, Any] = field(default_factory=dict)
    approval_context: dict[str, Any] = field(default_factory=dict)
