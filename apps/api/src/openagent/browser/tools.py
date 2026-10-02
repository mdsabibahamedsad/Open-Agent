"""Canonical browser tool definitions + Tool Runtime registration.

Every browser capability goes through Tool Runtime; this module declares the
tool catalogue and a validating executor that gates through BrowserService.
"""

from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

import structlog

from openagent.browser.security import classify_risk

logger = structlog.get_logger("browser.tools")

BROWSER_TOOLS: list[dict[str, Any]] = [
    {"name": "browser.open", "description": "Open/navigate to a URL in a browser session",
     "input_schema": {"type": "object", "properties": {
         "sessionId": {"type": "string"}, "url": {"type": "string"},
         "waitUntil": {"type": "string"}, "timeout": {"type": "number"}}, "required": ["sessionId", "url"]}},
    {"name": "browser.navigate", "description": "Navigate active page to URL",
     "input_schema": {"type": "object", "properties": {
         "sessionId": {"type": "string"}, "pageId": {"type": "string"}, "url": {"type": "string"}},
         "required": ["sessionId", "url"]}},
    {"name": "browser.click", "description": "Click an element",
     "input_schema": {"type": "object", "properties": {
         "sessionId": {"type": "string"}, "pageId": {"type": "string"}, "selector": {"type": "string"}},
         "required": ["sessionId", "selector"]}},
    {"name": "browser.type", "description": "Type text into an element",
     "input_schema": {"type": "object", "properties": {
         "sessionId": {"type": "string"}, "selector": {"type": "string"}, "text": {"type": "string"}},
         "required": ["sessionId", "selector", "text"]}},
    {"name": "browser.select", "description": "Select dropdown option",
     "input_schema": {"type": "object", "properties": {
         "sessionId": {"type": "string"}, "selector": {"type": "string"}, "value": {"type": "string"}},
         "required": ["sessionId", "selector", "value"]}},
    {"name": "browser.scroll", "description": "Scroll page",
     "input_schema": {"type": "object", "properties": {
         "sessionId": {"type": "string"}, "pageId": {"type": "string"},
         "x": {"type": "number"}, "y": {"type": "number"}}, "required": ["sessionId"]}},
    {"name": "browser.press", "description": "Press a key",
     "input_schema": {"type": "object", "properties": {
         "sessionId": {"type": "string"}, "key": {"type": "string"}}, "required": ["sessionId", "key"]}},
    {"name": "browser.wait", "description": "Wait for condition",
     "input_schema": {"type": "object", "properties": {
         "sessionId": {"type": "string"}, "selector": {"type": "string"}, "timeout": {"type": "number"}},
         "required": ["sessionId"]}},
    {"name": "browser.screenshot", "description": "Capture screenshot",
     "input_schema": {"type": "object", "properties": {
         "sessionId": {"type": "string"}, "pageId": {"type": "string"}, "fullPage": {"type": "boolean"}},
         "required": ["sessionId"]}},
    {"name": "browser.extract", "description": "Extract structured data from page",
     "input_schema": {"type": "object", "properties": {
         "sessionId": {"type": "string"}, "selector": {"type": "string"},
         "attribute": {"type": "string"}, "multiple": {"type": "boolean"}},
         "required": ["sessionId", "selector"]}},
    {"name": "browser.upload", "description": "Upload files (approval-gated)",
     "input_schema": {"type": "object", "properties": {
         "sessionId": {"type": "string"}, "selector": {"type": "string"}, "files": {"type": "array"}},
         "required": ["sessionId", "selector", "files"]}},
    {"name": "browser.download", "description": "Download a file",
     "input_schema": {"type": "object", "properties": {
         "sessionId": {"type": "string"}, "selector": {"type": "string"}}, "required": ["sessionId", "selector"]}},
    {"name": "browser.tabs", "description": "List/manage tabs",
     "input_schema": {"type": "object", "properties": {
         "sessionId": {"type": "string"}, "action": {"type": "string"}}, "required": ["sessionId"]}},
    {"name": "browser.back", "description": "History back",
     "input_schema": {"type": "object", "properties": {
         "sessionId": {"type": "string"}, "pageId": {"type": "string"}}, "required": ["sessionId"]}},
    {"name": "browser.forward", "description": "History forward",
     "input_schema": {"type": "object", "properties": {
         "sessionId": {"type": "string"}, "pageId": {"type": "string"}}, "required": ["sessionId"]}},
    {"name": "browser.reload", "description": "Reload page",
     "input_schema": {"type": "object", "properties": {
         "sessionId": {"type": "string"}, "pageId": {"type": "string"}}, "required": ["sessionId"]}},
    {"name": "browser.close", "description": "Close session",
     "input_schema": {"type": "object", "properties": {
         "sessionId": {"type": "string"}}, "required": ["sessionId"]}},
]

