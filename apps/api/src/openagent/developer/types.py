"""MP28: canonical developer-platform type registry.

Single canonical extension architecture (§3, §13). There is exactly one
extension type registry, one permission catalog, and one trust model.
All extension kinds (agents, tools, workflow nodes, connectors, MCP,
skills, evaluators, providers, UI, templates) are entries here — never
parallel plugin systems.
"""

from __future__ import annotations

import enum


class ExtensionType(str, enum.Enum):
    AGENT = "agent"
    SKILL = "skill"
    TOOL = "tool"
    WORKFLOW_NODE = "workflow-node"
    CONNECTOR = "connector"
    MCP_SERVER = "mcp-server"
    MCP_TOOL = "mcp-tool"
    MCP_RESOURCE = "mcp-resource"
    MCP_PROMPT = "mcp-prompt"
    WORKFLOW_TEMPLATE = "workflow-template"
    EVALUATOR = "evaluator"
    MEMORY_PROVIDER = "memory-provider"
    MODEL_PROVIDER = "model-provider"
    MODEL_ADAPTER = "model-adapter"
    BROWSER_EXTENSION = "browser-extension"
    SANDBOX_PROFILE = "sandbox-profile"
    INTEGRATION = "integration"
    UI_EXTENSION = "ui-extension"
    AUTOMATION_PACK = "automation-pack"
    AGENT_TEAM = "agent-team"


EXTENSION_TYPES: tuple[str, ...] = tuple(t.value for t in ExtensionType)


class TrustLevel(str, enum.Enum):
    CORE = "CORE"
    VERIFIED = "VERIFIED"
    ORGANIZATION = "ORGANIZATION"
    COMMUNITY = "COMMUNITY"
    UNTRUSTED = "UNTRUSTED"


class LifecycleStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    PACKAGED = "PACKAGED"
    SIGNED = "SIGNED"
    PUBLISHED = "PUBLISHED"
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"
    DEPRECATED = "DEPRECATED"
    QUARANTINED = "QUARANTINED"
    REVOKED = "REVOKED"
    UNPUBLISHED = "UNPUBLISHED"


class EnvironmentName(str, enum.Enum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


# ---------------------------------------------------------------------------
# Permission catalog (§26). Every permission is explicit, reviewable,
# enforceable, auditable, revocable. Least privilege by default.
# ---------------------------------------------------------------------------

# name -> {description, risk: low|medium|high|critical, requires_approval}
PERMISSION_CATALOG: dict[str, dict[str, object]] = {
    "network:outbound": {
        "description": "Limited outbound HTTPS to declared allowlisted hosts",
        "risk": "medium",
        "requires_approval": False,
    },
    "network:restricted": {
        "description": "Restricted/private network access (SSRF-sensitive)",
        "risk": "critical",
        "requires_approval": True,
    },
    "filesystem:workspace": {
        "description": "Read/write inside the extension workspace only",
        "risk": "low",
        "requires_approval": False,
    },
    "filesystem:artifact": {
        "description": "Read/write declared artifacts only",
        "risk": "low",
        "requires_approval": False,
    },
    "tool:execute": {
        "description": "Invoke other tools via the canonical Tool Runtime",
        "risk": "medium",
        "requires_approval": False,
    },
    "connector:use": {
        "description": "Use declared connector connections",
        "risk": "medium",
        "requires_approval": False,
    },
    "memory:read": {"description": "Read scoped memory", "risk": "medium", "requires_approval": False},
    "memory:write": {"description": "Write scoped memory", "risk": "medium", "requires_approval": False},
    "browser:use": {
        "description": "Drive browser sessions under browser policy",
        "risk": "high",
        "requires_approval": True,
    },
    "sandbox:execute": {
        "description": "Execute code inside the Sandbox boundary",
        "risk": "medium",
        "requires_approval": False,
    },
    "mcp:connect": {
        "description": "Connect to declared MCP servers",
        "risk": "medium",
        "requires_approval": False,
    },
    "secret:access": {
        "description": "Access declared secret references (never values)",
        "risk": "high",
        "requires_approval": True,
    },
    "workflow:execute": {
        "description": "Start workflow executions",
        "risk": "medium",
        "requires_approval": False,
    },
    "agent:invoke": {
        "description": "Invoke sub-agents under policy",
        "risk": "medium",
        "requires_approval": False,
    },
    "model:invoke": {
        "description": "Invoke models via the Model Router",
        "risk": "low",
        "requires_approval": False,
    },
    "evaluation:run": {
        "description": "Run evaluators on observable outputs",
        "risk": "low",
        "requires_approval": False,
    },
    "webhook:receive": {
        "description": "Receive inbound webhooks on declared endpoints",
        "risk": "medium",
        "requires_approval": False,
    },
    "storage:use": {
        "description": "Use object storage within quota",
        "risk": "low",
        "requires_approval": False,
    },
    "billing:read": {
        "description": "Read own usage/entitlement state",
        "risk": "low",
        "requires_approval": False,
    },
}

# Permissions that can never be granted to COMMUNITY/UNTRUSTED extensions
# without human review + sandbox confinement.
HIGH_RISK_PERMISSIONS = frozenset({
    "network:restricted",
    "browser:use",
    "secret:access",
})

# Default least-privilege set for newly scaffolded projects.
DEFAULT_PERMISSIONS: tuple[str, ...] = ("tool:execute", "filesystem:workspace")


# ---------------------------------------------------------------------------
# Event catalog (§46, §92): versioned developer event schemas.
# ---------------------------------------------------------------------------

DEVELOPER_EVENTS: tuple[str, ...] = (
    "agent.run.started.v1",
    "agent.run.completed.v1",
    "agent.run.failed.v1",
    "workflow.execution.started.v1",
    "workflow.execution.completed.v1",
    "workflow.execution.failed.v1",
    "tool.invoked.v1",
    "tool.completed.v1",
    "tool.failed.v1",
    "connector.event.received.v1",
    "mcp.server.connected.v1",
    "mcp.server.disconnected.v1",
    "deployment.started.v1",
    "deployment.completed.v1",
    "deployment.failed.v1",
    "extension.published.v1",
    "extension.installed.v1",
    "extension.quarantined.v1",
    "package.published.v1",
    "evaluation.completed.v1",
)


# Compatibility matrix (§61): SDK/API/extension-API generations known good.
COMPATIBILITY_MATRIX: dict[str, dict[str, str]] = {
    "1.x": {
        "openagent": ">=1.0.0 <2.0.0",
        "sdk": ">=1.0.0 <2.0.0",
        "extension_api": "1.x",
        "manifest": "1",
        "api_version": "v1",
    }
}

EXTENSION_API_VERSION = "1.x"
MANIFEST_VERSION = "1"
SDK_VERSION = "1.0.0"
API_VERSION = "v1"
