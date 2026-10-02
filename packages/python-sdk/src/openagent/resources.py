"""Resource classes for every API domain.

Each domain defines a shared mixin (path builders + payload helpers) that
is inherited by both the synchronous resource (``httpx.Client`` based) and
the asynchronous resource (``httpx.AsyncClient`` based), so URL shapes and
payload shapes are defined exactly once.
"""

from __future__ import annotations

from typing import Any, AsyncIterator, Dict, Iterator, List, Optional

from ._http import AsyncTransport, SyncTransport
from .errors import ValidationError
from .types_ import PaginatedResult
from .webhooks import verify_webhook

__all__ = [
    "Agents", "AsyncAgents",
    "AgentRuns", "AsyncAgentRuns",
    "Workflows", "AsyncWorkflows",
    "Executions", "AsyncExecutions",
    "Tools", "AsyncTools",
    "Connectors", "AsyncConnectors",
    "MCP", "AsyncMCP",
    "Memory", "AsyncMemory",
    "Models", "AsyncModels",
    "Evaluations", "AsyncEvaluations",
    "Sandboxes", "AsyncSandboxes",
    "Approvals", "AsyncApprovals",
    "Marketplace", "AsyncMarketplace",
    "Registries", "AsyncRegistries",
    "Billing", "AsyncBilling",
    "Projects", "AsyncProjects",
    "Extensions", "AsyncExtensions",
    "Deployments", "AsyncDeployments",
    "Events", "AsyncEvents",
    "Webhooks", "AsyncWebhooks",
]


def _clean(**kwargs: Any) -> Dict[str, Any]:
    return {k: v for k, v in kwargs.items() if v is not None}