for _t in BROWSER_TOOLS:
    _action = _t["name"].split(".")[1].upper()
    _t["risk_level"] = classify_risk(_action if _action != "OPEN" else "NAVIGATE")
    _t["capabilities"] = ["browser_control", "network"]


class BrowserToolExecutor:
    """ToolRuntime executor: validates, resolves task/page context, delegates to BrowserService."""

    executor_id = "browser"

    def __init__(self, service_factory):
        self._factory = service_factory

    @property
    def supported_tools(self) -> list[str]:
        return [t["name"] for t in BROWSER_TOOLS]

    def get_tool_schema(self, tool_name: str) -> Optional[dict[str, Any]]:
        for t in BROWSER_TOOLS:
            if t["name"] == tool_name:
                return t["input_schema"]
        return None

    async def validate_arguments(self, tool_name: str, arguments: dict[str, Any]) -> bool:
        schema = self.get_tool_schema(tool_name)
        if not schema:
            return False
        for req in schema.get("required", []):
            if req not in arguments:
                return False
        return True

    def list_tools(self) -> list[dict[str, Any]]:
        return BROWSER_TOOLS

    async def execute(self, tool_name: str, arguments: dict[str, Any],
                      context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        from openagent.browser.service import BrowserPolicyDenied, BrowserSecurityError
        ctx = context or {}
        db = ctx.get("db")
        if db is None:
            return {"error": "browser tool requires database context (db)", "requiresContext": True}
        service = self._factory(db)
        org_id = ctx.get("organization_id")
        if not org_id:
            return {"error": "organization_id context required", "requiresContext": True}
        task_id = ctx.get("task_id") or arguments.get("taskId")
        page_id = arguments.get("pageId")
        action_map = {"browser.open": "NAVIGATE", "browser.press": "PRESS_KEY"}
        action = action_map.get(tool_name, tool_name.split(".")[1].upper())
        try:
            if tool_name in ("browser.tabs", "browser.close"):
                return {"tool": tool_name, "deferred": True,
                        "note": "session-level op handled by BrowserService API"}
            if not task_id or not page_id:
                return {"error": "taskId and pageId context required", "requiresContext": True}
            result = await service.execute_task_action(
                task_id=UUID(str(task_id)), organization_id=UUID(str(org_id)),
                action_type=action, page_id=UUID(str(page_id)),
                input_data=arguments, approved=bool(arguments.get("approved")))
            return result
        except BrowserPolicyDenied as e:
            return {"error": str(e), "policyDenied": True}
        except BrowserSecurityError as e:
            return {"error": str(e)}


def ensure_browser_tools_registered(db_session_factory=None) -> "BrowserToolExecutor":
    """Register browser tools + executor with Tool Runtime (idempotent).

    Every browser capability flows through Tool Registry -> Policy ->
    Authorization -> Risk -> Credential Resolution -> Browser Engine.
    """
    from openagent.runtime.tools import tool_executor_registry, tool_registry
    from openagent.runtime.tools import ToolDefinition as RuntimeToolDefinition

    executor = BrowserToolExecutor(service_factory=_service_factory)
    if tool_executor_registry.get_executor("browser") is None:
        tool_executor_registry.register(executor)
    for t in BROWSER_TOOLS:
        if tool_registry.get_latest(t["name"]) is None:
            tool_registry.register(RuntimeToolDefinition(
                id=t["name"], name=t["name"], description=t["description"],
                input_schema=t["input_schema"], capabilities=t["capabilities"],
                risk_level=t["risk_level"].lower(), executor_id="browser",
                metadata={"category": "browser"},
            ))
    return executor


def _service_factory(db):
    from openagent.browser.service import BrowserService
    return BrowserService(db)
