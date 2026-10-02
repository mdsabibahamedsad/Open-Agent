"""Code workflow node executors.

Code nodes desugar to the canonical ``code.*`` tools and run through Tool
Runtime (registry -> policy -> authorization -> risk -> Code Engine). They
never touch the filesystem or git directly and never bypass policy gates:

- ``code_agent`` — objective-driven coding task descriptor
- ``code_search`` / ``code_read`` — bounded read-only descriptors
- ``code_patch`` — validated patch invocation descriptor
- ``code_test`` / ``code_lint`` — profile-gated execution descriptors
- ``code_review`` — review invocation descriptor
- ``git_commit`` / ``create_pr`` — gated commit / PR-draft descriptors

High-risk operations return ``WAITING`` (approval hook for MP19) instead of
executing blindly.
"""

from __future__ import annotations

from typing import Any, Dict

from openagent.code.security import (
    EXECUTION_PROFILES,
    classify_tool_risk,
    command_allowed_by_profile,
    resolve_profile,
    tool_requires_approval,
)
from openagent.runtime.engine import resolve_expressions
from openagent.runtime.executors.base import (
    NodeExecutionContext,
    NodeExecutionResult,
    NodeExecutor,
    NodeRunStatus,
)


def _fail(message: str, code: str = "INVALID_CONFIG") -> NodeExecutionResult:
    return NodeExecutionResult(status=NodeRunStatus.FAILED, error=message,
                               error_code=code)


def _waiting(tool: str, message: str, risk: str) -> NodeExecutionResult:
    return NodeExecutionResult(
        status=NodeRunStatus.WAITING,
        outputs={"tool": tool, "requiresApproval": True, "riskLevel": risk,
                 "message": message},
        metadata={"requires_approval": True, "risk": risk},
    )


class CodeAgentNodeExecutor(NodeExecutor):
    """Objective-driven coding task descriptor."""

    node_type = "code_agent"
    default_timeout = 600
    required_capabilities = ["code_execution", "tool_execution"]

    async def execute(self, node_config: Dict[str, Any],
                      context: 'NodeExecutionContext') -> 'NodeExecutionResult':
        try:
            cfg = resolve_expressions(node_config, context)
        except Exception as e:
            return _fail(f"Failed to resolve expressions: {e}", "EXPRESSION_ERROR")
        objective = str(cfg.get("objective", "")).strip()
        if not objective:
            return _fail("code_agent node requires 'objective'")
        if not cfg.get("repository_id") and not cfg.get("repository"):
            return _fail("code_agent node requires 'repository_id' or 'repository'")
        max_steps = int(cfg.get("max_steps", 50))
        if not 1 <= max_steps <= 200:
            return _fail("'max_steps' must be 1..200")
        return NodeExecutionResult(
            status=NodeRunStatus.SUCCEEDED,
            outputs={
                "tool": "code_agent",
                "objective": objective[:4000],
                "repository_id": cfg.get("repository_id") or cfg.get("repository"),
                "branch_strategy": cfg.get("branch_strategy", "openagent/task/<task-id>"),
                "max_steps": max_steps,
                "max_duration": min(int(cfg.get("max_duration", 3600)), 8 * 3600),
                "model_policy": cfg.get("model_policy", {}),
                "execution_policy": cfg.get("execution_policy", {}),
                "review_policy": cfg.get("review_policy", {}),
                "approval_policy": cfg.get("approval_policy", {}),
                "credential_ref": cfg.get("credential_ref"),
            },
            metadata={"node_type": self.node_type, "max_steps": max_steps},
        )


class CodeSearchNodeExecutor(NodeExecutor):
    node_type = "code_search"
    default_timeout = 60
    required_capabilities = ["code_execution", "read"]

    async def execute(self, node_config: Dict[str, Any],
                      context: 'NodeExecutionContext') -> 'NodeExecutionResult':
        try:
            cfg = resolve_expressions(node_config, context)
        except Exception as e:
            return _fail(f"Failed to resolve expressions: {e}", "EXPRESSION_ERROR")
        if not str(cfg.get("query", "")).strip():
            return _fail("code_search node requires 'query'")
        return NodeExecutionResult(
            status=NodeRunStatus.SUCCEEDED,
            outputs={"tool": "code.search", "riskLevel": "LOW",
                     "arguments": {"query": cfg["query"][:500],
                                   "regex": bool(cfg.get("regex", False)),
                                   "symbol": cfg.get("symbol"),
                                   "workspace_id": cfg.get("workspace_id"),
                                   "repository_id": cfg.get("repository_id")}},
            metadata={"node_type": self.node_type},
        )


