"""Code agent domain package (provider-neutral, policy-aware)."""

from openagent.code.security import (
    classify_tool_risk,
    command_allowed_by_profile,
    detect_repo_injection,
    filter_repo_instructions,
    is_protected_branch,
    is_retry_safe_tool,
    is_sensitive_filename,
    label_untrusted_code,
    redact_dict,
    redact_text,
    resolve_profile,
    scan_text_for_secrets,
    task_branch_name,
    tool_requires_approval,
    validate_workspace_path,
)
from openagent.code.service import (
    CodeNotFound,
    CodePolicyDenied,
    CodeSecurityError,
    CodeService,
)
from openagent.code.tools import CODE_TOOLS, CodeToolExecutor, ensure_code_tools_registered
from openagent.code.client import CodeClient

__all__ = [
    "CodeService", "CodeSecurityError", "CodePolicyDenied", "CodeNotFound",
    "CODE_TOOLS", "CodeToolExecutor", "ensure_code_tools_registered",
    "CodeClient",
    "classify_tool_risk", "tool_requires_approval", "is_retry_safe_tool",
    "validate_workspace_path", "scan_text_for_secrets", "is_sensitive_filename",
    "detect_repo_injection", "label_untrusted_code", "filter_repo_instructions",
    "is_protected_branch", "task_branch_name", "resolve_profile",
    "command_allowed_by_profile", "redact_text", "redact_dict",
]
