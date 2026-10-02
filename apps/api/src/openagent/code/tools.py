"""Canonical code tool definitions + Tool Runtime registration.

Every code capability flows through Tool Registry -> Policy ->
Authorization -> Risk -> Credential Resolution -> Code Engine.
"""

from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

import structlog

from openagent.code.security import classify_tool_risk

logger = structlog.get_logger("code.tools")

CODE_TOOLS: list[dict[str, Any]] = [
    {"name": "code.repository.list", "description": "List connected repositories",
     "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "code.repository.status", "description": "Repository + workspace git status",
     "input_schema": {"type": "object", "properties": {
         "workspaceId": {"type": "string"}}, "required": ["workspaceId"]}},
    {"name": "code.file.list", "description": "List files in a workspace",
     "input_schema": {"type": "object", "properties": {
         "workspaceId": {"type": "string"}, "prefix": {"type": "string"}},
         "required": ["workspaceId"]}},
    {"name": "code.file.read", "description": "Read a workspace file (jailed, labeled untrusted)",
     "input_schema": {"type": "object", "properties": {
         "workspaceId": {"type": "string"}, "path": {"type": "string"},
         "start": {"type": "number"}, "end": {"type": "number"}},
         "required": ["workspaceId", "path"]}},
    {"name": "code.search", "description": "Text/regex search across a workspace",
     "input_schema": {"type": "object", "properties": {
         "workspaceId": {"type": "string"}, "query": {"type": "string"},
         "regex": {"type": "boolean"}}, "required": ["workspaceId", "query"]}},
    {"name": "code.symbol.find", "description": "Find symbol definitions",
     "input_schema": {"type": "object", "properties": {
         "workspaceId": {"type": "string"}, "name": {"type": "string"},
         "kind": {"type": "string"}}, "required": ["workspaceId", "name"]}},
    {"name": "code.reference.find", "description": "Find references/usages of a symbol",
     "input_schema": {"type": "object", "properties": {
         "workspaceId": {"type": "string"}, "symbol": {"type": "string"}},
         "required": ["workspaceId", "symbol"]}},
    {"name": "code.diff", "description": "Working-tree / staged / commit diff",
     "input_schema": {"type": "object", "properties": {
         "workspaceId": {"type": "string"}, "kind": {"type": "string"},
         "ref": {"type": "string"}, "path": {"type": "string"}},
         "required": ["workspaceId"]}},
    {"name": "code.patch.apply", "description": "Validate + apply a unified diff (approval-gated for sensitive content)",
     "input_schema": {"type": "object", "properties": {
         "taskId": {"type": "string"}, "diff": {"type": "string"},
         "approved": {"type": "boolean"},
         "approvalId": {"type": "string"},
         "approval_id": {"type": "string"}}, "required": ["taskId", "diff"]}},
    {"name": "code.branch.create", "description": "Create and checkout a branch",
     "input_schema": {"type": "object", "properties": {
         "workspaceId": {"type": "string"}, "name": {"type": "string"}},
         "required": ["workspaceId", "name"]}},
    {"name": "code.git.fetch", "description": "Fetch from origin",
     "input_schema": {"type": "object", "properties": {
         "workspaceId": {"type": "string"}}, "required": ["workspaceId"]}},
    {"name": "code.git.commit", "description": "Secret-scanned, reviewed commit on task branch",
     "input_schema": {"type": "object", "properties": {
         "taskId": {"type": "string"}, "message": {"type": "string"}},
         "required": ["taskId", "message"]}},
    {"name": "code.git.push", "description": "Approval-gated push (protected branches blocked)",
     "input_schema": {"type": "object", "properties": {
         "taskId": {"type": "string"}, "approved": {"type": "boolean"},
         "approvalId": {"type": "string"},
         "approval_id": {"type": "string"},
         "force": {"type": "boolean"}}, "required": ["taskId"]}},
    {"name": "code.test.run", "description": "Run tests through the TEST execution profile",
     "input_schema": {"type": "object", "properties": {
         "taskId": {"type": "string"}, "workspaceId": {"type": "string"},
         "command": {"type": "string"}}, "required": ["command"]}},
    {"name": "code.lint.run", "description": "Run linters through the LINT profile",
     "input_schema": {"type": "object", "properties": {
         "taskId": {"type": "string"}, "workspaceId": {"type": "string"},
         "command": {"type": "string"}}, "required": ["command"]}},
    {"name": "code.typecheck.run", "description": "Run type checkers through the TYPECHECK profile",
     "input_schema": {"type": "object", "properties": {
         "taskId": {"type": "string"}, "workspaceId": {"type": "string"},
         "command": {"type": "string"}}, "required": ["command"]}},
    {"name": "code.build.run", "description": "Run builds through the BUILD profile",
     "input_schema": {"type": "object", "properties": {
         "taskId": {"type": "string"}, "workspaceId": {"type": "string"},
         "command": {"type": "string"}}, "required": ["command"]}},
    {"name": "code.review", "description": "Static structured review of task diff",
     "input_schema": {"type": "object", "properties": {
         "taskId": {"type": "string"}}, "required": ["taskId"]}},
    {"name": "code.pr.prepare", "description": "Prepare (and optionally open) a PR draft; never merges",
     "input_schema": {"type": "object", "properties": {
         "taskId": {"type": "string"}, "title": {"type": "string"},
         "summary": {"type": "string"}, "open": {"type": "boolean"}},
         "required": ["taskId", "title"]}},
]

