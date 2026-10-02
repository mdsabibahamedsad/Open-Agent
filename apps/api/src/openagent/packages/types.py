"""MP22: shared enums, constants and trust/visibility policy tables.

This module intentionally has no external dependencies so every other
package-domain module (and the API layer) shares one vocabulary.
"""

from __future__ import annotations

import enum

PACKAGE_FORMAT = "openagent-package"
PACKAGE_FORMAT_VERSION = "1"


class ResourceType(str, enum.Enum):
    """Reusable resource types. Extensible without schema rewrites."""

    AGENT = "AGENT"
    AGENT_TEAM = "AGENT_TEAM"
    WORKFORCE = "WORKFORCE"
    WORKFLOW = "WORKFLOW"
    SKILL = "SKILL"
    PROMPT = "PROMPT"
    TOOL_BUNDLE = "TOOL_BUNDLE"
    CONNECTOR_BUNDLE = "CONNECTOR_BUNDLE"
    MODEL_PRESET = "MODEL_PRESET"
    AGENT_PRESET = "AGENT_PRESET"
    WORKFLOW_PRESET = "WORKFLOW_PRESET"
    MEMORY_PRESET = "MEMORY_PRESET"
    AUTOMATION_RECIPE = "AUTOMATION_RECIPE"
    TEMPLATE_PACKAGE = "TEMPLATE_PACKAGE"


# PackageType is the wire-level alias for ResourceType at package granularity.
PackageType = ResourceType


class PackageStatus(str, enum.Enum):
    """Lifecycle of a package *version* (immutable once published)."""

    DRAFT = "DRAFT"
    VALIDATING = "VALIDATING"
    VALIDATED = "VALIDATED"
    PUBLISHED = "PUBLISHED"
    DEPRECATED = "DEPRECATED"
    REVOKED = "REVOKED"
    ARCHIVED = "ARCHIVED"


# Ordered lifecycle; transitions must move forward except explicit rollback
# paths which are handled by the installer, never by status mutation.
PACKAGE_LIFECYCLE_ORDER = [s.value for s in PackageStatus]

#: Allowed status transitions (source -> set of targets).
PACKAGE_TRANSITIONS: dict[str, frozenset[str]] = {
    PackageStatus.DRAFT.value: frozenset(
        {PackageStatus.VALIDATING.value, PackageStatus.ARCHIVED.value}
    ),
    PackageStatus.VALIDATING.value: frozenset(
        {
            PackageStatus.VALIDATED.value,
            PackageStatus.DRAFT.value,
            PackageStatus.ARCHIVED.value,
        }
    ),
    PackageStatus.VALIDATED.value: frozenset(
        {
            PackageStatus.PUBLISHED.value,
            PackageStatus.DRAFT.value,
            PackageStatus.ARCHIVED.value,
        }
    ),
    PackageStatus.PUBLISHED.value: frozenset(
        {
            PackageStatus.DEPRECATED.value,
            PackageStatus.REVOKED.value,
            PackageStatus.ARCHIVED.value,
        }
    ),
    PackageStatus.DEPRECATED.value: frozenset(
        {PackageStatus.REVOKED.value, PackageStatus.ARCHIVED.value}
    ),
    PackageStatus.REVOKED.value: frozenset({PackageStatus.ARCHIVED.value}),
    PackageStatus.ARCHIVED.value: frozenset(),
}


def can_transition(source: str, target: str) -> bool:
    """Return True when a version status transition is legal."""
    return target in PACKAGE_TRANSITIONS.get(source, frozenset())


class InstallationStatus(str, enum.Enum):
    """Lifecycle of a tenant-scoped package installation."""

    REQUESTED = "REQUESTED"
    RESOLVING = "RESOLVING"
    VALIDATING = "VALIDATING"
    AWAITING_CONFIGURATION = "AWAITING_CONFIGURATION"
    INSTALLING = "INSTALLING"
    VERIFYING = "VERIFYING"
    INSTALLED = "INSTALLED"
    FAILED = "FAILED"
    UPDATING = "UPDATING"
    ROLLING_BACK = "ROLLING_BACK"
    ROLLED_BACK = "ROLLED_BACK"
    UNINSTALLED = "UNINSTALLED"


