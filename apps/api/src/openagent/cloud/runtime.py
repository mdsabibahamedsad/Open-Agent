"""MP25: runtime provider abstraction (§4).

``RuntimeProvider`` is provider-neutral. The core execution engine talks
to it; local/docker/cloud backends implement it. Cloud mode reuses the
dispatcher + queues + workers rather than forking execution logic.
"""

from __future__ import annotations

import abc
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Optional

from openagent.cloud.types import ExecutionState


@dataclass
class ExecutionRequest:
    organization_id: str
    project_id: str = ""
    environment: str = "production"
    execution_class: str = "workflow"
    workflow_id: str = ""
    agent_id: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    priority: str = "NORMAL"
    region_id: str = ""
    pool_id: str = ""
    residency: str = "ANY_REGION"
    cpu_millicores: int = 500
    memory_mb: int = 512
    timeout_seconds: int = 600
    idempotency_key: str = ""
    run_at: Optional[datetime] = None
    labels: dict[str, str] = field(default_factory=dict)


@dataclass
class ExecutionHandle:
    execution_id: str
    status: str
    region_id: str
    queue: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class ExecutionView:
    execution_id: str
    status: str
    region_id: str
    queue: str
    worker_id: str = ""
    attempt: int = 0
    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: str = ""
    result_ref: str = ""
    usage: dict[str, float] = field(default_factory=dict)


class RuntimeProvider(abc.ABC):
    @abc.abstractmethod
    async def submit_execution(self, request: ExecutionRequest) -> ExecutionHandle: ...

    @abc.abstractmethod
    async def cancel_execution(self, execution_id: str, organization_id: str) -> ExecutionView: ...

    @abc.abstractmethod
    async def get_execution(self, execution_id: str, organization_id: str) -> ExecutionView: ...

    @abc.abstractmethod
    async def stream_execution(self, execution_id: str, organization_id: str,
                               from_sequence: int = 0) -> AsyncIterator[dict]: ...


class LocalRuntimeProvider(RuntimeProvider):
    """Self-hosted in-process/local-worker runtime (no cloud dependency)."""

    def __init__(self) -> None:
        self._executions: dict[str, ExecutionView] = {}

    async def submit_execution(self, request: ExecutionRequest) -> ExecutionHandle:
        execution_id = f"exe_{uuid.uuid4().hex[:16]}"
        view = ExecutionView(execution_id=execution_id, status=ExecutionState.QUEUED,
                             region_id="local-1", queue="workflow.default")
        self._executions[execution_id] = view
        return ExecutionHandle(execution_id=execution_id, status=view.status,
                               region_id=view.region_id, queue=view.queue)

    async def cancel_execution(self, execution_id: str, organization_id: str) -> ExecutionView:
        view = await self.get_execution(execution_id, organization_id)
        from openagent.cloud.types import is_valid_execution_transition
        if is_valid_execution_transition(view.status, ExecutionState.CANCELLED):
            view.status = ExecutionState.CANCELLED
        return view

    async def get_execution(self, execution_id: str, organization_id: str) -> ExecutionView:
        view = self._executions.get(execution_id)
        if view is None:
            raise KeyError(f"execution {execution_id} not found")
        return view

    async def stream_execution(self, execution_id: str, organization_id: str,
                               from_sequence: int = 0):
        view = await self.get_execution(execution_id, organization_id)
        yield {"sequence": from_sequence, "type": "execution.snapshot",
               "execution_id": view.execution_id, "status": view.status}
        return


class DockerRuntimeProvider(LocalRuntimeProvider):
    """Docker-based self-hosted runtime (same API; scheduler pins sandbox provider)."""

    def __init__(self, sandbox_image: str = "openagent-sandbox-base") -> None:
        super().__init__()
        self.sandbox_image = sandbox_image


class CloudRuntimeProvider(RuntimeProvider):
    """Cloud execution-plane adapter: delegates to the dispatcher service.

    The heavy lifting (authz/entitlement/quota/placement/queue) lives in
    :class:`openagent.cloud.dispatcher.ExecutionDispatcher`; this adapter
    keeps the ``RuntimeProvider`` surface stable across modes.
    """

    def __init__(self, dispatcher) -> None:
        self.dispatcher = dispatcher

    async def submit_execution(self, request: ExecutionRequest) -> ExecutionHandle:
        return await self.dispatcher.dispatch(request)

    async def cancel_execution(self, execution_id: str, organization_id: str) -> ExecutionView:
        return await self.dispatcher.cancel(execution_id, organization_id)

    async def get_execution(self, execution_id: str, organization_id: str) -> ExecutionView:
        return await self.dispatcher.describe(execution_id, organization_id)

    async def stream_execution(self, execution_id: str, organization_id: str,
                               from_sequence: int = 0):
        async for event in self.dispatcher.stream(execution_id, organization_id,
                                                  from_sequence=from_sequence):
            yield event


def get_runtime_provider(mode: str, dispatcher=None) -> RuntimeProvider:
    mode = str(mode or "self_hosted").lower()
    if mode == "cloud":
        if dispatcher is None:
            raise ValueError("cloud runtime requires a dispatcher")
        return CloudRuntimeProvider(dispatcher)
    if mode == "docker":
        return DockerRuntimeProvider()
    return LocalRuntimeProvider()
