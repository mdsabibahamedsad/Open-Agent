"""Action taxonomy + high-risk defaults (MP19).

Standardized categories; extensions go through the registry so tools/MCP/
workflows cannot invent privileged categories via free-form strings.
"""

from __future__ import annotations

ACTION_CATEGORIES: tuple[str, ...] = (
    "READ",
    "WRITE",
    "UPDATE",
    "DELETE",
    "DEPLOY",
    "EXECUTE_CODE",
    "NETWORK_ACCESS",
    "SEND_MESSAGE",
    "SEND_EMAIL",
    "PUBLISH_CONTENT",
    "MODIFY_REPOSITORY",
    "CREATE_COMMIT",
    "CREATE_BRANCH",
    "CREATE_PULL_REQUEST",
    "MERGE_CODE",
    "CHANGE_CONFIGURATION",
    "ACCESS_CREDENTIAL",
    "ACCESS_SENSITIVE_DATA",
    "FINANCIAL_ACTION",
    "ACCOUNT_ACTION",
    "USER_ADMINISTRATION",
    "ORGANIZATION_ADMINISTRATION",
    "INFRASTRUCTURE_ACTION",
    "BROWSER_EXTERNAL_ACTION",
    "MCP_ACTION",
    "SANDBOX_EXECUTION",
)

# Conservative high-risk defaults: category -> minimum risk floor + approval.
HIGH_RISK_DEFAULTS: dict[str, dict[str, object]] = {
    "DELETE": {"min_risk": "HIGH", "require_approval": True},
    "DEPLOY": {"min_risk": "HIGH", "require_approval": True},
    "EXECUTE_CODE": {"min_risk": "MEDIUM", "require_approval": False},
    "SEND_MESSAGE": {"min_risk": "MEDIUM", "require_approval": True},
    "SEND_EMAIL": {"min_risk": "MEDIUM", "require_approval": True},
    "PUBLISH_CONTENT": {"min_risk": "HIGH", "require_approval": True},
    "MODIFY_REPOSITORY": {"min_risk": "MEDIUM", "require_approval": False},
    "MERGE_CODE": {"min_risk": "HIGH", "require_approval": True},
    "CHANGE_CONFIGURATION": {"min_risk": "MEDIUM", "require_approval": True},
    "ACCESS_CREDENTIAL": {"min_risk": "CRITICAL", "require_approval": True},
    "ACCESS_SENSITIVE_DATA": {"min_risk": "HIGH", "require_approval": True},
    "FINANCIAL_ACTION": {"min_risk": "HIGH", "require_approval": True},
    "ACCOUNT_ACTION": {"min_risk": "HIGH", "require_approval": True},
    "USER_ADMINISTRATION": {"min_risk": "HIGH", "require_approval": True},
    "ORGANIZATION_ADMINISTRATION": {"min_risk": "CRITICAL", "require_approval": True},
    "INFRASTRUCTURE_ACTION": {"min_risk": "HIGH", "require_approval": True},
    "BROWSER_EXTERNAL_ACTION": {"min_risk": "HIGH", "require_approval": True},
    "MCP_ACTION": {"min_risk": "MEDIUM", "require_approval": False},
    "SANDBOX_EXECUTION": {"min_risk": "MEDIUM", "require_approval": False},
}

# Explicit always-deny patterns (deny-by-default): matched against ActionContext.
ALWAYS_DENY_RULES: tuple[dict[str, str], ...] = (
    {"match": "action_category==DELETE+environment==production+target_type==database",
     "reason": "Production database deletion is never allowed"},
    {"match": "privilege_level==platform+tenant_scope==platform+action_category==ORGANIZATION_ADMINISTRATION",
     "reason": "Platform privilege actions require platform-owner flow, never org path"},
)

_CUSTOM_CATEGORIES: set[str] = set()


def register_category(name: str) -> str:
    normalized = (name or "").strip().upper()
    if not normalized or len(normalized) > 64:
        raise ValueError("Invalid category name")
    if not all(c.isalnum() or c == "_" for c in normalized):
        raise ValueError("Category must be alphanumeric/underscore")
    if normalized in ACTION_CATEGORIES or normalized in _CUSTOM_CATEGORIES:
        return normalized
    _CUSTOM_CATEGORIES.add(normalized)
    return normalized


def is_known_category(name: str) -> bool:
    return (name or "").upper() in ACTION_CATEGORIES or (name or "").upper() in _CUSTOM_CATEGORIES


def all_categories() -> list[str]:
    return [*ACTION_CATEGORIES, *sorted(_CUSTOM_CATEGORIES)]


def high_risk_default(category: str) -> dict[str, object]:
    return HIGH_RISK_DEFAULTS.get((category or "").upper(), {})
