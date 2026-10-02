"""Browser workflow node executors.

Browser nodes desugar to the canonical ``browser.*`` tools and run through
Tool Runtime (registry -> policy -> authorization -> risk -> Browser Engine).
They never drive Chromium directly and never bypass policy gates:

- ``browser_agent``  — objective-driven task descriptor (agent runtime picks it up)
- ``browser_action`` — single validated action invocation descriptor
- ``browser_extract``— structured-extraction invocation descriptor

High-risk actions return ``WAITING`` (approval hook for MP19) instead of
executing blindly.
"""

from __future__ import annotations

from typing import Any, Dict

from openagent.browser.security import classify_risk, requires_approval, validate_url
from openagent.runtime.engine import resolve_expressions
from openagent.runtime.executors.base import (
    NodeExecutionContext,
    NodeExecutionResult,
    NodeExecutor,
    NodeRunStatus,
)


def _fail(message: str, code: str = "INVALID_CONFIG") -> NodeExecutionResult:
    return NodeExecutionResult(status=NodeRunStatus.FAILED, error=message, error_code=code)


class BrowserAgentNodeExecutor(NodeExecutor):
    """Objective-driven browser task node."""

    node_type = "browser_agent"
    default_timeout = 300
    required_capabilities = ["browser_control", "tool_execution"]

    async def execute(self, node_config: Dict[str, Any],
                      context: NodeExecutionContext) -> NodeExecutionResult:
        try:
            cfg = resolve_expressions(node_config, context)
        except Exception as e:
            return _fail(f"Failed to resolve expressions: {e}", "EXPRESSION_ERROR")
        objective = str(cfg.get("objective", "")).strip()
        if not objective:
            return _fail("browser_agent node requires 'objective'")
        max_steps = int(cfg.get("max_steps", 100))
        if not 1 <= max_steps <= 500:
            return _fail("'max_steps' must be 1..500")
        return NodeExecutionResult(
            status=NodeRunStatus.SUCCEEDED,
            outputs={
                "tool": "browser_agent",
                "objective": objective[:4000],
                "allowed_domains": cfg.get("allowed_domains", []),
                "max_steps": max_steps,
                "timeout": min(int(cfg.get("timeout", 300000)), 3600000),
                "browser_profile": cfg.get("browser_profile"),
                "risk_policy": cfg.get("risk_policy", {}),
                "credential_ref": cfg.get("credential_ref"),
            },
            metadata={"node_type": self.node_type, "max_steps": max_steps},
        )


class BrowserActionNodeExecutor(NodeExecutor):
    """Single browser action node (policy-gated, approval-aware)."""

    node_type = "browser_action"
    default_timeout = 120
    required_capabilities = ["browser_control", "tool_execution"]

    async def execute(self, node_config: Dict[str, Any],
                      context: NodeExecutionContext) -> NodeExecutionResult:
        try:
            cfg = resolve_expressions(node_config, context)
        except Exception as e:
            return _fail(f"Failed to resolve expressions: {e}", "EXPRESSION_ERROR")
        action_type = str(cfg.get("action_type", "")).upper()
        if not action_type:
            return _fail("browser_action node requires 'action_type'")
        risk = classify_risk(action_type)
        risk_policy = cfg.get("risk_policy", {}) or {}
        tool_map = {"NAVIGATE": "browser.navigate", "CLICK": "browser.click",
                    "TYPE": "browser.type", "FILL": "browser.fill",
                    "SELECT": "browser.select", "SCROLL": "browser.scroll",
                    "SCREENSHOT": "browser.screenshot", "EXTRACT": "browser.extract",
                    "UPLOAD": "browser.upload", "DOWNLOAD": "browser.download"}
        tool = tool_map.get(action_type, f"browser.{action_type.lower()}")
        if action_type == "NAVIGATE":
            url = str((cfg.get("input") or {}).get("url", cfg.get("url", "")))
            v = validate_url(url)
            if not v.valid:
                return _fail(f"Unsafe navigation blocked: {v.reason}", "POLICY_DENIED")
        if requires_approval(action_type, risk_policy) and not cfg.get("approved"):
            return NodeExecutionResult(
                status=NodeRunStatus.WAITING,
                outputs={"tool": tool, "action_type": action_type, "riskLevel": risk,
                         "requiresApproval": True,
                         "message": f"Action {action_type} (risk={risk}) parked for human approval"},
                metadata={"node_type": self.node_type, "risk": risk},
            )
        return NodeExecutionResult(
            status=NodeRunStatus.SUCCEEDED,
            outputs={"tool": tool, "action_type": action_type, "riskLevel": risk,
                     "arguments": cfg.get("input", {}), "requiresApproval": False},
            metadata={"node_type": self.node_type, "risk": risk},
        )


class BrowserExtractNodeExecutor(NodeExecutor):
    """Structured-extraction node."""

    node_type = "browser_extract"
    default_timeout = 60
    required_capabilities = ["browser_control", "read"]

    async def execute(self, node_config: Dict[str, Any],
                      context: NodeExecutionContext) -> NodeExecutionResult:
        try:
            cfg = resolve_expressions(node_config, context)
        except Exception as e:
            return _fail(f"Failed to resolve expressions: {e}", "EXPRESSION_ERROR")
        selector = str(cfg.get("selector", "")).strip()
        if not selector:
            return _fail("browser_extract node requires 'selector'")
        return NodeExecutionResult(
            status=NodeRunStatus.SUCCEEDED,
            outputs={"tool": "browser.extract", "riskLevel": "LOW",
                     "arguments": {"selector": selector,
                                   "attribute": cfg.get("attribute"),
                                   "multiple": bool(cfg.get("multiple", False))}},
            metadata={"node_type": self.node_type},
        )