class CodeReadNodeExecutor(NodeExecutor):
    node_type = "code_read"
    default_timeout = 60
    required_capabilities = ["code_execution", "read"]

    async def execute(self, node_config: Dict[str, Any],
                      context: 'NodeExecutionContext') -> 'NodeExecutionResult':
        try:
            cfg = resolve_expressions(node_config, context)
        except Exception as e:
            return _fail(f"Failed to resolve expressions: {e}", "EXPRESSION_ERROR")
        if not str(cfg.get("path", "")).strip():
            return _fail("code_read node requires 'path'")
        return NodeExecutionResult(
            status=NodeRunStatus.SUCCEEDED,
            outputs={"tool": "code.file.read", "riskLevel": "LOW",
                     "arguments": {"path": cfg["path"],
                                   "start": cfg.get("start"), "end": cfg.get("end"),
                                   "workspace_id": cfg.get("workspace_id")}},
            metadata={"node_type": self.node_type},
        )


class CodePatchNodeExecutor(NodeExecutor):
    node_type = "code_patch"
    default_timeout = 120
    required_capabilities = ["code_execution", "tool_execution"]

    async def execute(self, node_config: Dict[str, Any],
                      context: 'NodeExecutionContext') -> 'NodeExecutionResult':
        try:
            cfg = resolve_expressions(node_config, context)
        except Exception as e:
            return _fail(f"Failed to resolve expressions: {e}", "EXPRESSION_ERROR")
        if not str(cfg.get("diff", "")).strip():
            return _fail("code_patch node requires 'diff'")
        if not cfg.get("task_id"):
            return _fail("code_patch node requires 'task_id'")
        risk = classify_tool_risk("code.patch.apply")
        if tool_requires_approval("code.patch.apply",
                                  cfg.get("risk_policy")) and not cfg.get("approved"):
            # Sensitive-path patches park for approval; ordinary patches flow.
            return NodeExecutionResult(
                status=NodeRunStatus.SUCCEEDED,
                outputs={"tool": "code.patch.apply", "riskLevel": risk,
                         "arguments": {"task_id": cfg["task_id"], "diff": cfg["diff"]},
                         "note": "service re-checks sensitive paths at apply time"},
                metadata={"node_type": self.node_type, "risk": risk},
            )
        return NodeExecutionResult(
            status=NodeRunStatus.SUCCEEDED,
            outputs={"tool": "code.patch.apply", "riskLevel": risk,
                     "arguments": {"task_id": cfg["task_id"], "diff": cfg["diff"],
                                   "approved": bool(cfg.get("approved", False))}},
            metadata={"node_type": self.node_type, "risk": risk},
        )


class _ExecutionNodeExecutor(NodeExecutor):
    """Shared profile-gated execution descriptor (test/lint/typecheck/build)."""
    node_type = "code_test"
    tool_name = "code.test.run"
    profile = "TEST"

    async def execute(self, node_config: Dict[str, Any],
                      context: 'NodeExecutionContext') -> 'NodeExecutionResult':
        try:
            cfg = resolve_expressions(node_config, context)
        except Exception as e:
            return _fail(f"Failed to resolve expressions: {e}", "EXPRESSION_ERROR")
        command = str(cfg.get("command", "")).strip()
        if not command:
            return _fail(f"{self.node_type} node requires 'command'")
        prof = resolve_profile(str(cfg.get("profile", self.profile)))
        if not command_allowed_by_profile(command, prof):
            return _fail(
                f"Command not allowed by {prof.name} profile: {command[:200]}",
                "POLICY_DENIED")
        return NodeExecutionResult(
            status=NodeRunStatus.SUCCEEDED,
            outputs={"tool": self.tool_name, "riskLevel": "MEDIUM",
                     "arguments": {"command": command,
                                   "task_id": cfg.get("task_id"),
                                   "workspace_id": cfg.get("workspace_id")}},
            metadata={"node_type": self.node_type, "profile": prof.name},
        )


