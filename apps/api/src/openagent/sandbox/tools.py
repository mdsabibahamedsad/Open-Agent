"""Canonical sandbox tool definitions + Tool Runtime registration.

Every sandbox capability flows through Tool Registry -> Policy ->
Authorization -> Risk -> Sandbox Manager. Agents never touch providers.
"""

from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

import structlog

from openagent.sandbox.security import classify_sandbox_tool_risk

logger = structlog.get_logger("sandbox.tools")

SANDBOX_TOOLS: list[dict[str, Any]] = [
    {"name": "sandbox.create",
     "description": "Create an isolated sandbox from a profile (workspace mount optional)",
     "input_schema": {"type": "object", "properties": {
         "profile": {"type": "string"}, "workspaceHostPath": {"type": "string"},
         "workspaceMode": {"type": "string"}, "ttlSeconds": {"type": "number"}},
      "required": []}},
    {"name": "sandbox.execute",
     "description": "Policy-gated command execution inside a sandbox",
     "input_schema": {"type": "object", "properties": {
         "sandboxId": {"type": "string"}, "command": {"type": "string"},
         "workdir": {"type": "string"}, "timeoutSeconds": {"type": "number"},
         "approved": {"type": "boolean"}}, "required": ["sandboxId", "command"]}},
    {"name": "sandbox.read",
     "description": "Read a sandbox-authorized file (paths never leave the server)",
     "input_schema": {"type": "object", "properties": {
         "sandboxId": {"type": "string"}, "path": {"type": "string"}},
      "required": ["sandboxId", "path"]}},
    {"name": "sandbox.write",
     "description": "Write a file through the sandbox boundary (profile-gated)",
     "input_schema": {"type": "object", "properties": {
         "sandboxId": {"type": "string"}, "path": {"type": "string"},
         "content": {"type": "string"}}, "required": ["sandboxId", "path", "content"]}},
    {"name": "sandbox.upload",
     "description": "Stage an artifact into a sandbox (validated + scanned)",
     "input_schema": {"type": "object", "properties": {
         "sandboxId": {"type": "string"}, "name": {"type": "string"},
         "contentRef": {"type": "string"}}, "required": ["sandboxId", "name"]}},
    {"name": "sandbox.download",
     "description": "Export a sandbox artifact via a controlled storage ref",
     "input_schema": {"type": "object", "properties": {
         "sandboxId": {"type": "string"}, "artifactId": {"type": "string"}},
      "required": ["sandboxId", "artifactId"]}},
    {"name": "sandbox.stop",
     "description": "Stop a sandbox (running executions are cancelled)",
     "input_schema": {"type": "object", "properties": {
         "sandboxId": {"type": "string"}}, "required": ["sandboxId"]}},
    {"name": "sandbox.destroy",
     "description": "Destroy a sandbox and release its leases/credentials",
     "input_schema": {"type": "object", "properties": {
         "sandboxId": {"type": "string"}}, "required": ["sandboxId"]}},
]

for _t in SANDBOX_TOOLS:
    _t["risk_level"] = classify_sandbox_tool_risk(_t["name"])
    _t["capabilities"] = ["sandbox_execution",
                          "read" if _t["name"] in ("sandbox.read", "sandbox.download")
                          else "write"]


class SandboxToolExecutor:
    """ToolRuntime executor: validates, resolves sandbox context, delegates."""

    executor_id = "sandbox"

    def __init__(self, service_factory):
        self._factory = service_factory

    @property
    def supported_tools(self) -> list[str]:
        return [t["name"] for t in SANDBOX_TOOLS]

    def get_tool_schema(self, tool_name: str) -> Optional[dict[str, Any]]:
        for t in SANDBOX_TOOLS:
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
        return SANDBOX_TOOLS

    async def execute(self, tool_name: str, arguments: dict[str, Any],
                      context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        from openagent.sandbox.service import (
            SandboxNotFound, SandboxPolicyDenied, SandboxSecurityError)
        ctx = context or {}
        db = ctx.get("db")
        if db is None:
            return {"error": "sandbox tool requires database context (db)",
                    "requiresContext": True}
        service = self._factory(db)
        org_id = ctx.get("organization_id")
        if not org_id:
            return {"error": "organization_id context required", "requiresContext": True}
        org = UUID(str(org_id))
        actor = UUID(str(ctx["actor"])) if ctx.get("actor") else None
        try:
            if tool_name == "sandbox.create":
                sb = await service.create_sandbox(
                    organization_id=org,
                    profile=str(arguments.get("profile", "TEST")),
                    owner_id=actor,
                    task_id=UUID(str(ctx["task_id"])) if ctx.get("task_id") else None,
                    workspace_host_path=arguments.get("workspaceHostPath"),
                    workspace_mode=str(arguments.get("workspaceMode", "WORKSPACE_RW")),
                    ttl_seconds=int(arguments.get("ttlSeconds", 3600)))
                return {"sandbox_id": str(sb.id), "status": str(sb.status),
                        "profile": sb.profile}
            sb_id = UUID(str(arguments["sandboxId"]))
            if tool_name == "sandbox.execute":
                return await service.execute(
                    sandbox_id=sb_id, organization_id=org,
                    command=arguments["command"],
                    workdir=str(arguments.get("workdir", "/workspace")),
                    task_id=UUID(str(ctx["task_id"])) if ctx.get("task_id") else None,
                    actor=actor,
                    owner=str(ctx.get("owner") or ctx.get("task_id") or "tool"),
                    timeout_seconds=(int(arguments["timeoutSeconds"])
                                     if arguments.get("timeoutSeconds") else None),
                    approved=bool(arguments.get("approved", False)))
            if tool_name == "sandbox.stop":
                sb = await service.stop_sandbox(sb_id, org, actor)
                return {"sandbox_id": str(sb.id), "status": str(sb.status)}
            if tool_name == "sandbox.destroy":
                await service.destroy_sandbox(sb_id, org, actor)
                return {"sandbox_id": str(sb_id), "status": "DESTROYED"}
            if tool_name in ("sandbox.read", "sandbox.write",
                             "sandbox.upload", "sandbox.download"):
                return {"error": f"{tool_name} is mediated via artifacts/execute; "
                                 "use sandbox.execute with explicit artifact paths",
                        "policyDenied": False}
            return {"error": f"Unknown sandbox tool: {tool_name}"}
        except SandboxPolicyDenied as e:
            return {"error": str(e), "policyDenied": True}
        except SandboxSecurityError as e:
            return {"error": str(e)}
        except SandboxNotFound as e:
            return {"error": str(e), "notFound": True}


def ensure_sandbox_tools_registered(db_session_factory=None) -> "SandboxToolExecutor":
    """Register sandbox tools + executor with Tool Runtime (idempotent)."""
    from openagent.runtime.tools import tool_executor_registry, tool_registry
    from openagent.runtime.tools import ToolDefinition as RuntimeToolDefinition

    executor = SandboxToolExecutor(service_factory=_service_factory)
    if tool_executor_registry.get_executor("sandbox") is None:
        tool_executor_registry.register(executor)
    for t in SANDBOX_TOOLS:
        if tool_registry.get_latest(t["name"]) is None:
            tool_registry.register(RuntimeToolDefinition(
                id=t["name"], name=t["name"], description=t["description"],
                input_schema=t["input_schema"], capabilities=t["capabilities"],
                risk_level=t["risk_level"].lower(), executor_id="sandbox",
                metadata={"category": "sandbox"},
            ))
    return executor


def _service_factory(db):
    from openagent.sandbox.service import SandboxManager
    return SandboxManager(db)