for _t in CODE_TOOLS:
    _t["risk_level"] = classify_tool_risk(_t["name"])
    _t["capabilities"] = ["code_execution", "read"]


class CodeToolExecutor:
    """ToolRuntime executor: validates, resolves workspace/task context, delegates."""

    executor_id = "code"

    def __init__(self, service_factory):
        self._factory = service_factory

    @property
    def supported_tools(self) -> list[str]:
        return [t["name"] for t in CODE_TOOLS]

    def get_tool_schema(self, tool_name: str) -> Optional[dict[str, Any]]:
        for t in CODE_TOOLS:
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
        return CODE_TOOLS

    async def execute(self, tool_name: str, arguments: dict[str, Any],
                      context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        from openagent.code.service import CodeNotFound, CodePolicyDenied, CodeSecurityError
        ctx = context or {}
        db = ctx.get("db")
        if db is None:
            return {"error": "code tool requires database context (db)", "requiresContext": True}
        service = self._factory(db)
        org_id = ctx.get("organization_id")
        if not org_id:
            return {"error": "organization_id context required", "requiresContext": True}
        org = UUID(str(org_id))
        ws = UUID(str(arguments["workspaceId"])) if arguments.get("workspaceId") else None
        task = UUID(str(arguments["taskId"])) if arguments.get("taskId") \
            else (UUID(str(ctx["task_id"])) if ctx.get("task_id") else None)
        try:
            if tool_name == "code.repository.list":
                repos = await service.list_repositories(org)
                return {"repositories": [
                    {"id": str(r.id), "name": r.name, "full_name": r.full_name,
                     "provider": str(r.provider), "status": str(r.status)} for r in repos]}
            if tool_name == "code.repository.status":
                return await service.workspace_status(ws, org)  # type: ignore[arg-type]
            if tool_name == "code.file.list":
                return {"files": await service.list_files(
                    ws, org, arguments.get("prefix", ""))}  # type: ignore[arg-type]
            if tool_name == "code.file.read":
                if arguments.get("start") and arguments.get("end"):
                    return await service.read_range(
                        ws, org, arguments["path"],  # type: ignore[arg-type]
                        int(arguments["start"]), int(arguments["end"]))
                return await service.read_file(ws, org, arguments["path"])  # type: ignore[arg-type]
            if tool_name == "code.search":
                if arguments.get("regex"):
                    return await service.search_regex(
                        ws, org, arguments["query"])  # type: ignore[arg-type]
                return await service.search_text(ws, org, arguments["query"])  # type: ignore[arg-type]
            if tool_name == "code.symbol.find":
                return await service.find_symbol(
                    ws, org, arguments["name"],  # type: ignore[arg-type]
                    arguments.get("kind"))
            if tool_name == "code.reference.find":
                return await service.find_references(
                    ws, org, arguments["symbol"])  # type: ignore[arg-type]
            if tool_name == "code.diff":
                return await service.get_diff(
                    ws, org, arguments.get("kind", "working"),  # type: ignore[arg-type]
                    arguments.get("ref"), arguments.get("path"))
            if tool_name == "code.patch.apply":
                _approval_raw = arguments.get("approvalId", arguments.get("approval_id"))
                return await service.apply_patch(
                    task, org, diff_text=arguments["diff"],  # type: ignore[arg-type]
                    approved=bool(arguments.get("approved")),
                    approval_id=UUID(str(_approval_raw)) if _approval_raw else None)
            if tool_name == "code.branch.create":
                return await service.create_branch(ws, org, arguments["name"])  # type: ignore[arg-type]
            if tool_name == "code.git.fetch":
                w = await service.get_workspace(ws, org)  # type: ignore[arg-type]
                repo = await service.get_repository(w.repository_id, org)
                auth = await service._auth_for(repo)
                await service._provider_for(repo).fetch(
                    str(service._workspace_path(w)), auth)
                return {"success": True}
            if tool_name == "code.git.commit":
                return await service.commit(task, org, arguments["message"])  # type: ignore[arg-type]
            if tool_name == "code.git.push":
                _push_approval = arguments.get("approvalId", arguments.get("approval_id"))
                return await service.push(
                    task, org, approved=bool(arguments.get("approved")),  # type: ignore[arg-type]
                    approval_id=UUID(str(_push_approval)) if _push_approval else None,
                    force=bool(arguments.get("force")))
            if tool_name in ("code.test.run", "code.lint.run",
                             "code.typecheck.run", "code.build.run"):
                profile = {"code.test.run": "TEST", "code.lint.run": "LINT",
                           "code.typecheck.run": "TYPECHECK",
                           "code.build.run": "BUILD"}[tool_name]
                if tool_name == "code.test.run":
                    return await service.run_tests(task, org, ws, arguments["command"])
                return await service.run_command(task, org, ws, profile,
                                                 arguments["command"])
            if tool_name == "code.review":
                return await service.review_task(task, org)  # type: ignore[arg-type]
            if tool_name == "code.pr.prepare":
                return await service.prepare_pr(
                    task, org, arguments["title"],  # type: ignore[arg-type]
                    arguments.get("summary", ""),
                    open_remote=bool(arguments.get("open")))
            return {"error": f"Unknown code tool: {tool_name}"}
        except CodePolicyDenied as e:
            return {"error": str(e), "policyDenied": True}
        except CodeSecurityError as e:
            return {"error": str(e)}
        except CodeNotFound as e:
            return {"error": str(e), "notFound": True}


def ensure_code_tools_registered(db_session_factory=None) -> "CodeToolExecutor":
    """Register code tools + executor with Tool Runtime (idempotent)."""
    from openagent.runtime.tools import tool_executor_registry, tool_registry
    from openagent.runtime.tools import ToolDefinition as RuntimeToolDefinition

    executor = CodeToolExecutor(service_factory=_service_factory)
    if tool_executor_registry.get_executor("code") is None:
        tool_executor_registry.register(executor)
    for t in CODE_TOOLS:
        if tool_registry.get_latest(t["name"]) is None:
            tool_registry.register(RuntimeToolDefinition(
                id=t["name"], name=t["name"], description=t["description"],
                input_schema=t["input_schema"], capabilities=t["capabilities"],
                risk_level=t["risk_level"].lower(), executor_id="code",
                metadata={"category": "code"},
            ))
    return executor


def _service_factory(db):
    from openagent.code.service import CodeService
    return CodeService(db)