class CodeTestNodeExecutor(_ExecutionNodeExecutor):
    node_type = "code_test"
    tool_name = "code.test.run"
    profile = "TEST"
    default_timeout = 1200
    required_capabilities = ["code_execution", "tool_execution"]


class CodeLintNodeExecutor(_ExecutionNodeExecutor):
    node_type = "code_lint"
    tool_name = "code.lint.run"
    profile = "LINT"
    default_timeout = 600
    required_capabilities = ["code_execution", "tool_execution"]


class CodeReviewNodeExecutor(NodeExecutor):
    node_type = "code_review"
    default_timeout = 300
    required_capabilities = ["code_execution", "read"]

    async def execute(self, node_config: Dict[str, Any],
                      context: 'NodeExecutionContext') -> 'NodeExecutionResult':
        try:
            cfg = resolve_expressions(node_config, context)
        except Exception as e:
            return _fail(f"Failed to resolve expressions: {e}", "EXPRESSION_ERROR")
        if not cfg.get("task_id") and not cfg.get("diff"):
            return _fail("code_review node requires 'task_id' or 'diff'")
        return NodeExecutionResult(
            status=NodeRunStatus.SUCCEEDED,
            outputs={"tool": "code.review", "riskLevel": "LOW",
                     "arguments": {"task_id": cfg.get("task_id"),
                                   "diff": cfg.get("diff")},
                     "reviewers": cfg.get("reviewers", ["static"])},
            metadata={"node_type": self.node_type},
        )


class GitCommitNodeExecutor(NodeExecutor):
    node_type = "git_commit"
    default_timeout = 120
    required_capabilities = ["code_execution", "tool_execution"]

    async def execute(self, node_config: Dict[str, Any],
                      context: 'NodeExecutionContext') -> 'NodeExecutionResult':
        try:
            cfg = resolve_expressions(node_config, context)
        except Exception as e:
            return _fail(f"Failed to resolve expressions: {e}", "EXPRESSION_ERROR")
        if not str(cfg.get("message", "")).strip():
            return _fail("git_commit node requires 'message'")
        if not cfg.get("task_id"):
            return _fail("git_commit node requires 'task_id'")
        return NodeExecutionResult(
            status=NodeRunStatus.SUCCEEDED,
            outputs={"tool": "code.git.commit", "riskLevel": "MEDIUM",
                     "arguments": {"task_id": cfg["task_id"],
                                   "message": cfg["message"][:2000]}},
            metadata={"node_type": self.node_type},
        )


class CreatePRNodeExecutor(NodeExecutor):
    node_type = "create_pr"
    default_timeout = 120
    required_capabilities = ["code_execution", "tool_execution"]

    async def execute(self, node_config: Dict[str, Any],
                      context: 'NodeExecutionContext') -> 'NodeExecutionResult':
        try:
            cfg = resolve_expressions(node_config, context)
        except Exception as e:
            return _fail(f"Failed to resolve expressions: {e}", "EXPRESSION_ERROR")
        if not str(cfg.get("title", "")).strip():
            return _fail("create_pr node requires 'title'")
        if not cfg.get("task_id"):
            return _fail("create_pr node requires 'task_id'")
        if cfg.get("merge") or cfg.get("auto_merge"):
            return _fail("Automatic merging is never permitted by policy",
                         "POLICY_DENIED")
        return NodeExecutionResult(
            status=NodeRunStatus.SUCCEEDED,
            outputs={"tool": "code.pr.prepare", "riskLevel": "MEDIUM",
                     "arguments": {"task_id": cfg["task_id"],
                                   "title": cfg["title"][:500],
                                   "summary": cfg.get("summary", ""),
                                   "open": bool(cfg.get("open", False))}},
            metadata={"node_type": self.node_type},
        )
