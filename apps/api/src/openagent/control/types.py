"""MP26: control-plane vocabulary. Pure constants + validators (no I/O)."""

from __future__ import annotations


class EnvironmentName:
    DEVELOPMENT = "DEVELOPMENT"
    STAGING = "STAGING"
    PRODUCTION = "PRODUCTION"
    ALL = ("DEVELOPMENT", "STAGING", "PRODUCTION")


class HealthState:
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"
    UNKNOWN = "UNKNOWN"
    MAINTENANCE = "MAINTENANCE"
    ALL = ("HEALTHY", "DEGRADED", "UNAVAILABLE", "UNKNOWN", "MAINTENANCE")
    RANK = {"HEALTHY": 0, "UNKNOWN": 1, "MAINTENANCE": 2,
            "DEGRADED": 3, "UNAVAILABLE": 4}


def aggregate_health(states: list[str]) -> str:
    """Worst-rank wins; empty input is UNKNOWN (never fake HEALTHY)."""
    if not states:
        return HealthState.UNKNOWN
    rank = HealthState.RANK
    worst = max(states, key=lambda s: rank.get(s, 1))
    return worst if worst in HealthState.ALL else HealthState.UNKNOWN


class ActionRisk:
    NORMAL = "NORMAL"
    SENSITIVE = "SENSITIVE"
    HIGH_RISK = "HIGH_RISK"
    CRITICAL = "CRITICAL"
    ALL = ("NORMAL", "SENSITIVE", "HIGH_RISK", "CRITICAL")
    RANK = {"NORMAL": 0, "SENSITIVE": 1, "HIGH_RISK": 2, "CRITICAL": 3}


class AlertSeverity:
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"
    ALL = ("INFO", "WARNING", "ERROR", "CRITICAL")


class AlertStatus:
    FIRING = "FIRING"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"
    SILENCED = "SILENCED"
    ALL = ("FIRING", "ACKNOWLEDGED", "RESOLVED", "SILENCED")


class IncidentStatus:
    DETECTED = "DETECTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    INVESTIGATING = "INVESTIGATING"
    MITIGATING = "MITIGATING"
    MONITORING = "MONITORING"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"
    ALL = ("DETECTED", "ACKNOWLEDGED", "INVESTIGATING", "MITIGATING",
           "MONITORING", "RESOLVED", "CLOSED")


_INCIDENT_TRANSITIONS: dict[str, frozenset[str]] = {
    IncidentStatus.DETECTED: frozenset({IncidentStatus.ACKNOWLEDGED, IncidentStatus.INVESTIGATING}),
    IncidentStatus.ACKNOWLEDGED: frozenset({IncidentStatus.INVESTIGATING, IncidentStatus.MITIGATING}),
    IncidentStatus.INVESTIGATING: frozenset({IncidentStatus.MITIGATING, IncidentStatus.MONITORING,
                                             IncidentStatus.RESOLVED}),
    IncidentStatus.MITIGATING: frozenset({IncidentStatus.MONITORING, IncidentStatus.INVESTIGATING,
                                          IncidentStatus.RESOLVED}),
    IncidentStatus.MONITORING: frozenset({IncidentStatus.RESOLVED, IncidentStatus.MITIGATING}),
    IncidentStatus.RESOLVED: frozenset({IncidentStatus.CLOSED, IncidentStatus.INVESTIGATING}),
    IncidentStatus.CLOSED: frozenset(),
}


def is_valid_incident_transition(frm: str, to: str) -> bool:
    if frm not in _INCIDENT_TRANSITIONS or to not in IncidentStatus.ALL:
        return False
    if frm == to:
        return True
    return to in _INCIDENT_TRANSITIONS[frm]


class DeploymentStatus:
    PENDING = "PENDING"
    DEPLOYING = "DEPLOYING"
    ACTIVE = "ACTIVE"
    FAILED = "FAILED"
    ROLLED_BACK = "ROLLED_BACK"
    ALL = ("PENDING", "DEPLOYING", "ACTIVE", "FAILED", "ROLLED_BACK")


class ReleaseState:
    CREATED = "CREATED"
    DEPLOYING = "DEPLOYING"
    ACTIVE = "ACTIVE"
    FAILED = "FAILED"
    ROLLED_BACK = "ROLLED_BACK"
    ALL = ("CREATED", "DEPLOYING", "ACTIVE", "FAILED", "ROLLED_BACK")


class DataClassification:
    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    CONFIDENTIAL = "CONFIDENTIAL"
    RESTRICTED = "RESTRICTED"
    ALL = ("PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED")
    RANK = {"PUBLIC": 0, "INTERNAL": 1, "CONFIDENTIAL": 2, "RESTRICTED": 3}


class ConfigScope:
    PLATFORM = "PLATFORM"
    ORGANIZATION = "ORGANIZATION"
    PROJECT = "PROJECT"
    ENVIRONMENT = "ENVIRONMENT"
    USER = "USER"
    ALL = ("PLATFORM", "ORGANIZATION", "PROJECT", "ENVIRONMENT", "USER")


class RiskLevel:
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"
    ALL = ("LOW", "MEDIUM", "HIGH", "CRITICAL")


# Canonical resource types for the unified resource model (§5).
RESOURCE_TYPES = (
    "organization", "project", "environment", "agent", "workflow",
    "execution", "worker_pool", "worker", "queue", "sandbox",
    "browser_session", "artifact", "connector", "mcp_server",
    "credential", "api_key", "region", "storage",
)

# Canonical platform event names (§85).
PLATFORM_EVENTS = (
    "deployment.started", "deployment.completed", "region.degraded",
    "worker.unhealthy", "queue.overloaded", "incident.created",
    "incident.resolved", "feature_flag.changed", "policy.changed",
)

# Status-page states (§34). Internal detail stays internal.
PUBLIC_STATUS = ("operational", "degraded", "partial_outage",
                 "major_outage", "maintenance")


def public_status_for(health: str) -> str:
    mapping = {HealthState.HEALTHY: "operational",
               HealthState.DEGRADED: "degraded",
               HealthState.UNAVAILABLE: "major_outage",
               HealthState.MAINTENANCE: "maintenance"}
    return mapping.get(health, "degraded" if health == "UNKNOWN" else "operational")