class _SyncBase:
    _transport: SyncTransport

    def __init__(self, transport: SyncTransport) -> None:
        self._transport = transport

    def _org(self, suffix: str = "") -> str:
        org = self._transport.organization_id
        if not org:
            raise ValidationError("organization_id is required for this resource")
        return f"/organizations/{org}{suffix}"

    def _list(
        self,
        path: str,
        *,
        limit: Optional[int] = None,
        cursor: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> PaginatedResult:
        merged = _clean(limit=limit, cursor=cursor)
        if params:
            merged.update(params)
        return self._transport.request_paginated("GET", path, params=merged or None, **kwargs)

    def _iterate(
        self,
        path: str,
        *,
        limit: Optional[int] = None,
        params: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Iterator[Any]:
        merged = _clean(limit=limit)
        if params:
            merged.update(params)
        return self._transport.iter_paginated("GET", path, params=merged or None, **kwargs)


class _AsyncBase:
    _transport: AsyncTransport

    def __init__(self, transport: AsyncTransport) -> None:
        self._transport = transport

    def _org(self, suffix: str = "") -> str:
        org = self._transport.organization_id
        if not org:
            raise ValidationError("organization_id is required for this resource")
        return f"/organizations/{org}{suffix}"

    async def _list(
        self,
        path: str,
        *,
        limit: Optional[int] = None,
        cursor: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> PaginatedResult:
        merged = _clean(limit=limit, cursor=cursor)
        if params:
            merged.update(params)
        return await self._transport.request_paginated(
            "GET", path, params=merged or None, **kwargs
        )

    def _iterate(
        self,
        path: str,
        *,
        limit: Optional[int] = None,
        params: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> AsyncIterator[Any]:
        merged = _clean(limit=limit)
        if params:
            merged.update(params)
        return self._transport.iter_paginated("GET", path, params=merged or None, **kwargs)


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------

class _AgentsMixin:
    def _base(self) -> str:
        return self._org("/agents")  # type: ignore[no-untyped-def]

    def _item(self, agent_id: str) -> str:
        return f"{self._base()}/{agent_id}"  # type: ignore[no-untyped-def]


class Agents(_SyncBase, _AgentsMixin):
    def list(self, *, limit=None, cursor=None, params=None, **kw) -> PaginatedResult:
        return self._list(self._base(), limit=limit, cursor=cursor, params=params, **kw)

    def iterate(self, *, limit=None, params=None, **kw) -> Iterator[Any]:
        return self._iterate(self._base(), limit=limit, params=params, **kw)

    def get(self, agent_id: str, **kw) -> Dict[str, Any]:
        return self._transport.request("GET", self._item(agent_id), **kw)

    def create(self, name: str, *, description=None, model=None, instructions=None,
               tools=None, metadata=None, idempotency_key=None, **kw) -> Dict[str, Any]:
        return self._transport.request(
            "POST", self._base(),
            json_body=_clean(name=name, description=description, model=model,
                             instructions=instructions, tools=tools, metadata=metadata),
            idempotency_key=idempotency_key, **kw)

    def update(self, agent_id: str, *, idempotency_key=None, **fields) -> Dict[str, Any]:
        return self._transport.request("PATCH", self._item(agent_id),
                                       json_body=_clean(**fields),
                                       idempotency_key=idempotency_key)

    def delete(self, agent_id: str, **kw) -> Dict[str, Any]:
        return self._transport.request("DELETE", self._item(agent_id), **kw)

    def run(self, agent_id: str, input: Any, *, stream=False, idempotency_key=None, **kw) -> Dict[str, Any]:
        return self._transport.request(
            "POST", f"{self._item(agent_id)}/runs",
            json_body=_clean(input=input, stream=stream, **kw.pop("payload", {})),
            idempotency_key=idempotency_key, **kw)

    def list_runs(self, agent_id: str, *, limit=None, cursor=None, **kw) -> PaginatedResult:
        return self._list(f"{self._item(agent_id)}/runs", limit=limit, cursor=cursor, **kw)


class AsyncAgents(_AsyncBase, _AgentsMixin):
    async def list(self, *, limit=None, cursor=None, params=None, **kw) -> PaginatedResult:
        return await self._list(self._base(), limit=limit, cursor=cursor, params=params, **kw)

    def iterate(self, *, limit=None, params=None, **kw) -> AsyncIterator[Any]:
        return self._iterate(self._base(), limit=limit, params=params, **kw)

    async def get(self, agent_id: str, **kw) -> Dict[str, Any]:
        return await self._transport.request("GET", self._item(agent_id), **kw)

    async def create(self, name: str, *, description=None, model=None, instructions=None,
                     tools=None, metadata=None, idempotency_key=None, **kw) -> Dict[str, Any]:
        return await self._transport.request(
            "POST", self._base(),
            json_body=_clean(name=name, description=description, model=model,
                             instructions=instructions, tools=tools, metadata=metadata),
            idempotency_key=idempotency_key, **kw)

    async def update(self, agent_id: str, *, idempotency_key=None, **fields) -> Dict[str, Any]:
        return await self._transport.request("PATCH", self._item(agent_id),
                                             json_body=_clean(**fields),
                                             idempotency_key=idempotency_key)

    async def delete(self, agent_id: str, **kw) -> Dict[str, Any]:
        return await self._transport.request("DELETE", self._item(agent_id), **kw)

    async def run(self, agent_id: str, input: Any, *, stream=False, idempotency_key=None, **kw) -> Dict[str, Any]:
        return await self._transport.request(
            "POST", f"{self._item(agent_id)}/runs",
            json_body=_clean(input=input, stream=stream, **kw.pop("payload", {})),
            idempotency_key=idempotency_key, **kw)

    async def list_runs(self, agent_id: str, *, limit=None, cursor=None, **kw) -> PaginatedResult:
        return await self._list(f"{self._item(agent_id)}/runs", limit=limit, cursor=cursor, **kw)


# ---------------------------------------------------------------------------
# AgentRuns
# ---------------------------------------------------------------------------

class _AgentRunsMixin:
    def _runs_base(self, agent_id: str) -> str:
        return self._org(f"/agents/{agent_id}/runs")  # type: ignore[no-untyped-def]

    def _run_path(self, run_id: str) -> str:
        return self._org(f"/runs/{run_id}")  # type: ignore[no-untyped-def]


class AgentRuns(_SyncBase, _AgentRunsMixin):
    def list(self, agent_id: str, *, limit=None, cursor=None, **kw) -> PaginatedResult:
        return self._list(self._runs_base(agent_id), limit=limit, cursor=cursor, **kw)

    def iterate(self, agent_id: str, *, limit=None, **kw) -> Iterator[Any]:
        return self._iterate(self._runs_base(agent_id), limit=limit, **kw)

    def get(self, run_id: str, **kw) -> Dict[str, Any]:
        return self._transport.request("GET", self._run_path(run_id), **kw)

    def create(self, agent_id: str, input: Any, *, idempotency_key=None, **kw) -> Dict[str, Any]:
        payload = kw.pop("payload", {})
        return self._transport.request(
            "POST", self._runs_base(agent_id), json_body=_clean(input=input, **payload),
            idempotency_key=idempotency_key, **kw)

    def cancel(self, run_id: str, *, idempotency_key=None, **kw) -> Dict[str, Any]:
        return self._transport.request("POST", f"{self._run_path(run_id)}/cancel",
                                       json_body={}, idempotency_key=idempotency_key, **kw)

    def list_steps(self, run_id: str, *, limit=None, cursor=None, **kw) -> PaginatedResult:
        return self._list(f"{self._run_path(run_id)}/steps", limit=limit, cursor=cursor, **kw)

    def stream(self, run_id: str, **kw) -> Iterator[Dict[str, Any]]:
        return self._transport.stream("GET", f"{self._run_path(run_id)}/stream", **kw)


class AsyncAgentRuns(_AsyncBase, _AgentRunsMixin):
    async def list(self, agent_id: str, *, limit=None, cursor=None, **kw) -> PaginatedResult:
        return await self._list(self._runs_base(agent_id), limit=limit, cursor=cursor, **kw)

    def iterate(self, agent_id: str, *, limit=None, **kw) -> AsyncIterator[Any]:
        return self._iterate(self._runs_base(agent_id), limit=limit, **kw)

    async def get(self, run_id: str, **kw) -> Dict[str, Any]:
        return await self._transport.request("GET", self._run_path(run_id), **kw)

    async def create(self, agent_id: str, input: Any, *, idempotency_key=None, **kw) -> Dict[str, Any]:
        payload = kw.pop("payload", {})
        return await self._transport.request(
            "POST", self._runs_base(agent_id), json_body=_clean(input=input, **payload),
            idempotency_key=idempotency_key, **kw)

    async def cancel(self, run_id: str, *, idempotency_key=None, **kw) -> Dict[str, Any]:
        return await self._transport.request("POST", f"{self._run_path(run_id)}/cancel",
                                             json_body={}, idempotency_key=idempotency_key, **kw)

    async def list_steps(self, run_id: str, *, limit=None, cursor=None, **kw) -> PaginatedResult:
        return await self._list(f"{self._run_path(run_id)}/steps", limit=limit, cursor=cursor, **kw)

    def stream(self, run_id: str, **kw) -> AsyncIterator[Dict[str, Any]]:
        return self._transport.stream("GET", f"{self._run_path(run_id)}/stream", **kw)


# ---------------------------------------------------------------------------
# Workflows
# ---------------------------------------------------------------------------

class _WorkflowsMixin:
    def _base(self) -> str:
        return self._org("/workflows")  # type: ignore[no-untyped-def]

    def _item(self, workflow_id: str) -> str:
        return f"{self._base()}/{workflow_id}"  # type: ignore[no-untyped-def]

    def _execution(self, execution_id: str) -> str:
        return f"{self._base()}/executions/{execution_id}"  # type: ignore[no-untyped-def]


class Workflows(_SyncBase, _WorkflowsMixin):
    def list(self, *, limit=None, cursor=None, params=None, **kw) -> PaginatedResult:
        return self._list(self._base(), limit=limit, cursor=cursor, params=params, **kw)

    def iterate(self, *, limit=None, params=None, **kw) -> Iterator[Any]:
        return self._iterate(self._base(), limit=limit, params=params, **kw)

    def get(self, workflow_id: str, **kw) -> Dict[str, Any]:
        return self._transport.request("GET", self._item(workflow_id), **kw)

    def create(self, name: str, *, definition=None, description=None, idempotency_key=None, **kw) -> Dict[str, Any]:
        payload = kw.pop("payload", {})
        return self._transport.request(
            "POST", self._base(),
            json_body=_clean(name=name, definition=definition, description=description, **payload),
            idempotency_key=idempotency_key, **kw)

    def update(self, workflow_id: str, *, idempotency_key=None, **fields) -> Dict[str, Any]:
        return self._transport.request("PATCH", self._item(workflow_id),
                                       json_body=_clean(**fields),
                                       idempotency_key=idempotency_key)

    def delete(self, workflow_id: str, **kw) -> Dict[str, Any]:
        return self._transport.request("DELETE", self._item(workflow_id), **kw)

    def execute(self, workflow_id: str, input: Any = None, *, idempotency_key=None, **kw) -> Dict[str, Any]:
        payload = kw.pop("payload", {})
        return self._transport.request(
            "POST", f"{self._item(workflow_id)}/executions",
            json_body=_clean(input=input, **payload),
            idempotency_key=idempotency_key, **kw)

    def list_executions(self, workflow_id: str, *, limit=None, cursor=None, **kw) -> PaginatedResult:
        return self._list(f"{self._item(workflow_id)}/executions", limit=limit, cursor=cursor, **kw)

    def get_execution(self, execution_id: str, **kw) -> Dict[str, Any]:
        return self._transport.request("GET", self._execution(execution_id), **kw)

    def cancel_execution(self, execution_id: str, *, idempotency_key=None, **kw) -> Dict[str, Any]:
        return self._transport.request("POST", f"{self._execution(execution_id)}/cancel",
                                       json_body={}, idempotency_key=idempotency_key, **kw)

    def stream_execution(self, execution_id: str, **kw) -> Iterator[Dict[str, Any]]:
        return self._transport.stream("GET", f"{self._execution(execution_id)}/stream", **kw)


class AsyncWorkflows(_AsyncBase, _WorkflowsMixin):
    async def list(self, *, limit=None, cursor=None, params=None, **kw) -> PaginatedResult:
        return await self._list(self._base(), limit=limit, cursor=cursor, params=params, **kw)

    def iterate(self, *, limit=None, params=None, **kw) -> AsyncIterator[Any]:
        return self._iterate(self._base(), limit=limit, params=params, **kw)

    async def get(self, workflow_id: str, **kw) -> Dict[str, Any]:
        return await self._transport.request("GET", self._item(workflow_id), **kw)

    async def create(self, name: str, *, definition=None, description=None, idempotency_key=None, **kw) -> Dict[str, Any]:
        payload = kw.pop("payload", {})
        return await self._transport.request(
            "POST", self._base(),
            json_body=_clean(name=name, definition=definition, description=description, **payload),
            idempotency_key=idempotency_key, **kw)

    async def update(self, workflow_id: str, *, idempotency_key=None, **fields) -> Dict[str, Any]:
        return await self._transport.request("PATCH", self._item(workflow_id),
                                             json_body=_clean(**fields),
                                             idempotency_key=idempotency_key)

    async def delete(self, workflow_id: str, **kw) -> Dict[str, Any]:
        return await self._transport.request("DELETE", self._item(workflow_id), **kw)

    async def execute(self, workflow_id: str, input: Any = None, *, idempotency_key=None, **kw) -> Dict[str, Any]:
        payload = kw.pop("payload", {})
        return await self._transport.request(
            "POST", f"{self._item(workflow_id)}/executions",
            json_body=_clean(input=input, **payload),
            idempotency_key=idempotency_key, **kw)

    async def list_executions(self, workflow_id: str, *, limit=None, cursor=None, **kw) -> PaginatedResult:
        return await self._list(f"{self._item(workflow_id)}/executions", limit=limit, cursor=cursor, **kw)

    async def get_execution(self, execution_id: str, **kw) -> Dict[str, Any]:
        return await self._transport.request("GET", self._execution(execution_id), **kw)

    async def cancel_execution(self, execution_id: str, *, idempotency_key=None, **kw) -> Dict[str, Any]:
        return await self._transport.request("POST", f"{self._execution(execution_id)}/cancel",
                                             json_body={}, idempotency_key=idempotency_key, **kw)

    def stream_execution(self, execution_id: str, **kw) -> AsyncIterator[Dict[str, Any]]:
        return self._transport.stream("GET", f"{self._execution(execution_id)}/stream", **kw)


# ---------------------------------------------------------------------------
# Executions (cloud)
# ---------------------------------------------------------------------------

class _ExecutionsMixin:
    def _base(self) -> str:
        return "/cloud/executions"

    def _item(self, execution_id: str) -> str:
        return f"/cloud/executions/{execution_id}"


class Executions(_SyncBase, _ExecutionsMixin):
    def list(self, *, limit=None, cursor=None, params=None, **kw) -> PaginatedResult:
        return self._list(self._base(), limit=limit, cursor=cursor, params=params, **kw)

    def iterate(self, *, limit=None, params=None, **kw) -> Iterator[Any]:
        return self._iterate(self._base(), limit=limit, params=params, **kw)

    def get(self, execution_id: str, **kw) -> Dict[str, Any]:
        return self._transport.request("GET", self._item(execution_id), **kw)

    def create(self, *, payload=None, idempotency_key=None, **kw) -> Dict[str, Any]:
        return self._transport.request("POST", self._base(), json_body=dict(payload or {}),
                                       idempotency_key=idempotency_key, **kw)

    def cancel(self, execution_id: str, *, idempotency_key=None, **kw) -> Dict[str, Any]:
        return self._transport.request("POST", f"{self._item(execution_id)}/cancel",
                                       json_body={}, idempotency_key=idempotency_key, **kw)

    def logs(self, execution_id: str, *, limit=None, cursor=None, **kw) -> PaginatedResult:
        return self._list(f"{self._item(execution_id)}/logs", limit=limit, cursor=cursor, **kw)

    def stream_logs(self, execution_id: str, **kw) -> Iterator[Dict[str, Any]]:
        return self._transport.stream("GET", f"{self._item(execution_id)}/logs/stream", **kw)


class AsyncExecutions(_AsyncBase, _ExecutionsMixin):
    async def list(self, *, limit=None, cursor=None, params=None, **kw) -> PaginatedResult:
        return await self._list(self._base(), limit=limit, cursor=cursor, params=params, **kw)

    def iterate(self, *, limit=None, params=None, **kw) -> AsyncIterator[Any]:
        return self._iterate(self._base(), limit=limit, params=params, **kw)

    async def get(self, execution_id: str, **kw) -> Dict[str, Any]:
        return await self._transport.request("GET", self._item(execution_id), **kw)

    async def create(self, *, payload=None, idempotency_key=None, **kw) -> Dict[str, Any]:
        return await self._transport.request("POST", self._base(), json_body=dict(payload or {}),
                                             idempotency_key=idempotency_key, **kw)

    async def cancel(self, execution_id: str, *, idempotency_key=None, **kw) -> Dict[str, Any]:
        return await self._transport.request("POST", f"{self._item(execution_id)}/cancel",
                                             json_body={}, idempotency_key=idempotency_key, **kw)

    async def logs(self, execution_id: str, *, limit=None, cursor=None, **kw) -> PaginatedResult:
        return await self._list(f"{self._item(execution_id)}/logs", limit=limit, cursor=cursor, **kw)

    def stream_logs(self, execution_id: str, **kw) -> AsyncIterator[Dict[str, Any]]:
        return self._transport.stream("GET", f"{self._item(execution_id)}/logs/stream", **kw)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

class _ToolsMixin:
    def _base(self) -> str:
        return self._org("/tools")  # type: ignore[no-untyped-def]

    def _item(self, tool_id: str) -> str:
        return f"{self._base()}/{tool_id}"  # type: ignore[no-untyped-def]


class Tools(_SyncBase, _ToolsMixin):
    def list(self, *, limit=None, cursor=None, params=None, **kw) -> PaginatedResult:
        return self._list(self._base(), limit=limit, cursor=cursor, params=params, **kw)

    def iterate(self, *, limit=None, params=None, **kw) -> Iterator[Any]:
        return self._iterate(self._base(), limit=limit, params=params, **kw)

    def get(self, tool_id: str, **kw) -> Dict[str, Any]:
        return self._transport.request("GET", self._item(tool_id), **kw)

    def create(self, name: str, *, description=None, schema=None, idempotency_key=None, **kw) -> Dict[str, Any]:
        payload = kw.pop("payload", {})
        return self._transport.request(
            "POST", self._base(),
            json_body=_clean(name=name, description=description, schema=schema, **payload),
            idempotency_key=idempotency_key, **kw)

    def update(self, tool_id: str, *, idempotency_key=None, **fields) -> Dict[str, Any]:
        return self._transport.request("PATCH", self._item(tool_id),
                                       json_body=_clean(**fields),
                                       idempotency_key=idempotency_key)

    def delete(self, tool_id: str, **kw) -> Dict[str, Any]:
        return self._transport.request("DELETE", self._item(tool_id), **kw)

    def execute(self, tool_id: str, arguments: Optional[Dict[str, Any]] = None, *,
                idempotency_key=None, **kw) -> Dict[str, Any]:
        return self._transport.request(
            "POST", f"{self._item(tool_id)}/execute",
            json_body={"arguments": arguments or {}}, idempotency_key=idempotency_key, **kw)

    def list_versions(self, tool_id: str, *, limit=None, cursor=None, **kw) -> PaginatedResult:
        return self._list(f"{self._item(tool_id)}/versions", limit=limit, cursor=cursor, **kw)


class AsyncTools(_AsyncBase, _ToolsMixin):
    async def list(self, *, limit=None, cursor=None, params=None, **kw) -> PaginatedResult:
        return await self._list(self._base(), limit=limit, cursor=cursor, params=params, **kw)

    def iterate(self, *, limit=None, params=None, **kw) -> AsyncIterator[Any]:
        return self._iterate(self._base(), limit=limit, params=params, **kw)

    async def get(self, tool_id: str, **kw) -> Dict[str, Any]:
        return await self._transport.request("GET", self._item(tool_id), **kw)

    async def create(self, name: str, *, description=None, schema=None, idempotency_key=None, **kw) -> Dict[str, Any]:
        payload = kw.pop("payload", {})
        return await self._transport.request(
            "POST", self._base(),
            json_body=_clean(name=name, description=description, schema=schema, **payload),
            idempotency_key=idempotency_key, **kw)

    async def update(self, tool_id: str, *, idempotency_key=None, **fields) -> Dict[str, Any]:
        return await self._transport.request("PATCH", self._item(tool_id),
                                             json_body=_clean(**fields),
                                             idempotency_key=idempotency_key)

    async def delete(self, tool_id: str, **kw) -> Dict[str, Any]:
        return await self._transport.request("DELETE", self._item(tool_id), **kw)

    async def execute(self, tool_id: str, arguments: Optional[Dict[str, Any]] = None, *,
                      idempotency_key=None, **kw) -> Dict[str, Any]:
        return await self._transport.request(
            "POST", f"{self._item(tool_id)}/execute",
            json_body={"arguments": arguments or {}}, idempotency_key=idempotency_key, **kw)

    async def list_versions(self, tool_id: str, *, limit=None, cursor=None, **kw) -> PaginatedResult:
        return await self._list(f"{self._item(tool_id)}/versions", limit=limit, cursor=cursor, **kw)


# ---------------------------------------------------------------------------
# Connectors (+ connections / credentials / webhooks)
# ---------------------------------------------------------------------------

class _ConnectorsMixin:
    def _base(self) -> str:
        return self._org("/connectors")  # type: ignore[no-untyped-def]

    def _item(self, connector_id: str) -> str:
        return f"{self._base()}/{connector_id}"  # type: ignore[no-untyped-def]


class Connectors(_SyncBase, _ConnectorsMixin):
    def list(self, *, limit=None, cursor=None, params=None, **kw) -> PaginatedResult:
        return self._list(self._base(), limit=limit, cursor=cursor, params=params, **kw)

    def iterate(self, *, limit=None, params=None, **kw) -> Iterator[Any]:
        return self._iterate(self._base(), limit=limit, params=params, **kw)

    def get(self, connector_id: str, **kw) -> Dict[str, Any]:
        return self._transport.request("GET", self._item(connector_id), **kw)

    def create(self, name: str, *, connector_type=None, config=None, idempotency_key=None, **kw) -> Dict[str, Any]:
        payload = kw.pop("payload", {})
        return self._transport.request(
            "POST", self._base(),
            json_body=_clean(name=name, type=connector_type, config=config, **payload),
            idempotency_key=idempotency_key, **kw)

    def update(self, connector_id: str, *, idempotency_key=None, **fields) -> Dict[str, Any]:
        return self._transport.request("PATCH", self._item(connector_id),
                                       json_body=_clean(**fields),
                                       idempotency_key=idempotency_key)

    def delete(self, connector_id: str, **kw) -> Dict[str, Any]:
        return self._transport.request("DELETE", self._item(connector_id), **kw)

    def test(self, connector_id: str, *, idempotency_key=None, **kw) -> Dict[str, Any]:
        return self._transport.request("POST", f"{self._item(connector_id)}/test",
                                       json_body={}, idempotency_key=idempotency_key, **kw)

    def list_connections(self, connector_id: str, *, limit=None, cursor=None, **kw) -> PaginatedResult:
        return self._list(f"{self._item(connector_id)}/connections", limit=limit, cursor=cursor, **kw)

    def create_connection(self, connector_id: str, *, idempotency_key=None, **fields) -> Dict[str, Any]:
        return self._transport.request("POST", f"{self._item(connector_id)}/connections",
                                       json_body=_clean(**fields),
                                       idempotency_key=idempotency_key)

    def get_connection(self, connection_id: str, **kw) -> Dict[str, Any]:
        return self._transport.request("GET", f"{self._base()}/connections/{connection_id}", **kw)

    def delete_connection(self, connection_id: str, **kw) -> Dict[str, Any]:
        return self._transport.request("DELETE", f"{self._base()}/connections/{connection_id}", **kw)

    def list_credentials(self, connector_id: str, *, limit=None, cursor=None, **kw) -> PaginatedResult:
        return self._list(f"{self._item(connector_id)}/credentials", limit=limit, cursor=cursor, **kw)

    def create_credential(self, connector_id: str, *, idempotency_key=None, **fields) -> Dict[str, Any]:
        return self._transport.request("POST", f"{self._item(connector_id)}/credentials",
                                       json_body=_clean(**fields),
                                       idempotency_key=idempotency_key)

    def delete_credential(self, credential_id: str, **kw) -> Dict[str, Any]:
        return self._transport.request("DELETE", f"{self._base()}/credentials/{credential_id}", **kw)

    def rotate_credential(self, credential_id: str, *, idempotency_key=None, **kw) -> Dict[str, Any]:
        return self._transport.request("POST", f"{self._base()}/credentials/{credential_id}/rotate",
                                       json_body={}, idempotency_key=idempotency_key, **kw)

    def list_webhooks(self, *, limit=None, cursor=None, **kw) -> PaginatedResult:
        return self._list(f"{self._base()}/webhooks", limit=limit, cursor=cursor, **kw)

    def register_webhook(self, url: str, *, events=None, idempotency_key=None, **kw) -> Dict[str, Any]:
        payload = kw.pop("payload", {})
        return self._transport.request(
            "POST", f"{self._base()}/webhooks",
            json_body=_clean(url=url, events=events, **payload),
            idempotency_key=idempotency_key, **kw)

    def delete_webhook(self, webhook_id: str, **kw) -> Dict[str, Any]:
        return self._transport.request("DELETE", f"{self._base()}/webhooks/{webhook_id}", **kw)


class AsyncConnectors(_AsyncBase, _ConnectorsMixin):
    async def list(self, *, limit=None, cursor=None, params=None, **kw) -> PaginatedResult:
        return await self._list(self._base(), limit=limit, cursor=cursor, params=params, **kw)

    def iterate(self, *, limit=None, params=None, **kw) -> AsyncIterator[Any]:
        return self._iterate(self._base(), limit=limit, params=params, **kw)

    async def get(self, connector_id: str, **kw) -> Dict[str, Any]:
        return await self._transport.request("GET", self._item(connector_id), **kw)

    async def create(self, name: str, *, connector_type=None, config=None, idempotency_key=None, **kw) -> Dict[str, Any]:
        payload = kw.pop("payload", {})
        return await self._transport.request(
            "POST", self._base(),
            json_body=_clean(name=name, type=connector_type, config=config, **payload),
            idempotency_key=idempotency_key, **kw)

    async def update(self, connector_id: str, *, idempotency_key=None, **fields) -> Dict[str, Any]:
        return await self._transport.request("PATCH", self._item(connector_id),
                                             json_body=_clean(**fields),
                                             idempotency_key=idempotency_key)

    async def delete(self, connector_id: str, **kw) -> Dict[str, Any]:
        return await self._transport.request("DELETE", self._item(connector_id), **kw)

    async def test(self, connector_id: str, *, idempotency_key=None, **kw) -> Dict[str, Any]:
        return await self._transport.request("POST", f"{self._item(connector_id)}/test",
                                             json_body={}, idempotency_key=idempotency_key, **kw)

    async def list_connections(self, connector_id: str, *, limit=None, cursor=None, **kw) -> PaginatedResult:
        return await self._list(f"{self._item(connector_id)}/connections", limit=limit, cursor=cursor, **kw)

    async def create_connection(self, connector_id: str, *, idempotency_key=None, **fields) -> Dict[str, Any]:
        return await self._transport.request("POST", f"{self._item(connector_id)}/connections",
                                             json_body=_clean(**fields),
                                             idempotency_key=idempotency_key)

    async def get_connection(self, connection_id: str, **kw) -> Dict[str, Any]:
        return await self._transport.request("GET", f"{self._base()}/connections/{connection_id}", **kw)

    async def delete_connection(self, connection_id: str, **kw) -> Dict[str, Any]:
        return await self._transport.request("DELETE", f"{self._base()}/connections/{connection_id}", **kw)

    async def list_credentials(self, connector_id: str, *, limit=None, cursor=None, **kw) -> PaginatedResult:
        return await self._list(f"{self._item(connector_id)}/credentials", limit=limit, cursor=cursor, **kw)

    async def create_credential(self, connector_id: str, *, idempotency_key=None, **fields) -> Dict[str, Any]:
        return await self._transport.request("POST", f"{self._item(connector_id)}/credentials",
                                             json_body=_clean(**fields),
                                             idempotency_key=idempotency_key)

    async def delete_credential(self, credential_id: str, **kw) -> Dict[str, Any]:
        return await self._transport.request("DELETE", f"{self._base()}/credentials/{credential_id}", **kw)

    async def rotate_credential(self, credential_id: str, *, idempotency_key=None, **kw) -> Dict[str, Any]:
        return await self._transport.request("POST", f"{self._base()}/credentials/{credential_id}/rotate",
                                             json_body={}, idempotency_key=idempotency_key, **kw)

    async def list_webhooks(self, *, limit=None, cursor=None, **kw) -> PaginatedResult:
        return await self._list(f"{self._base()}/webhooks", limit=limit, cursor=cursor, **kw)

    async def register_webhook(self, url: str, *, events=None, idempotency_key=None, **kw) -> Dict[str, Any]:
        payload = kw.pop("payload", {})
        return await self._transport.request(
            "POST", f"{self._base()}/webhooks",
            json_body=_clean(url=url, events=events, **payload),
            idempotency_key=idempotency_key, **kw)

    async def delete_webhook(self, webhook_id: str, **kw) -> Dict[str, Any]:
        return await self._transport.request("DELETE", f"{self._base()}/webhooks/{webhook_id}", **kw)


# ---------------------------------------------------------------------------
# MCP
# ---------------------------------------------------------------------------

class _MCPMixin:
    def _servers(self) -> str:
        return self._org("/mcp/servers")  # type: ignore[no-untyped-def]

    def _server(self, server_id: str) -> str:
        return f"{self._servers()}/{server_id}"  # type: ignore[no-untyped-def]


class MCP(_SyncBase, _MCPMixin):
    def list_servers(self, *, limit=None, cursor=None, params=None, **kw) -> PaginatedResult:
        return self._list(self._servers(), limit=limit, cursor=cursor, params=params, **kw)

    def iterate_servers(self, *, limit=None, params=None, **kw) -> Iterator[Any]:
        return self._iterate(self._servers(), limit=limit, params=params, **kw)

    def get_server(self, server_id: str, **kw) -> Dict[str, Any]:
        return self._transport.request("GET", self._server(server_id), **kw)

    def create_server(self, name: str, *, url=None, command=None, idempotency_key=None, **kw) -> Dict[str, Any]:
        payload = kw.pop("payload", {})
        return self._transport.request(
            "POST", self._servers(),
            json_body=_clean(name=name, url=url, command=command, **payload),
            idempotency_key=idempotency_key, **kw)

    def update_server(self, server_id: str, *, idempotency_key=None, **fields) -> Dict[str, Any]:
        return self._transport.request("PATCH", self._server(server_id),
                                       json_body=_clean(**fields),
                                       idempotency_key=idempotency_key)

    def delete_server(self, server_id: str, **kw) -> Dict[str, Any]:
        return self._transport.request("DELETE", self._server(server_id), **kw)

    def connect(self, server_id: str, *, idempotency_key=None, **kw) -> Dict[str, Any]:
        return self._transport.request("POST", f"{self._server(server_id)}/connect",
                                       json_body={}, idempotency_key=idempotency_key, **kw)

    def disconnect(self, server_id: str, *, idempotency_key=None, **kw) -> Dict[str, Any]:
        return self._transport.request("POST", f"{self._server(server_id)}/disconnect",
                                       json_body={}, idempotency_key=idempotency_key, **kw)

    def list_server_tools(self, server_id: str, *, limit=None, cursor=None, **kw) -> PaginatedResult:
        return self._list(f"{self._server(server_id)}/tools", limit=limit, cursor=cursor, **kw)

    def call_tool(self, server_id: str, tool_name: str, arguments: Optional[Dict[str, Any]] = None, *,
                  idempotency_key=None, **kw) -> Dict[str, Any]:
        return self._transport.request(
            "POST", f"{self._server(server_id)}/tools/call",
            json_body={"tool": tool_name, "arguments": arguments or {}},
            idempotency_key=idempotency_key, **kw)


class AsyncMCP(_AsyncBase, _MCPMixin):
    async def list_servers(self, *, limit=None, cursor=None, params=None, **kw) -> PaginatedResult:
        return await self._list(self._servers(), limit=limit, cursor=cursor, params=params, **kw)

    def iterate_servers(self, *, limit=None, params=None, **kw) -> AsyncIterator[Any]:
        return self._iterate(self._servers(), limit=limit, params=params, **kw)

    async def get_server(self, server_id: str, **kw) -> Dict[str, Any]:
        return await self._transport.request("GET", self._server(server_id), **kw)

    async def create_server(self, name: str, *, url=None, command=None, idempotency_key=None, **kw) -> Dict[str, Any]:
        payload = kw.pop("payload", {})
        return await self._transport.request(
            "POST", self._servers(),
            json_body=_clean(name=name, url=url, command=command, **payload),
            idempotency_key=idempotency_key, **kw)

    async def update_server(self, server_id: str, *, idempotency_key=None, **fields) -> Dict[str, Any]:
        return await self._transport.request("PATCH", self._server(server_id),
                                             json_body=_clean(**fields),
                                             idempotency_key=idempotency_key)

    async def delete_server(self, server_id: str, **kw) -> Dict[str, Any]:
        return await self._transport.request("DELETE", self._server(server_id), **kw)

    async def connect(self, server_id: str, *, idempotency_key=None, **kw) -> Dict[str, Any]:
        return await self._transport.request("POST", f"{self._server(server_id)}/connect",
                                             json_body={}, idempotency_key=idempotency_key, **kw)

    async def disconnect(self, server_id: str, *, idempotency_key=None, **kw) -> Dict[str, Any]:
        return await self._transport.request("POST", f"{self._server(server_id)}/disconnect",
                                             json_body={}, idempotency_key=idempotency_key, **kw)

    async def list_server_tools(self, server_id: str, *, limit=None, cursor=None, **kw) -> PaginatedResult:
        return await self._list(f"{self._server(server_id)}/tools", limit=limit, cursor=cursor, **kw)

    async def call_tool(self, server_id: str, tool_name: str, arguments: Optional[Dict[str, Any]] = None, *,
                        idempotency_key=None, **kw) -> Dict[str, Any]:
        return await self._transport.request(
            "POST", f"{self._server(server_id)}/tools/call",
            json_body={"tool": tool_name, "arguments": arguments or {}},
            idempotency_key=idempotency_key, **kw)


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------

class _MemoryMixin:
    def _base(self) -> str:
        return self._org("/memory")  # type: ignore[no-untyped-def]

    def _item(self, memory_id: str) -> str:
        return f"{self._base()}/{memory_id}"  # type: ignore[no-untyped-def]


class Memory(_SyncBase, _MemoryMixin):
    def list(self, *, limit=None, cursor=None, params=None, **kw) -> PaginatedResult:
        return self._list(self._base(), limit=limit, cursor=cursor, params=params, **kw)

    def iterate(self, *, limit=None, params=None, **kw) -> Iterator[Any]:
        return self._iterate(self._base(), limit=limit, params=params, **kw)

    def search(self, query: str, *, limit=None, **kw) -> PaginatedResult:
        return self._list(f"{self._base()}/search", limit=limit, params={"query": query}, **kw)

    def get(self, memory_id: str, **kw) -> Dict[str, Any]:
        return self._transport.request("GET", self._item(memory_id), **kw)

    def create(self, content: Any, *, scope=None, idempotency_key=None, **kw) -> Dict[str, Any]:
        payload = kw.pop("payload", {})
        return self._transport.request(
            "POST", self._base(), json_body=_clean(content=content, scope=scope, **payload),
            idempotency_key=idempotency_key, **kw)

    def update(self, memory_id: str, *, idempotency_key=None, **fields) -> Dict[str, Any]:
        return self._transport.request("PATCH", self._item(memory_id),
                                       json_body=_clean(**fields),
                                       idempotency_key=idempotency_key)

    def delete(self, memory_id: str, **kw) -> Dict[str, Any]:
        return self._transport.request("DELETE", self._item(memory_id), **kw)

    def transition(self, memory_id: str, to_state: str, *, idempotency_key=None, **kw) -> Dict[str, Any]:
        return self._transport.request("POST", f"{self._item(memory_id)}/transition",
                                       json_body={"to_state": to_state},
                                       idempotency_key=idempotency_key, **kw)

    def review(self, memory_id: str, decision: str, *, idempotency_key=None, **kw) -> Dict[str, Any]:
        return self._transport.request("POST", f"{self._item(memory_id)}/review",
                                       json_body={"decision": decision},
                                       idempotency_key=idempotency_key, **kw)

    def correct(self, memory_id: str, content: Any, *, idempotency_key=None, **kw) -> Dict[str, Any]:
        return self._transport.request("POST", f"{self._item(memory_id)}/correct",
                                       json_body={"content": content},
                                       idempotency_key=idempotency_key, **kw)


class AsyncMemory(_AsyncBase, _MemoryMixin):
    async def list(self, *, limit=None, cursor=None, params=None, **kw) -> PaginatedResult:
        return await self._list(self._base(), limit=limit, cursor=cursor, params=params, **kw)

    def iterate(self, *, limit=None, params=None, **kw) -> AsyncIterator[Any]:
        return self._iterate(self._base(), limit=limit, params=params, **kw)

    async def search(self, query: str, *, limit=None, **kw) -> PaginatedResult:
        return await self._list(f"{self._base()}/search", limit=limit, params={"query": query}, **kw)

    async def get(self, memory_id: str, **kw) -> Dict[str, Any]:
        return await self._transport.request("GET", self._item(memory_id), **kw)

    async def create(self, content: Any, *, scope=None, idempotency_key=None, **kw) -> Dict[str, Any]:
        payload = kw.pop("payload", {})
        return await self._transport.request(
            "POST", self._base(), json_body=_clean(content=content, scope=scope, **payload),
            idempotency_key=idempotency_key, **kw)

    async def update(self, memory_id: str, *, idempotency_key=None, **fields) -> Dict[str, Any]:
        return await self._transport.request("PATCH", self._item(memory_id),
                                             json_body=_clean(**fields),
                                             idempotency_key=idempotency_key)

    async def delete(self, memory_id: str, **kw) -> Dict[str, Any]:
        return await self._transport.request("DELETE", self._item(memory_id), **kw)

    async def transition(self, memory_id: str, to_state: str, *, idempotency_key=None, **kw) -> Dict[str, Any]:
        return await self._transport.request("POST", f"{self._item(memory_id)}/transition",
                                             json_body={"to_state": to_state},
                                             idempotency_key=idempotency_key, **kw)

    async def review(self, memory_id: str, decision: str, *, idempotency_key=None, **kw) -> Dict[str, Any]:
        return await self._transport.request("POST", f"{self._item(memory_id)}/review",
                                             json_body={"decision": decision},
                                             idempotency_key=idempotency_key, **kw)

    async def correct(self, memory_id: str, content: Any, *, idempotency_key=None, **kw) -> Dict[str, Any]:
        return await self._transport.request("POST", f"{self._item(memory_id)}/correct",
                                             json_body={"content": content},
                                             idempotency_key=idempotency_key, **kw)


# ---------------------------------------------------------------------------
# Models (discovery)
# ---------------------------------------------------------------------------

class _ModelsMixin:
    def _base(self) -> str:
        return "/models"

    def _item(self, model_id: str) -> str:
        return f"/models/{model_id}"


class Models(_SyncBase, _ModelsMixin):
    def list(self, *, limit=None, cursor=None, params=None, **kw) -> PaginatedResult:
        return self._list(self._base(), limit=limit, cursor=cursor, params=params, **kw)

    def iterate(self, *, limit=None, params=None, **kw) -> Iterator[Any]:
        return self._iterate(self._base(), limit=limit, params=params, **kw)

    def get(self, model_id: str, **kw) -> Dict[str, Any]:
        return self._transport.request("GET", self._item(model_id), **kw)

    def discover(self, *, params=None, **kw) -> PaginatedResult:
        return self._list(f"{self._base()}/discover", params=params, **kw)

    def list_providers(self, **kw) -> PaginatedResult:
        return self._list(f"{self._base()}/providers", **kw)

    def get_provider(self, provider_id: str, **kw) -> Dict[str, Any]:
        return self._transport.request("GET", f"{self._base()}/providers/{provider_id}", **kw)

    def recommend(self, requirements: Optional[Dict[str, Any]] = None, **kw) -> Dict[str, Any]:
        return self._transport.request("POST", f"{self._base()}/recommend",
                                       json_body={"requirements": requirements or {}}, **kw)


class AsyncModels(_AsyncBase, _ModelsMixin):
    async def list(self, *, limit=None, cursor=None, params=None, **kw) -> PaginatedResult:
        return await self._list(self._base(), limit=limit, cursor=cursor, params=params, **kw)

    def iterate(self, *, limit=None, params=None, **kw) -> AsyncIterator[Any]:
        return self._iterate(self._base(), limit=limit, params=params, **kw)

    async def get(self, model_id: str, **kw) -> Dict[str, Any]:
        return await self._transport.request("GET", self._item(model_id), **kw)

    async def discover(self, *, params=None, **kw) -> PaginatedResult:
        return await self._list(f"{self._base()}/discover", params=params, **kw)

    async def list_providers(self, **kw) -> PaginatedResult:
        return await self._list(f"{self._base()}/providers", **kw)

    async def get_provider(self, provider_id: str, **kw) -> Dict[str, Any]:
        return await self._transport.request("GET", f"{self._base()}/providers/{provider_id}", **kw)

    async def recommend(self, requirements: Optional[Dict[str, Any]] = None, **kw) -> Dict[str, Any]:
        return await self._transport.request("POST", f"{self._base()}/recommend",
                                             json_body={"requirements": requirements or {}}, **kw)


# ---------------------------------------------------------------------------
# Evaluations
# ---------------------------------------------------------------------------

class _EvaluationsMixin:
    def _base(self) -> str:
        return self._org("/evaluations")  # type: ignore[no-untyped-def]

    def _item(self, evaluation_id: str) -> str:
        return f"{self._base()}/{evaluation_id}"  # type: ignore[no-untyped-def]

    def _rubrics(self) -> str:
        return self._org("/evaluation-rubrics")  # type: ignore[no-untyped-def]

    def _gates(self) -> str:
        return self._org("/quality-gates")  # type: ignore[no-untyped-def]


class Evaluations(_SyncBase, _EvaluationsMixin):
    def list(self, *, limit=None, cursor=None, params=None, **kw) -> PaginatedResult:
        return self._list(self._base(), limit=limit, cursor=cursor, params=params, **kw)

    def iterate(self, *, limit=None, params=None, **kw) -> Iterator[Any]:
        return self._iterate(self._base(), limit=limit, params=params, **kw)

    def get(self, evaluation_id: str, **kw) -> Dict[str, Any]:
        return self._transport.request("GET", self._item(evaluation_id), **kw)

    def create(self, name: str, *, target=None, idempotency_key=None, **kw) -> Dict[str, Any]:
        payload = kw.pop("payload", {})
        return self._transport.request(
            "POST", self._base(), json_body=_clean(name=name, target=target, **payload),
            idempotency_key=idempotency_key, **kw)

    def run(self, evaluation_id: str, *, input=None, idempotency_key=None, **kw) -> Dict[str, Any]:
        payload = kw.pop("payload", {})
        return self._transport.request(
            "POST", f"{self._item(evaluation_id)}/runs",
            json_body=_clean(input=input, **payload),
            idempotency_key=idempotency_key, **kw)

    def list_runs(self, evaluation_id: str, *, limit=None, cursor=None, **kw) -> PaginatedResult:
        return self._list(f"{self._item(evaluation_id)}/runs", limit=limit, cursor=cursor, **kw)

    def get_run(self, evaluation_id: str, run_id: str, **kw) -> Dict[str, Any]:
        return self._transport.request("GET", f"{self._item(evaluation_id)}/runs/{run_id}", **kw)

    def list_rubrics(self, *, limit=None, cursor=None, **kw) -> PaginatedResult:
        return self._list(self._rubrics(), limit=limit, cursor=cursor, **kw)

    def create_rubric(self, name: str, *, idempotency_key=None, **fields) -> Dict[str, Any]:
        return self._transport.request("POST", self._rubrics(),
                                       json_body=_clean(name=name, **fields),
                                       idempotency_key=idempotency_key)

    def list_gates(self, *, limit=None, cursor=None, **kw) -> PaginatedResult:
        return self._list(self._gates(), limit=limit, cursor=cursor, **kw)

    def evaluate_gate(self, gate_id: str, *, idempotency_key=None, **fields) -> Dict[str, Any]:
        return self._transport.request("POST", f"{self._gates()}/{gate_id}/evaluate",
                                       json_body=_clean(**fields),
                                       idempotency_key=idempotency_key)


class AsyncEvaluations(_AsyncBase, _EvaluationsMixin):
    async def list(self, *, limit=None, cursor=None, params=None, **kw) -> PaginatedResult:
        return await self._list(self._base(), limit=limit, cursor=cursor, params=params, **kw)

    def iterate(self, *, limit=None, params=None, **kw) -> AsyncIterator[Any]:
        return self._iterate(self._base(), limit=limit, params=params, **kw)

    async def get(self, evaluation_id: str, **kw) -> Dict[str, Any]:
        return await self._transport.request("GET", self._item(evaluation_id), **kw)

    async def create(self, name: str, *, target=None, idempotency_key=None, **kw) -> Dict[str, Any]:
        payload = kw.pop("payload", {})
        return await self._transport.request(
            "POST", self._base(), json_body=_clean(name=name, target=target, **payload),
            idempotency_key=idempotency_key, **kw)

    async def run(self, evaluation_id: str, *, input=None, idempotency_key=None, **kw) -> Dict[str, Any]:
        payload = kw.pop("payload", {})
        return await self._transport.request(
            "POST", f"{self._item(evaluation_id)}/runs",
            json_body=_clean(input=input, **payload),
            idempotency_key=idempotency_key, **kw)

    async def list_runs(self, evaluation_id: str, *, limit=None, cursor=None, **kw) -> PaginatedResult:
        return await self._list(f"{self._item(evaluation_id)}/runs", limit=limit, cursor=cursor, **kw)

    async def get_run(self, evaluation_id: str, run_id: str, **kw) -> Dict[str, Any]:
        return await self._transport.request("GET", f"{self._item(evaluation_id)}/runs/{run_id}", **kw)

    async def list_rubrics(self, *, limit=None, cursor=None, **kw) -> PaginatedResult:
        return await self._list(self._rubrics(), limit=limit, cursor=cursor, **kw)

    async def create_rubric(self, name: str, *, idempotency_key=None, **fields) -> Dict[str, Any]:
        return await self._transport.request("POST", self._rubrics(),
                                             json_body=_clean(name=name, **fields),
                                             idempotency_key=idempotency_key)

    async def list_gates(self, *, limit=None, cursor=None, **kw) -> PaginatedResult:
        return await self._list(self._gates(), limit=limit, cursor=cursor, **kw)

    async def evaluate_gate(self, gate_id: str, *, idempotency_key=None, **fields) -> Dict[str, Any]:
        return await self._transport.request("POST", f"{self._gates()}/{gate_id}/evaluate",
                                             json_body=_clean(**fields),
                                             idempotency_key=idempotency_key)


# ---------------------------------------------------------------------------
# Sandboxes
# ---------------------------------------------------------------------------

class _SandboxesMixin:
    def _base(self) -> str:
        return "/sandboxes"

    def _item(self, sandbox_id: str) -> str:
        return f"/sandboxes/{sandbox_id}"

    def _profiles(self) -> str:
        return "/sandbox-profiles"

    def _executions(self) -> str:
        return "/sandbox-executions"


class Sandboxes(_SyncBase, _SandboxesMixin):
    def list(self, *, limit=None, cursor=None, params=None, **kw) -> PaginatedResult:
        return self._list(self._base(), limit=limit, cursor=cursor, params=params, **kw)

    def iterate(self, *, limit=None, params=None, **kw) -> Iterator[Any]:
        return self._iterate(self._base(), limit=limit, params=params, **kw)

    def get(self, sandbox_id: str, **kw) -> Dict[str, Any]:
        return self._transport.request("GET", self._item(sandbox_id), **kw)

    def create(self, *, image=None, idempotency_key=None, **fields) -> Dict[str, Any]:
        return self._transport.request("POST", self._base(),
                                       json_body=_clean(image=image, **fields),
                                       idempotency_key=idempotency_key)

    def delete(self, sandbox_id: str, **kw) -> Dict[str, Any]:
        return self._transport.request("DELETE", self._item(sandbox_id), **kw)

    def execute(self, sandbox_id: str, command: str, *, idempotency_key=None, **kw) -> Dict[str, Any]:
        payload = kw.pop("payload", {})
        return self._transport.request(
            "POST", f"{self._item(sandbox_id)}/execute",
            json_body=_clean(command=command, **payload),
            idempotency_key=idempotency_key, **kw)

    def list_executions(self, *, limit=None, cursor=None, **kw) -> PaginatedResult:
        return self._list(self._executions(), limit=limit, cursor=cursor, **kw)

    def get_execution(self, execution_id: str, **kw) -> Dict[str, Any]:
        return self._transport.request("GET", f"{self._executions()}/{execution_id}", **kw)

    def list_profiles(self, *, limit=None, cursor=None, **kw) -> PaginatedResult:
        return self._list(self._profiles(), limit=limit, cursor=cursor, **kw)

    def create_profile(self, name: str, *, idempotency_key=None, **fields) -> Dict[str, Any]:
        return self._transport.request("POST", self._profiles(),
                                       json_body=_clean(name=name, **fields),
                                       idempotency_key=idempotency_key)


class AsyncSandboxes(_AsyncBase, _SandboxesMixin):
    async def list(self, *, limit=None, cursor=None, params=None, **kw) -> PaginatedResult:
        return await self._list(self._base(), limit=limit, cursor=cursor, params=params, **kw)

    def iterate(self, *, limit=None, params=None, **kw) -> AsyncIterator[Any]:
        return self._iterate(self._base(), limit=limit, params=params, **kw)

    async def get(self, sandbox_id: str, **kw) -> Dict[str, Any]:
        return await self._transport.request("GET", self._item(sandbox_id), **kw)

    async def create(self, *, image=None, idempotency_key=None, **fields) -> Dict[str, Any]:
        return await self._transport.request("POST", self._base(),
                                             json_body=_clean(image=image, **fields),
                                             idempotency_key=idempotency_key)

    async def delete(self, sandbox_id: str, **kw) -> Dict[str, Any]:
        return await self._transport.request("DELETE", self._item(sandbox_id), **kw)

    async def execute(self, sandbox_id: str, command: str, *, idempotency_key=None, **kw) -> Dict[str, Any]:
        payload = kw.pop("payload", {})
        return await self._transport.request(
            "POST", f"{self._item(sandbox_id)}/execute",
            json_body=_clean(command=command, **payload),
            idempotency_key=idempotency_key, **kw)

    async def list_executions(self, *, limit=None, cursor=None, **kw) -> PaginatedResult:
        return await self._list(self._executions(), limit=limit, cursor=cursor, **kw)

    async def get_execution(self, execution_id: str, **kw) -> Dict[str, Any]:
        return await self._transport.request("GET", f"{self._executions()}/{execution_id}", **kw)

    async def list_profiles(self, *, limit=None, cursor=None, **kw) -> PaginatedResult:
        return await self._list(self._profiles(), limit=limit, cursor=cursor, **kw)

    async def create_profile(self, name: str, *, idempotency_key=None, **fields) -> Dict[str, Any]:
        return await self._transport.request("POST", self._profiles(),
                                             json_body=_clean(name=name, **fields),
                                             idempotency_key=idempotency_key)


# ---------------------------------------------------------------------------
# Approvals
# ---------------------------------------------------------------------------

class _ApprovalsMixin:
    def _base(self) -> str:
        return self._org("/approvals")  # type: ignore[no-untyped-def]

    def _item(self, approval_id: str) -> str:
        return f"{self._base()}/{approval_id}"  # type: ignore[no-untyped-def]

    def _policies(self) -> str:
        return self._org("/approval-policies")  # type: ignore[no-untyped-def]

    def _delegations(self) -> str:
        return self._org("/approval-delegations")  # type: ignore[no-untyped-def]


class Approvals(_SyncBase, _ApprovalsMixin):
    def list(self, *, limit=None, cursor=None, params=None, **kw) -> PaginatedResult:
        return self._list(self._base(), limit=limit, cursor=cursor, params=params, **kw)

    def iterate(self, *, limit=None, params=None, **kw) -> Iterator[Any]:
        return self._iterate(self._base(), limit=limit, params=params, **kw)

    def get(self, approval_id: str, **kw) -> Dict[str, Any]:
        return self._transport.request("GET", self._item(approval_id), **kw)

    def create(self, subject: str, action: str, *, idempotency_key=None, **kw) -> Dict[str, Any]:
        payload = kw.pop("payload", {})
        return self._transport.request(
            "POST", self._base(), json_body=_clean(subject=subject, action=action, **payload),
            idempotency_key=idempotency_key, **kw)

    def approve(self, approval_id: str, *, comment=None, idempotency_key=None, **kw) -> Dict[str, Any]:
        return self._transport.request("POST", f"{self._item(approval_id)}/approve",
                                       json_body=_clean(comment=comment),
                                       idempotency_key=idempotency_key, **kw)

    def reject(self, approval_id: str, *, comment=None, idempotency_key=None, **kw) -> Dict[str, Any]:
        return self._transport.request("POST", f"{self._item(approval_id)}/reject",
                                       json_body=_clean(comment=comment),
                                       idempotency_key=idempotency_key, **kw)

    def cancel(self, approval_id: str, *, idempotency_key=None, **kw) -> Dict[str, Any]:
        return self._transport.request("POST", f"{self._item(approval_id)}/cancel",
                                       json_body={}, idempotency_key=idempotency_key, **kw)

    def list_policies(self, *, limit=None, cursor=None, **kw) -> PaginatedResult:
        return self._list(self._policies(), limit=limit, cursor=cursor, **kw)

    def create_policy(self, name: str, *, idempotency_key=None, **fields) -> Dict[str, Any]:
        return self._transport.request("POST", self._policies(),
                                       json_body=_clean(name=name, **fields),
                                       idempotency_key=idempotency_key)

    def get_policy(self, policy_id: str, **kw) -> Dict[str, Any]:
        return self._transport.request("GET", f"{self._policies()}/{policy_id}", **kw)

    def delete_policy(self, policy_id: str, **kw) -> Dict[str, Any]:
        return self._transport.request("DELETE", f"{self._policies()}/{policy_id}", **kw)

    def list_delegations(self, *, limit=None, cursor=None, **kw) -> PaginatedResult:
        return self._list(self._delegations(), limit=limit, cursor=cursor, **kw)

    def create_delegation(self, *, idempotency_key=None, **fields) -> Dict[str, Any]:
        return self._transport.request("POST", self._delegations(),
                                       json_body=_clean(**fields),
                                       idempotency_key=idempotency_key)

    def delete_delegation(self, delegation_id: str, **kw) -> Dict[str, Any]:
        return self._transport.request("DELETE", f"{self._delegations()}/{delegation_id}", **kw)


class AsyncApprovals(_AsyncBase, _ApprovalsMixin):
    async def list(self, *, limit=None, cursor=None, params=None, **kw) -> PaginatedResult:
        return await self._list(self._base(), limit=limit, cursor=cursor, params=params, **kw)

    def iterate(self, *, limit=None, params=None, **kw) -> AsyncIterator[Any]:
        return self._iterate(self._base(), limit=limit, params=params, **kw)

    async def get(self, approval_id: str, **kw) -> Dict[str, Any]:
        return await self._transport.request("GET", self._item(approval_id), **kw)

    async def create(self, subject: str, action: str, *, idempotency_key=None, **kw) -> Dict[str, Any]:
        payload = kw.pop("payload", {})
        return await self._transport.request(
            "POST", self._base(), json_body=_clean(subject=subject, action=action, **payload),
            idempotency_key=idempotency_key, **kw)

    async def approve(self, approval_id: str, *, comment=None, idempotency_key=None, **kw) -> Dict[str, Any]:
        return await self._transport.request("POST", f"{self._item(approval_id)}/approve",
                                             json_body=_clean(comment=comment),
                                             idempotency_key=idempotency_key, **kw)

    async def reject(self, approval_id: str, *, comment=None, idempotency_key=None, **kw) -> Dict[str, Any]:
        return await self._transport.request("POST", f"{self._item(approval_id)}/reject",
                                             json_body=_clean(comment=comment),
                                             idempotency_key=idempotency_key, **kw)

    async def cancel(self, approval_id: str, *, idempotency_key=None, **kw) -> Dict[str, Any]:
        return await self._transport.request("POST", f"{self._item(approval_id)}/cancel",
                                             json_body={}, idempotency_key=idempotency_key, **kw)

    async def list_policies(self, *, limit=None, cursor=None, **kw) -> PaginatedResult:
        return await self._list(self._policies(), limit=limit, cursor=cursor, **kw)

    async def create_policy(self, name: str, *, idempotency_key=None, **fields) -> Dict[str, Any]:
        return await self._transport.request("POST", self._policies(),
                                             json_body=_clean(name=name, **fields),
                                             idempotency_key=idempotency_key)

    async def get_policy(self, policy_id: str, **kw) -> Dict[str, Any]:
        return await self._transport.request("GET", f"{self._policies()}/{policy_id}", **kw)

    async def delete_policy(self, policy_id: str, **kw) -> Dict[str, Any]:
        return await self._transport.request("DELETE", f"{self._policies()}/{policy_id}", **kw)

    async def list_delegations(self, *, limit=None, cursor=None, **kw) -> PaginatedResult:
        return await self._list(self._delegations(), limit=limit, cursor=cursor, **kw)

    async def create_delegation(self, *, idempotency_key=None, **fields) -> Dict[str, Any]:
        return await self._transport.request("POST", self._delegations(),
                                             json_body=_clean(**fields),
                                             idempotency_key=idempotency_key)

    async def delete_delegation(self, delegation_id: str, **kw) -> Dict[str, Any]:
        return await self._transport.request("DELETE", f"{self._delegations()}/{delegation_id}", **kw)


# ---------------------------------------------------------------------------
# Marketplace (+ publishers / listings / reviews)
# ---------------------------------------------------------------------------

class _MarketplaceMixin:
    def _market(self) -> str:
        return "/marketplace"

    def _listing(self, listing_id: str) -> str:
        return f"/marketplace/listings/{listing_id}"


class Marketplace(_SyncBase, _MarketplaceMixin):
    def search(self, query: str, *, kind=None, limit=None, **kw) -> PaginatedResult:
        return self._list("/marketplace/search", limit=limit,
                          params=_clean(query=query, kind=kind), **kw)

    def list_listings(self, *, limit=None, cursor=None, params=None, **kw) -> PaginatedResult:
        return self._list("/marketplace/listings", limit=limit, cursor=cursor, params=params, **kw)

    def iterate_listings(self, *, limit=None, params=None, **kw) -> Iterator[Any]:
        return self._iterate("/marketplace/listings", limit=limit, params=params, **kw)

    def get_listing(self, listing_id: str, **kw) -> Dict[str, Any]:
        return self._transport.request("GET", self._listing(listing_id), **kw)

    def install(self, listing_id: str, *, environment=None, idempotency_key=None, **kw) -> Dict[str, Any]:
        payload = kw.pop("payload", {})
        return self._transport.request(
            "POST", f"{self._listing(listing_id)}/install",
            json_body=_clean(environment=environment, **payload),
            idempotency_key=idempotency_key, **kw)

    def list_publishers(self, *, limit=None, cursor=None, **kw) -> PaginatedResult:
        return self._list("/publishers", limit=limit, cursor=cursor, **kw)

    def get_publisher(self, publisher_id: str, **kw) -> Dict[str, Any]:
        return self._transport.request("GET", f"/publishers/{publisher_id}", **kw)

    def register_publisher(self, name: str, *, idempotency_key=None, **fields) -> Dict[str, Any]:
        return self._transport.request("POST", "/publishers",
                                       json_body=_clean(name=name, **fields),
                                       idempotency_key=idempotency_key)

    def list_reviews(self, listing_id: str, *, limit=None, cursor=None, **kw) -> PaginatedResult:
        return self._list(f"{self._listing(listing_id)}/reviews", limit=limit, cursor=cursor, **kw)

    def create_review(self, listing_id: str, rating: int, body: Optional[str] = None, *,
                      idempotency_key=None, **kw) -> Dict[str, Any]:
        return self._transport.request(
            "POST", f"{self._listing(listing_id)}/reviews",
            json_body=_clean(rating=rating, body=body),
            idempotency_key=idempotency_key, **kw)

    def list_favorites(self, **kw) -> PaginatedResult:
        return self._list("/favorites", **kw)

    def add_favorite(self, listing_id: str, *, idempotency_key=None, **kw) -> Dict[str, Any]:
        return self._transport.request("POST", "/favorites",
                                       json_body={"listing_id": listing_id},
                                       idempotency_key=idempotency_key, **kw)

    def remove_favorite(self, listing_id: str, **kw) -> Dict[str, Any]:
        return self._transport.request("DELETE", f"/favorites/{listing_id}", **kw)


class AsyncMarketplace(_AsyncBase, _MarketplaceMixin):
    async def search(self, query: str, *, kind=None, limit=None, **kw) -> PaginatedResult:
        return await self._list("/marketplace/search", limit=limit,
                                params=_clean(query=query, kind=kind), **kw)

    async def list_listings(self, *, limit=None, cursor=None, params=None, **kw) -> PaginatedResult:
        return await self._list("/marketplace/listings", limit=limit, cursor=cursor, params=params, **kw)

    def iterate_listings(self, *, limit=None, params=None, **kw) -> AsyncIterator[Any]:
        return self._iterate("/marketplace/listings", limit=limit, params=params, **kw)

    async def get_listing(self, listing_id: str, **kw) -> Dict[str, Any]:
        return await self._transport.request("GET", self._listing(listing_id), **kw)

    async def install(self, listing_id: str, *, environment=None, idempotency_key=None, **kw) -> Dict[str, Any]:
        payload = kw.pop("payload", {})
        return await self._transport.request(
            "POST", f"{self._listing(listing_id)}/install",
            json_body=_clean(environment=environment, **payload),
            idempotency_key=idempotency_key, **kw)

    async def list_publishers(self, *, limit=None, cursor=None, **kw) -> PaginatedResult:
        return await self._list("/publishers", limit=limit, cursor=cursor, **kw)

    async def get_publisher(self, publisher_id: str, **kw) -> Dict[str, Any]:
        return await self._transport.request("GET", f"/publishers/{publisher_id}", **kw)

    async def register_publisher(self, name: str, *, idempotency_key=None, **fields) -> Dict[str, Any]:
        return await self._transport.request("POST", "/publishers",
                                             json_body=_clean(name=name, **fields),
                                             idempotency_key=idempotency_key)

    async def list_reviews(self, listing_id: str, *, limit=None, cursor=None, **kw) -> PaginatedResult:
        return await self._list(f"{self._listing(listing_id)}/reviews", limit=limit, cursor=cursor, **kw)

    async def create_review(self, listing_id: str, rating: int, body: Optional[str] = None, *,
                            idempotency_key=None, **kw) -> Dict[str, Any]:
        return await self._transport.request(
            "POST", f"{self._listing(listing_id)}/reviews",
            json_body=_clean(rating=rating, body=body),
            idempotency_key=idempotency_key, **kw)

    async def list_favorites(self, **kw) -> PaginatedResult:
        return await self._list("/favorites", **kw)

    async def add_favorite(self, listing_id: str, *, idempotency_key=None, **kw) -> Dict[str, Any]:
        return await self._transport.request("POST", "/favorites",
                                             json_body={"listing_id": listing_id},
                                             idempotency_key=idempotency_key, **kw)

    async def remove_favorite(self, listing_id: str, **kw) -> Dict[str, Any]:
        return await self._transport.request("DELETE", f"/favorites/{listing_id}", **kw)


# ---------------------------------------------------------------------------
# Registries
# ---------------------------------------------------------------------------

class _RegistriesMixin:
    def _base(self) -> str:
        return "/registries"

    def _item(self, registry_id: str) -> str:
        return f"/registries/{registry_id}"


class Registries(_SyncBase, _RegistriesMixin):
    def list(self, *, limit=None, cursor=None, params=None, **kw) -> PaginatedResult:
        return self._list(self._base(), limit=limit, cursor=cursor, params=params, **kw)

    def iterate(self, *, limit=None, params=None, **kw) -> Iterator[Any]:
        return self._iterate(self._base(), limit=limit, params=params, **kw)

    def get(self, registry_id: str, **kw) -> Dict[str, Any]:
        return self._transport.request("GET", self._item(registry_id), **kw)

    def create(self, name: str, *, url=None, idempotency_key=None, **kw) -> Dict[str, Any]:
        payload = kw.pop("payload", {})
        return self._transport.request(
            "POST", self._base(), json_body=_clean(name=name, url=url, **payload),
            idempotency_key=idempotency_key, **kw)

    def update(self, registry_id: str, *, idempotency_key=None, **fields) -> Dict[str, Any]:
        return self._transport.request("PATCH", self._item(registry_id),
                                       json_body=_clean(**fields),
                                       idempotency_key=idempotency_key)

    def delete(self, registry_id: str, **kw) -> Dict[str, Any]:
        return self._transport.request("DELETE", self._item(registry_id), **kw)

    def lookup(self, registry_id: str, package_name: str, **kw) -> Dict[str, Any]:
        return self._transport.request("GET", f"{self._item(registry_id)}/packages/{package_name}", **kw)

    def publish_package(self, registry_id: str, *, manifest=None, idempotency_key=None, **kw) -> Dict[str, Any]:
        payload = kw.pop("payload", {})
        return self._transport.request(
            "POST", f"{self._item(registry_id)}/packages",
            json_body=_clean(manifest=manifest, **payload),
            idempotency_key=idempotency_key, **kw)


class AsyncRegistries(_AsyncBase, _RegistriesMixin):
    async def list(self, *, limit=None, cursor=None, params=None, **kw) -> PaginatedResult:
        return await self._list(self._base(), limit=limit, cursor=cursor, params=params, **kw)

    def iterate(self, *, limit=None, params=None, **kw) -> AsyncIterator[Any]:
        return self._iterate(self._base(), limit=limit, params=params, **kw)

    async def get(self, registry_id: str, **kw) -> Dict[str, Any]:
        return await self._transport.request("GET", self._item(registry_id), **kw)

    async def create(self, name: str, *, url=None, idempotency_key=None, **kw) -> Dict[str, Any]:
        payload = kw.pop("payload", {})
        return await self._transport.request(
            "POST", self._base(), json_body=_clean(name=name, url=url, **payload),
            idempotency_key=idempotency_key, **kw)

    async def update(self, registry_id: str, *, idempotency_key=None, **fields) -> Dict[str, Any]:
        return await self._transport.request("PATCH", self._item(registry_id),
                                             json_body=_clean(**fields),
                                             idempotency_key=idempotency_key)

    async def delete(self, registry_id: str, **kw) -> Dict[str, Any]:
        return await self._transport.request("DELETE", self._item(registry_id), **kw)

    async def lookup(self, registry_id: str, package_name: str, **kw) -> Dict[str, Any]:
        return await self._transport.request("GET", f"{self._item(registry_id)}/packages/{package_name}", **kw)

    async def publish_package(self, registry_id: str, *, manifest=None, idempotency_key=None, **kw) -> Dict[str, Any]:
        payload = kw.pop("payload", {})
        return await self._transport.request(
            "POST", f"{self._item(registry_id)}/packages",
            json_body=_clean(manifest=manifest, **payload),
            idempotency_key=idempotency_key, **kw)


# ---------------------------------------------------------------------------
# Billing
# ---------------------------------------------------------------------------

class _BillingMixin:
    pass


class Billing(_SyncBase, _BillingMixin):
    def list_products(self, *, limit=None, cursor=None, **kw) -> PaginatedResult:
        return self._list("/products", limit=limit, cursor=cursor, **kw)

    def get_product(self, product_id: str, **kw) -> Dict[str, Any]:
        return self._transport.request("GET", f"/products/{product_id}", **kw)

    def create_product(self, name: str, *, idempotency_key=None, **fields) -> Dict[str, Any]:
        return self._transport.request("POST", "/products",
                                       json_body=_clean(name=name, **fields),
                                       idempotency_key=idempotency_key)

    def list_prices(self, *, product_id=None, limit=None, cursor=None, **kw) -> PaginatedResult:
        return self._list("/prices", limit=limit, cursor=cursor,
                          params=_clean(product_id=product_id), **kw)

    def create_price(self, product_id: str, amount: Any, *, currency="usd",
                     idempotency_key=None, **kw) -> Dict[str, Any]:
        fields = kw.pop("payload", {})
        return self._transport.request(
            "POST", "/prices",
            json_body=_clean(product_id=product_id, amount=amount, currency=currency, **fields),
            idempotency_key=idempotency_key, **kw)

    def create_checkout_session(self, *, idempotency_key=None, **fields) -> Dict[str, Any]:
        return self._transport.request("POST", "/checkout/sessions",
                                       json_body=_clean(**fields),
                                       idempotency_key=idempotency_key)

    def get_checkout_session(self, session_id: str, **kw) -> Dict[str, Any]:
        return self._transport.request("GET", f"/checkout/sessions/{session_id}", **kw)

    def list_subscriptions(self, *, limit=None, cursor=None, **kw) -> PaginatedResult:
        return self._list("/billing/subscriptions", limit=limit, cursor=cursor, **kw)

    def get_subscription(self, subscription_id: str, **kw) -> Dict[str, Any]:
        return self._transport.request("GET", f"/billing/subscriptions/{subscription_id}", **kw)

    def cancel_subscription(self, subscription_id: str, *, idempotency_key=None, **kw) -> Dict[str, Any]:
        return self._transport.request("POST", f"/billing/subscriptions/{subscription_id}/cancel",
                                       json_body={}, idempotency_key=idempotency_key, **kw)

    def entitlements(self, **kw) -> Dict[str, Any]:
        return self._transport.request("GET", "/billing/entitlements", **kw)

    def usage(self, *, params=None, **kw) -> Dict[str, Any]:
        return self._transport.request("GET", "/billing/usage", params=params, **kw)

    def quotas(self, **kw) -> Dict[str, Any]:
        return self._transport.request("GET", "/billing/quotas", **kw)

    def list_invoices(self, *, limit=None, cursor=None, **kw) -> PaginatedResult:
        return self._list("/invoices", limit=limit, cursor=cursor, **kw)

    def get_invoice(self, invoice_id: str, **kw) -> Dict[str, Any]:
        return self._transport.request("GET", f"/invoices/{invoice_id}", **kw)

    def revenue(self, *, params=None, **kw) -> Dict[str, Any]:
        return self._transport.request("GET", "/billing/revenue", params=params, **kw)

    def list_payouts(self, *, limit=None, cursor=None, **kw) -> PaginatedResult:
        return self._list("/billing/payouts", limit=limit, cursor=cursor, **kw)

    def create_payout(self, *, idempotency_key=None, **fields) -> Dict[str, Any]:
        return self._transport.request("POST", "/billing/payouts",
                                       json_body=_clean(**fields),
                                       idempotency_key=idempotency_key)


class AsyncBilling(_AsyncBase, _BillingMixin):
    async def list_products(self, *, limit=None, cursor=None, **kw) -> PaginatedResult:
        return await self._list("/products", limit=limit, cursor=cursor, **kw)

    async def get_product(self, product_id: str, **kw) -> Dict[str, Any]:
        return await self._transport.request("GET", f"/products/{product_id}", **kw)

    async def create_product(self, name: str, *, idempotency_key=None, **fields) -> Dict[str, Any]:
        return await self._transport.request("POST", "/products",
                                             json_body=_clean(name=name, **fields),
                                             idempotency_key=idempotency_key)

    async def list_prices(self, *, product_id=None, limit=None, cursor=None, **kw) -> PaginatedResult:
        return await self._list("/prices", limit=limit, cursor=cursor,
                                params=_clean(product_id=product_id), **kw)

    async def create_price(self, product_id: str, amount: Any, *, currency="usd",
                           idempotency_key=None, **kw) -> Dict[str, Any]:
        fields = kw.pop("payload", {})
        return await self._transport.request(
            "POST", "/prices",
            json_body=_clean(product_id=product_id, amount=amount, currency=currency, **fields),
            idempotency_key=idempotency_key, **kw)

    async def create_checkout_session(self, *, idempotency_key=None, **fields) -> Dict[str, Any]:
        return await self._transport.request("POST", "/checkout/sessions",
                                             json_body=_clean(**fields),
                                             idempotency_key=idempotency_key)

    async def get_checkout_session(self, session_id: str, **kw) -> Dict[str, Any]:
        return await self._transport.request("GET", f"/checkout/sessions/{session_id}", **kw)

    async def list_subscriptions(self, *, limit=None, cursor=None, **kw) -> PaginatedResult:
        return await self._list("/billing/subscriptions", limit=limit, cursor=cursor, **kw)

    async def get_subscription(self, subscription_id: str, **kw) -> Dict[str, Any]:
        return await self._transport.request("GET", f"/billing/subscriptions/{subscription_id}", **kw)

    async def cancel_subscription(self, subscription_id: str, *, idempotency_key=None, **kw) -> Dict[str, Any]:
        return await self._transport.request("POST", f"/billing/subscriptions/{subscription_id}/cancel",
                                             json_body={}, idempotency_key=idempotency_key, **kw)

    async def entitlements(self, **kw) -> Dict[str, Any]:
        return await self._transport.request("GET", "/billing/entitlements", **kw)

    async def usage(self, *, params=None, **kw) -> Dict[str, Any]:
        return await self._transport.request("GET", "/billing/usage", params=params, **kw)

    async def quotas(self, **kw) -> Dict[str, Any]:
        return await self._transport.request("GET", "/billing/quotas", **kw)

    async def list_invoices(self, *, limit=None, cursor=None, **kw) -> PaginatedResult:
        return await self._list("/invoices", limit=limit, cursor=cursor, **kw)

    async def get_invoice(self, invoice_id: str, **kw) -> Dict[str, Any]:
        return await self._transport.request("GET", f"/invoices/{invoice_id}", **kw)

    async def revenue(self, *, params=None, **kw) -> Dict[str, Any]:
        return await self._transport.request("GET", "/billing/revenue", params=params, **kw)

    async def list_payouts(self, *, limit=None, cursor=None, **kw) -> PaginatedResult:
        return await self._list("/billing/payouts", limit=limit, cursor=cursor, **kw)

    async def create_payout(self, *, idempotency_key=None, **fields) -> Dict[str, Any]:
        return await self._transport.request("POST", "/billing/payouts",
                                             json_body=_clean(**fields),
                                             idempotency_key=idempotency_key)


# ---------------------------------------------------------------------------
# Projects (developer API)
# ---------------------------------------------------------------------------

class _ProjectsMixin:
    def _base(self) -> str:
        return self._org("/developer/projects")  # type: ignore[no-untyped-def]

    def _item(self, project_id: str) -> str:
        return f"{self._base()}/{project_id}"  # type: ignore[no-untyped-def]


class Projects(_SyncBase, _ProjectsMixin):
    def list(self, *, limit=None, cursor=None, params=None, **kw) -> PaginatedResult:
        return self._list(self._base(), limit=limit, cursor=cursor, params=params, **kw)

    def iterate(self, *, limit=None, params=None, **kw) -> Iterator[Any]:
        return self._iterate(self._base(), limit=limit, params=params, **kw)

    def get(self, project_id: str, **kw) -> Dict[str, Any]:
        return self._transport.request("GET", self._item(project_id), **kw)

    def create(self, name: str, *, idempotency_key=None, **fields) -> Dict[str, Any]:
        return self._transport.request("POST", self._base(),
                                       json_body=_clean(name=name, **fields),
                                       idempotency_key=idempotency_key)

    def update_environment(self, project_id: str, env: str, config: Dict[str, Any], *,
                           idempotency_key=None, **kw) -> Dict[str, Any]:
        return self._transport.request("PUT", f"{self._item(project_id)}/environments/{env}",
                                       json_body={"config": config},
                                       idempotency_key=idempotency_key, **kw)


class AsyncProjects(_AsyncBase, _ProjectsMixin):
    async def list(self, *, limit=None, cursor=None, params=None, **kw) -> PaginatedResult:
        return await self._list(self._base(), limit=limit, cursor=cursor, params=params, **kw)

    def iterate(self, *, limit=None, params=None, **kw) -> AsyncIterator[Any]:
        return self._iterate(self._base(), limit=limit, params=params, **kw)

    async def get(self, project_id: str, **kw) -> Dict[str, Any]:
        return await self._transport.request("GET", self._item(project_id), **kw)

    async def create(self, name: str, *, idempotency_key=None, **fields) -> Dict[str, Any]:
        return await self._transport.request("POST", self._base(),
                                             json_body=_clean(name=name, **fields),
                                             idempotency_key=idempotency_key)

    async def update_environment(self, project_id: str, env: str, config: Dict[str, Any], *,
                                 idempotency_key=None, **kw) -> Dict[str, Any]:
        return await self._transport.request("PUT", f"{self._item(project_id)}/environments/{env}",
                                             json_body={"config": config},
                                             idempotency_key=idempotency_key, **kw)


# ---------------------------------------------------------------------------
# Extensions (full lifecycle)
# ---------------------------------------------------------------------------

class _ExtensionsMixin:
    def _base(self) -> str:
        return self._org("/extensions")  # type: ignore[no-untyped-def]

    def _item(self, extension_id: str) -> str:
        return f"{self._base()}/{extension_id}"  # type: ignore[no-untyped-def]


class Extensions(_SyncBase, _ExtensionsMixin):
    def list(self, *, limit=None, cursor=None, params=None, **kw) -> PaginatedResult:
        return self._list(self._base(), limit=limit, cursor=cursor, params=params, **kw)

    def iterate(self, *, limit=None, params=None, **kw) -> Iterator[Any]:
        return self._iterate(self._base(), limit=limit, params=params, **kw)

    def get(self, extension_id: str, **kw) -> Dict[str, Any]:
        return self._transport.request("GET", self._item(extension_id), **kw)

    def create(self, name: str, *, kind=None, manifest=None, idempotency_key=None, **kw) -> Dict[str, Any]:
        fields = kw.pop("payload", {})
        return self._transport.request(
            "POST", self._base(),
            json_body=_clean(name=name, kind=kind, manifest=manifest, **fields),
            idempotency_key=idempotency_key, **kw)

    def create_version(self, extension_id: str, version: str, *, manifest=None,
                       idempotency_key=None, **kw) -> Dict[str, Any]:
        fields = kw.pop("payload", {})
        return self._transport.request(
            "POST", f"{self._item(extension_id)}/versions",
            json_body=_clean(version=version, manifest=manifest, **fields),
            idempotency_key=idempotency_key, **kw)

    def validate(self, extension_id: str, *, idempotency_key=None, **kw) -> Dict[str, Any]:
        return self._transport.request("POST", f"{self._item(extension_id)}/validate",
                                       json_body={}, idempotency_key=idempotency_key, **kw)

    def test(self, extension_id: str, *, idempotency_key=None, **kw) -> Dict[str, Any]:
        return self._transport.request("POST", f"{self._item(extension_id)}/test",
                                       json_body={}, idempotency_key=idempotency_key, **kw)

    def package(self, extension_id: str, *, idempotency_key=None, **kw) -> Dict[str, Any]:
        return self._transport.request("POST", f"{self._item(extension_id)}/package",
                                       json_body={}, idempotency_key=idempotency_key, **kw)

    def artifact(self, extension_id: str, **kw) -> Dict[str, Any]:
        return self._transport.request("GET", f"{self._item(extension_id)}/artifact", **kw)

    def publish(self, extension_id: str, *, idempotency_key=None, **kw) -> Dict[str, Any]:
        fields = kw.pop("payload", {})
        return self._transport.request("POST", f"{self._item(extension_id)}/publish",
                                       json_body=_clean(**fields),
                                       idempotency_key=idempotency_key, **kw)

    def sign(self, extension_id: str, *, idempotency_key=None, **kw) -> Dict[str, Any]:
        fields = kw.pop("payload", {})
        return self._transport.request("POST", f"{self._item(extension_id)}/sign",
                                       json_body=_clean(**fields),
                                       idempotency_key=idempotency_key, **kw)

    def sign_complete(self, extension_id: str, signature: str, *, idempotency_key=None, **kw) -> Dict[str, Any]:
        return self._transport.request("POST", f"{self._item(extension_id)}/sign/complete",
                                       json_body={"signature": signature},
                                       idempotency_key=idempotency_key, **kw)

    def install(self, extension_id: str, environment: str, *, idempotency_key=None, **kw) -> Dict[str, Any]:
        fields = kw.pop("payload", {})
        return self._transport.request(
            "POST", f"{self._item(extension_id)}/install",
            json_body=_clean(environment=environment, **fields),
            idempotency_key=idempotency_key, **kw)

    def disable(self, extension_id: str, *, idempotency_key=None, **kw) -> Dict[str, Any]:
        return self._transport.request("POST", f"{self._item(extension_id)}/disable",
                                       json_body={}, idempotency_key=idempotency_key, **kw)

    def quarantine(self, extension_id: str, *, reason=None, idempotency_key=None, **kw) -> Dict[str, Any]:
        return self._transport.request("POST", f"{self._item(extension_id)}/quarantine",
                                       json_body=_clean(reason=reason),
                                       idempotency_key=idempotency_key, **kw)

    def rollback(self, extension_id: str, installation_id: str, *, idempotency_key=None, **kw) -> Dict[str, Any]:
        return self._transport.request("POST", f"{self._item(extension_id)}/rollback",
                                       json_body={"installation_id": installation_id},
                                       idempotency_key=idempotency_key, **kw)

    def deploy(self, extension_id: str, environment: str, *, idempotency_key=None, **kw) -> Dict[str, Any]:
        fields = kw.pop("payload", {})
        return self._transport.request(
            "POST", f"{self._item(extension_id)}/deploy",
            json_body=_clean(environment=environment, **fields),
            idempotency_key=idempotency_key, **kw)


class AsyncExtensions(_AsyncBase, _ExtensionsMixin):
    async def list(self, *, limit=None, cursor=None, params=None, **kw) -> PaginatedResult:
        return await self._list(self._base(), limit=limit, cursor=cursor, params=params, **kw)

    def iterate(self, *, limit=None, params=None, **kw) -> AsyncIterator[Any]:
        return self._iterate(self._base(), limit=limit, params=params, **kw)

    async def get(self, extension_id: str, **kw) -> Dict[str, Any]:
        return await self._transport.request("GET", self._item(extension_id), **kw)

    async def create(self, name: str, *, kind=None, manifest=None, idempotency_key=None, **kw) -> Dict[str, Any]:
        fields = kw.pop("payload", {})
        return await self._transport.request(
            "POST", self._base(),
            json_body=_clean(name=name, kind=kind, manifest=manifest, **fields),
            idempotency_key=idempotency_key, **kw)

    async def create_version(self, extension_id: str, version: str, *, manifest=None,
                             idempotency_key=None, **kw) -> Dict[str, Any]:
        fields = kw.pop("payload", {})
        return await self._transport.request(
            "POST", f"{self._item(extension_id)}/versions",
            json_body=_clean(version=version, manifest=manifest, **fields),
            idempotency_key=idempotency_key, **kw)

    async def validate(self, extension_id: str, *, idempotency_key=None, **kw) -> Dict[str, Any]:
        return await self._transport.request("POST", f"{self._item(extension_id)}/validate",
                                             json_body={}, idempotency_key=idempotency_key, **kw)

    async def test(self, extension_id: str, *, idempotency_key=None, **kw) -> Dict[str, Any]:
        return await self._transport.request("POST", f"{self._item(extension_id)}/test",
                                             json_body={}, idempotency_key=idempotency_key, **kw)

    async def package(self, extension_id: str, *, idempotency_key=None, **kw) -> Dict[str, Any]:
        return await self._transport.request("POST", f"{self._item(extension_id)}/package",
                                             json_body={}, idempotency_key=idempotency_key, **kw)

    async def artifact(self, extension_id: str, **kw) -> Dict[str, Any]:
        return await self._transport.request("GET", f"{self._item(extension_id)}/artifact", **kw)

    async def publish(self, extension_id: str, *, idempotency_key=None, **kw) -> Dict[str, Any]:
        fields = kw.pop("payload", {})
        return await self._transport.request("POST", f"{self._item(extension_id)}/publish",
                                             json_body=_clean(**fields),
                                             idempotency_key=idempotency_key, **kw)

    async def sign(self, extension_id: str, *, idempotency_key=None, **kw) -> Dict[str, Any]:
        fields = kw.pop("payload", {})
        return await self._transport.request("POST", f"{self._item(extension_id)}/sign",
                                             json_body=_clean(**fields),
                                             idempotency_key=idempotency_key, **kw)

    async def sign_complete(self, extension_id: str, signature: str, *, idempotency_key=None, **kw) -> Dict[str, Any]:
        return await self._transport.request("POST", f"{self._item(extension_id)}/sign/complete",
                                             json_body={"signature": signature},
                                             idempotency_key=idempotency_key, **kw)

    async def install(self, extension_id: str, environment: str, *, idempotency_key=None, **kw) -> Dict[str, Any]:
        fields = kw.pop("payload", {})
        return await self._transport.request(
            "POST", f"{self._item(extension_id)}/install",
            json_body=_clean(environment=environment, **fields),
            idempotency_key=idempotency_key, **kw)

    async def disable(self, extension_id: str, *, idempotency_key=None, **kw) -> Dict[str, Any]:
        return await self._transport.request("POST", f"{self._item(extension_id)}/disable",
                                             json_body={}, idempotency_key=idempotency_key, **kw)

    async def quarantine(self, extension_id: str, *, reason=None, idempotency_key=None, **kw) -> Dict[str, Any]:
        return await self._transport.request("POST", f"{self._item(extension_id)}/quarantine",
                                             json_body=_clean(reason=reason),
                                             idempotency_key=idempotency_key, **kw)

    async def rollback(self, extension_id: str, installation_id: str, *, idempotency_key=None, **kw) -> Dict[str, Any]:
        return await self._transport.request("POST", f"{self._item(extension_id)}/rollback",
                                             json_body={"installation_id": installation_id},
                                             idempotency_key=idempotency_key, **kw)

    async def deploy(self, extension_id: str, environment: str, *, idempotency_key=None, **kw) -> Dict[str, Any]:
        fields = kw.pop("payload", {})
        return await self._transport.request(
            "POST", f"{self._item(extension_id)}/deploy",
            json_body=_clean(environment=environment, **fields),
            idempotency_key=idempotency_key, **kw)


# ---------------------------------------------------------------------------
# Deployments (developer API)
# ---------------------------------------------------------------------------

class _DeploymentsMixin:
    def _base(self) -> str:
        return self._org("/developer/deployments")  # type: ignore[no-untyped-def]

    def _item(self, deployment_id: str) -> str:
        return f"{self._base()}/{deployment_id}"  # type: ignore[no-untyped-def]


class Deployments(_SyncBase, _DeploymentsMixin):
    def list(self, *, limit=None, cursor=None, params=None, **kw) -> PaginatedResult:
        return self._list(self._base(), limit=limit, cursor=cursor, params=params, **kw)

    def iterate(self, *, limit=None, params=None, **kw) -> Iterator[Any]:
        return self._iterate(self._base(), limit=limit, params=params, **kw)

    def get(self, deployment_id: str, **kw) -> Dict[str, Any]:
        return self._transport.request("GET", self._item(deployment_id), **kw)

    def cancel(self, deployment_id: str, *, idempotency_key=None, **kw) -> Dict[str, Any]:
        return self._transport.request("POST", f"{self._item(deployment_id)}/cancel",
                                       json_body={}, idempotency_key=idempotency_key, **kw)

    def logs(self, deployment_id: str, *, limit=None, cursor=None, **kw) -> PaginatedResult:
        return self._list(f"{self._item(deployment_id)}/logs", limit=limit, cursor=cursor, **kw)


class AsyncDeployments(_AsyncBase, _DeploymentsMixin):
    async def list(self, *, limit=None, cursor=None, params=None, **kw) -> PaginatedResult:
        return await self._list(self._base(), limit=limit, cursor=cursor, params=params, **kw)

    def iterate(self, *, limit=None, params=None, **kw) -> AsyncIterator[Any]:
        return self._iterate(self._base(), limit=limit, params=params, **kw)

    async def get(self, deployment_id: str, **kw) -> Dict[str, Any]:
        return await self._transport.request("GET", self._item(deployment_id), **kw)

    async def cancel(self, deployment_id: str, *, idempotency_key=None, **kw) -> Dict[str, Any]:
        return await self._transport.request("POST", f"{self._item(deployment_id)}/cancel",
                                             json_body={}, idempotency_key=idempotency_key, **kw)

    async def logs(self, deployment_id: str, *, limit=None, cursor=None, **kw) -> PaginatedResult:
        return await self._list(f"{self._item(deployment_id)}/logs", limit=limit, cursor=cursor, **kw)


# ---------------------------------------------------------------------------
# Events (developer API)
# ---------------------------------------------------------------------------

class _EventsMixin:
    def _org_base(self) -> str:
        return self._org("/developer/events")  # type: ignore[no-untyped-def]


class Events(_SyncBase, _EventsMixin):
    def list_schemas(self, **kw) -> PaginatedResult:
        return self._transport.request_paginated("GET", "/developer/events", **kw)

    def list(self, *, limit=None, cursor=None, params=None, **kw) -> PaginatedResult:
        return self._list(self._org_base(), limit=limit, cursor=cursor, params=params, **kw)

    def iterate(self, *, limit=None, params=None, **kw) -> Iterator[Any]:
        return self._iterate(self._org_base(), limit=limit, params=params, **kw)

    def get(self, event_id: str, **kw) -> Dict[str, Any]:
        return self._transport.request("GET", f"{self._org_base()}/{event_id}", **kw)

    def usage(self, *, params=None, **kw) -> Dict[str, Any]:
        return self._transport.request("GET", self._org("/developer/usage"), params=params, **kw)


class AsyncEvents(_AsyncBase, _EventsMixin):
    async def list_schemas(self, **kw) -> PaginatedResult:
        return await self._transport.request_paginated("GET", "/developer/events", **kw)

    async def list(self, *, limit=None, cursor=None, params=None, **kw) -> PaginatedResult:
        return await self._list(self._org_base(), limit=limit, cursor=cursor, params=params, **kw)

    def iterate(self, *, limit=None, params=None, **kw) -> AsyncIterator[Any]:
        return self._iterate(self._org_base(), limit=limit, params=params, **kw)

    async def get(self, event_id: str, **kw) -> Dict[str, Any]:
        return await self._transport.request("GET", f"{self._org_base()}/{event_id}", **kw)

    async def usage(self, *, params=None, **kw) -> Dict[str, Any]:
        return await self._transport.request("GET", self._org("/developer/usage"), params=params, **kw)


# ---------------------------------------------------------------------------
# Webhooks (developer API CRUD + server-side verify helper)
# ---------------------------------------------------------------------------

class _WebhooksMixin:
    def _base(self) -> str:
        return self._org("/developer/webhooks")  # type: ignore[no-untyped-def]

    def _item(self, webhook_id: str) -> str:
        return f"{self._base()}/{webhook_id}"  # type: ignore[no-untyped-def]

    @staticmethod
    def verify(secret: str, body: bytes, header: str, *,
               now: int = 0, tolerance: int = 300) -> Dict[str, Any]:
        """Verify an inbound webhook signature (server-side helper)."""
        return verify_webhook(secret, body, header, now=now, tolerance=tolerance)


class Webhooks(_SyncBase, _WebhooksMixin):
    def list(self, *, limit=None, cursor=None, params=None, **kw) -> PaginatedResult:
        return self._list(self._base(), limit=limit, cursor=cursor, params=params, **kw)

    def iterate(self, *, limit=None, params=None, **kw) -> Iterator[Any]:
        return self._iterate(self._base(), limit=limit, params=params, **kw)

    def get(self, webhook_id: str, **kw) -> Dict[str, Any]:
        return self._transport.request("GET", self._item(webhook_id), **kw)

    def create(self, url: str, events: List[str], *, secret=None, idempotency_key=None, **kw) -> Dict[str, Any]:
        fields = kw.pop("payload", {})
        return self._transport.request(
            "POST", self._base(),
            json_body=_clean(url=url, events=events, secret=secret, **fields),
            idempotency_key=idempotency_key, **kw)

    def update(self, webhook_id: str, *, idempotency_key=None, **fields) -> Dict[str, Any]:
        return self._transport.request("PATCH", self._item(webhook_id),
                                       json_body=_clean(**fields),
                                       idempotency_key=idempotency_key)

    def delete(self, webhook_id: str, **kw) -> Dict[str, Any]:
        return self._transport.request("DELETE", self._item(webhook_id), **kw)

    def rotate_secret(self, webhook_id: str, *, idempotency_key=None, **kw) -> Dict[str, Any]:
        return self._transport.request("POST", f"{self._item(webhook_id)}/rotate",
                                       json_body={}, idempotency_key=idempotency_key, **kw)

    def test(self, webhook_id: str, event: str, *, idempotency_key=None, **kw) -> Dict[str, Any]:
        return self._transport.request("POST", f"{self._item(webhook_id)}/test",
                                       json_body={"event": event},
                                       idempotency_key=idempotency_key, **kw)


class AsyncWebhooks(_AsyncBase, _WebhooksMixin):
    async def list(self, *, limit=None, cursor=None, params=None, **kw) -> PaginatedResult:
        return await self._list(self._base(), limit=limit, cursor=cursor, params=params, **kw)

    def iterate(self, *, limit=None, params=None, **kw) -> AsyncIterator[Any]:
        return self._iterate(self._base(), limit=limit, params=params, **kw)

    async def get(self, webhook_id: str, **kw) -> Dict[str, Any]:
        return await self._transport.request("GET", self._item(webhook_id), **kw)

    async def create(self, url: str, events: List[str], *, secret=None, idempotency_key=None, **kw) -> Dict[str, Any]:
        fields = kw.pop("payload", {})
        return await self._transport.request(
            "POST", self._base(),
            json_body=_clean(url=url, events=events, secret=secret, **fields),
            idempotency_key=idempotency_key, **kw)

    async def update(self, webhook_id: str, *, idempotency_key=None, **fields) -> Dict[str, Any]:
        return await self._transport.request("PATCH", self._item(webhook_id),
                                             json_body=_clean(**fields),
                                             idempotency_key=idempotency_key)

    async def delete(self, webhook_id: str, **kw) -> Dict[str, Any]:
        return await self._transport.request("DELETE", self._item(webhook_id), **kw)

    async def rotate_secret(self, webhook_id: str, *, idempotency_key=None, **kw) -> Dict[str, Any]:
        return await self._transport.request("POST", f"{self._item(webhook_id)}/rotate",
                                             json_body={}, idempotency_key=idempotency_key, **kw)

    async def test(self, webhook_id: str, event: str, *, idempotency_key=None, **kw) -> Dict[str, Any]:
        return await self._transport.request("POST", f"{self._item(webhook_id)}/test",
                                             json_body={"event": event},
                                             idempotency_key=idempotency_key, **kw)