class TrustLevel(str, enum.Enum):
    CORE = "CORE"
    VERIFIED = "VERIFIED"
    ORGANIZATION = "ORGANIZATION"
    COMMUNITY = "COMMUNITY"
    UNTRUSTED = "UNTRUSTED"


#: Trust rank (higher = more trusted). Trust NEVER overrides security policy;
#: it only tunes warnings, defaults and approval strictness.
TRUST_RANK: dict[str, int] = {
    TrustLevel.CORE.value: 50,
    TrustLevel.VERIFIED.value: 40,
    TrustLevel.ORGANIZATION.value: 30,
    TrustLevel.COMMUNITY.value: 20,
    TrustLevel.UNTRUSTED.value: 10,
}


def trust_at_least(level: str, minimum: str) -> bool:
    return TRUST_RANK.get(level, 0) >= TRUST_RANK.get(minimum, 0)


class Visibility(str, enum.Enum):
    PRIVATE = "PRIVATE"
    TEAM = "TEAM"
    ORGANIZATION = "ORGANIZATION"
    PUBLIC = "PUBLIC"
    UNLISTED = "UNLISTED"


class PresetKind(str, enum.Enum):
    MODEL_PRESET = "MODEL_PRESET"
    AGENT_PRESET = "AGENT_PRESET"
    WORKFLOW_PRESET = "WORKFLOW_PRESET"
    MEMORY_PRESET = "MEMORY_PRESET"


class Severity(str, enum.Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    BLOCKER = "BLOCKER"


SEVERITY_RANK: dict[str, int] = {
    Severity.INFO.value: 0,
    Severity.WARNING.value: 1,
    Severity.ERROR.value: 2,
    Severity.BLOCKER.value: 3,
}


STANDARD_CATEGORIES: tuple[str, ...] = (
    "AI & Agents",
    "Automation",
    "Business",
    "Marketing",
    "Sales",
    "Customer Support",
    "Developer Tools",
    "Coding",
    "Research",
    "Data",
    "Productivity",
    "Finance",
    "Operations",
    "Content",
    "SEO",
    "Social Media",
    "Browser Automation",
    "DevOps",
    "Security",
    "Education",
    "Personal Assistant",
    "Enterprise",
)

SUPPORTED_LICENSES: tuple[str, ...] = (
    "Apache-2.0",
    "MIT",
    "GPL-3.0-only",
    "BSD-3-Clause",
    "MPL-2.0",
    "CC-BY-4.0",
    "CC-BY-SA-4.0",
    "Elastic-2.0",
    "SSPL-1.0",
    "PolyForm-Noncommercial-1.0.0",
    "Proprietary",
    "Unlicense",
)

#: MP22 event types emitted through the outbox (``package`` aggregate).
PACKAGE_EVENTS: tuple[str, ...] = (
    "PACKAGE_CREATED",
    "PACKAGE_VERSION_CREATED",
    "PACKAGE_VALIDATED",
    "PACKAGE_PUBLISHED",
    "PACKAGE_INSTALLED",
    "PACKAGE_UPDATED",
    "PACKAGE_ROLLED_BACK",
    "PACKAGE_FORKED",
    "PACKAGE_IMPORTED",
    "PACKAGE_EXPORTED",
    "PACKAGE_REVOKED",
    "SECURITY_SCAN_COMPLETED",
    "DEPENDENCY_RESOLUTION_FAILED",
)

#: Metric names owned by this domain.
PACKAGE_METRICS: tuple[str, ...] = (
    "package_install_total",
    "package_install_failed_total",
    "package_validation_total",
    "package_validation_failed_total",
    "package_update_total",
    "package_rollback_total",
    "package_download_total",
    "package_fork_total",
    "skill_usage_total",
    "template_usage_total",
)
