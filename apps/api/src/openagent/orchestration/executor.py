"""Orchestration executor: drives the task graph to completion.

Uses existing Agent Runtime (AgentLoop), Model Router, and Tool Runtime.
No second model/tool system is created here.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set
from uuid import UUID

import structlog

from openagent.orchestration.aggregation import AgentResult, aggregate_results
from openagent.orchestration.budgets import BudgetExceeded, BudgetState
from openagent.orchestration.events import record_metric
from openagent.orchestration.security import cap_output, sanitize_dict
from openagent.orchestration.supervisor import AgentSupervisor, TaskSnapshot
from openagent.orchestration.task_graph import (
    TaskNode,
    dependencies_satisfied,
    detect_deadlock,
    find_cycle,
    should_fail_parent,
    topological_order,
)
from openagent.orchestration.types import (
    AggregationStrategy,
    Budget,
    DependencyPolicy,
    OrchTaskStatus,
)

logger = structlog.get_logger("orchestration.executor")


@dataclass
class TaskSpec:
    id: UUID
    external_task_id: str
    title: str
    instructions: str
    input: Dict[str, Any]
    required_capabilities: List[str]
    priority: str
    dependency_policy: DependencyPolicy
    dependencies: List[str]  # external ids
    assigned_agent_id: Optional[UUID]
    timeout_seconds: int
    max_retries: int
    retry_strategy: str
    risk_level: str
    depth: int
    requires_approval: bool = False


@dataclass
class ExecutorResult:
    status: str
    final_result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    tasks_succeeded: int = 0
    tasks_failed: int = 0


AgentTaskRunner = Callable[[TaskSpec, Optional[UUID], Budget], Awaitable[Dict[str, Any]]]
"""Runner signature: (task, agent_id, child_budget) -> {status, output?, usage?, error?}."""


class OrchestrationExecutor:
    """In-process DAG driver. Persistence + locking owned by the service layer."""

    def __init__(
        self,
        runner: AgentTaskRunner,
        *,
        supervisor: Optional[AgentSupervisor] = None,
        max_parallel_tasks: int = 10,
        heartbeat_callback: Optional[Callable[[UUID], Awaitable[None]]] = None,
        event_callback: Optional[Callable[..., Awaitable[None]]] = None,
        should_stop: Optional[Callable[[], Awaitable[bool]]] = None,
    ):
        self.runner = runner
        self.supervisor = supervisor or AgentSupervisor()
        self.max_parallel_tasks = max_parallel_tasks
        self.heartbeat_callback = heartbeat_callback
        self.event_callback = event_callback
        self.should_stop = should_stop

    async def run(
        self,
        *,
        tasks: List[TaskSpec],
        budget: Budget,
        aggregation: Optional[AggregationStrategy] = None,
        initial: Optional[Dict[str, OrchTaskStatus]] = None,
        initial_outputs: Optional[Dict[str, Dict[str, Any]]] = None,
        approved: Optional[Set[str]] = None,
    ) -> ExecutorResult:
        state = BudgetState(limits=budget)
        nodes: Dict[str, TaskNode] = {
            t.external_task_id: TaskNode(
                task_id=t.external_task_id,
                dependencies=list(t.dependencies),
                status=OrchTaskStatus.CREATED,
                dependency_policy=t.dependency_policy,
            )
            for t in tasks
        }
        by_ext = {t.external_task_id: t for t in tasks}
        cycle = find_cycle(nodes)
        if cycle:
            return ExecutorResult("failed", error=f"cycle: {' -> '.join(cycle)}")
        try:
            order = topological_order(nodes)
        except ValueError as exc:
            return ExecutorResult("failed", error=str(exc))
        _ = order

        statuses: Dict[str, OrchTaskStatus] = {
            nid: (initial.get(nid, OrchTaskStatus.CREATED) if initial else OrchTaskStatus.CREATED)
            for nid in nodes
        }
        for nid, node in nodes.items():
            node.status = statuses[nid]
        outputs: Dict[str, Dict[str, Any]] = dict(initial_outputs or {})
        attempts: Dict[str, int] = {nid: 0 for nid in nodes}
        sem = asyncio.Semaphore(max(1, self.max_parallel_tasks))
        delegation_chains: Dict[str, List[str]] = {nid: [] for nid in nodes}

        async def execute_one(ext_id: str) -> bool:
            spec = by_ext[ext_id]
            async with sem:
                if self.should_stop and await self.should_stop():
                    statuses[ext_id] = OrchTaskStatus.CANCELLED
                    nodes[ext_id].status = OrchTaskStatus.CANCELLED
                    return False
                # Idempotency guard: only schedulable tasks execute.
                if statuses[ext_id] not in (
                    OrchTaskStatus.CREATED,
                    OrchTaskStatus.READY,
                    OrchTaskStatus.ASSIGNED,
                ):
                    return statuses[ext_id] == OrchTaskStatus.SUCCEEDED
                statuses[ext_id] = OrchTaskStatus.RUNNING
                nodes[ext_id].status = OrchTaskStatus.RUNNING
                await self._emit("TASK_STARTED", spec, None)
                attempts[ext_id] += 1
                if self.heartbeat_callback:
                    try:
                        await self.heartbeat_callback(spec.id)
                    except Exception:
                        pass
                deadline = time.monotonic() + max(1, spec.timeout_seconds)
                try:
                    child = state.child_budget(fraction=1.0)
                    result = await self.runner(spec, spec.assigned_agent_id, child)
                except BudgetExceeded as exc:
                    statuses[ext_id] = OrchTaskStatus.FAILED
                    nodes[ext_id].status = OrchTaskStatus.FAILED
                    return False
                except Exception as exc:  # noqa: BLE001 - runner errors become task failures
                    logger.error("task runner raised", task=ext_id, error=str(exc))
                    result = {"status": "failed", "error": str(exc)}
                if time.monotonic() > deadline:
                    statuses[ext_id] = OrchTaskStatus.TIMED_OUT
                    nodes[ext_id].status = OrchTaskStatus.TIMED_OUT
                    await self._emit("TASK_FAILED", spec, {"reason": "timeout"})
                    return False
                usage_raw = result.get("usage", {}) if isinstance(result, dict) else {}
                usage = usage_raw if isinstance(usage_raw, dict) else {}
                try:
                    state.consume(
                        tokens=int(usage.get("tokens", 0)),
                        cost=float(usage.get("cost", 0.0)),
                        tool_calls=int(usage.get("tool_calls", 0)),
                        steps=int(usage.get("steps", 1)),
                        tasks=1,
                    )
                except BudgetExceeded:
                    statuses[ext_id] = OrchTaskStatus.FAILED
                    nodes[ext_id].status = OrchTaskStatus.FAILED
                    await self._emit("BUDGET_EXCEEDED", spec, usage)
                    return False
                if isinstance(result, dict) and result.get("status") == "succeeded":
                    raw_output = result.get("output", {}) or {}
                    if not isinstance(raw_output, dict):
                        raw_output = {"value": raw_output}
                    outputs[ext_id] = cap_output(sanitize_dict(raw_output), 256 * 1024)
                    statuses[ext_id] = OrchTaskStatus.SUCCEEDED
                    nodes[ext_id].status = OrchTaskStatus.SUCCEEDED
                    await self._emit(
                        "TASK_COMPLETED",
                        spec,
                        {"attempt": attempts[ext_id], "output": outputs[ext_id]},
                    )
                    record_metric("tasks_completed_total")
                    return True
                statuses[ext_id] = OrchTaskStatus.FAILED
                nodes[ext_id].status = OrchTaskStatus.FAILED
                await self._emit(
                    "TASK_FAILED", spec, {"error": str(result.get("error", "failed"))[:2000]}
                )
                record_metric("tasks_failed_total")
                return False

        # Level-by-level execution preserves dependencies; independent tasks
        # within a level run concurrently. Previously-terminal tasks keep
        # their status so resume never re-executes completed work.
        # Human approval hook (MP19 ships the full system): tasks requiring
        # approval wait unless their id is in `approved`.
        approved_ids = approved or set()
        for ext_id, spec in by_ext.items():
            if (
                spec.requires_approval
                and ext_id not in approved_ids
                and statuses[ext_id] not in _terminal()
                and statuses[ext_id] != OrchTaskStatus.WAITING
            ):
                statuses[ext_id] = OrchTaskStatus.WAITING
                nodes[ext_id].status = OrchTaskStatus.WAITING
        pending = {nid for nid, s in statuses.items() if s not in _terminal() and s != OrchTaskStatus.WAITING}
        succeeded_overall = True
        while pending:
            if self.should_stop and await self.should_stop():
                for ext_id in list(pending):
                    statuses[ext_id] = OrchTaskStatus.CANCELLED
                    nodes[ext_id].status = OrchTaskStatus.CANCELLED
                break
            deadlock = detect_deadlock(nodes)
            if deadlock:
                return ExecutorResult("failed", error=f"deadlock: {deadlock}")
            runnable = [
                ext_id
                for ext_id in pending
                if dependencies_satisfied(nodes[ext_id], statuses)
            ]
            if not runnable:
                # Nothing runnable: apply dependency policies to unblock or fail.
                progressed = False
                for ext_id in list(pending):
                    node = nodes[ext_id]
                    deps = [statuses.get(d) for d in node.dependencies]
                    if deps and all(d in _terminal() for d in deps if d is not None):
                        if should_fail_parent(node, statuses):
                            statuses[ext_id] = OrchTaskStatus.FAILED
                            node.status = OrchTaskStatus.FAILED
                            pending.discard(ext_id)
                            progressed = True
                            succeeded_overall = False
                if not progressed:
                    break
                continue
            # Priority: critical first, then fewest dependencies.
            runnable.sort(key=lambda e: (_priority_rank(by_ext[e].priority), len(by_ext[e].dependencies), e))
            results = await asyncio.gather(*(execute_one(e) for e in runnable))
            for ext_id, ok in zip(runnable, results):
                pending.discard(ext_id)
                # Retry within budget before giving up.
                spec = by_ext[ext_id]
                if not ok and statuses[ext_id] == OrchTaskStatus.FAILED:
                    if attempts[ext_id] <= spec.max_retries and spec.retry_strategy != "none":
                        if spec.retry_strategy in ("fixed", "exponential_backoff"):
                            delay = 0.05 * (2 ** (attempts[ext_id] - 1))
                            await asyncio.sleep(min(delay, 2.0))
                        statuses[ext_id] = OrchTaskStatus.CREATED
                        nodes[ext_id].status = OrchTaskStatus.CREATED
                        pending.add(ext_id)
                        continue
                    succeeded_overall = False
            # Supervisor pass: stalled/loop detection hooks.
            snapshots = [
                TaskSnapshot(
                    task_id=e,
                    status=statuses[e],
                    retry_count=attempts[e],
                    max_retries=by_ext[e].max_retries,
                    timeout_seconds=by_ext[e].timeout_seconds,
                    delegation_chain=delegation_chains.get(e, []),
                )
                for e in pending
            ]
            loop = any(self.supervisor.detect_delegation_loop(c) for c in delegation_chains.values() if c)
            decisions = await self.supervisor.supervise(snapshots, loop_detected=loop)
            for d in decisions:
                if d.action == "pause":
                    return ExecutorResult("paused", error=d.reason)
                if d.action == "escalate":
                    return ExecutorResult("failed", error=d.reason)

        succeeded = sum(1 for s in statuses.values() if s == OrchTaskStatus.SUCCEEDED)
        failed = sum(1 for s in statuses.values() if s in (OrchTaskStatus.FAILED, OrchTaskStatus.TIMED_OUT))
        waiting = sum(1 for s in statuses.values() if s == OrchTaskStatus.WAITING)
        agent_results = [
            AgentResult(task_id=e, agent_id=str(by_ext[e].assigned_agent_id) if by_ext[e].assigned_agent_id else None,
                        output=outputs.get(e, {}))
            for e, s in statuses.items() if s == OrchTaskStatus.SUCCEEDED
        ]
        final = aggregate_results(aggregation or AggregationStrategy.SUMMARIZE, agent_results)
        final["tasks_succeeded"] = succeeded
        final["tasks_failed"] = failed
        final["tasks_waiting"] = waiting
        if waiting and not failed:
            for ext_id, s in statuses.items():
                if s == OrchTaskStatus.WAITING:
                    await self._emit("TASK_PROGRESS", by_ext[ext_id],
                                     {"reason": "approval_required"})
            return ExecutorResult("waiting", final_result=final,
                                  tasks_succeeded=succeeded, tasks_failed=failed)
        if succeeded and not failed:
            return ExecutorResult("succeeded", final_result=final,
                                  tasks_succeeded=succeeded, tasks_failed=failed)
        if succeeded and failed:
            return ExecutorResult("partially_succeeded", final_result=final,
                                  tasks_succeeded=succeeded, tasks_failed=failed)
        return ExecutorResult("failed", final_result=final,
                              error="all tasks failed" if not succeeded_overall else "tasks failed",
                              tasks_succeeded=succeeded, tasks_failed=failed)

    async def _emit(self, event_type: str, spec: TaskSpec, payload: Optional[Dict[str, Any]]) -> None:
        if self.event_callback:
            try:
                await self.event_callback(event_type, spec, payload or {})
            except Exception:
                pass


def _terminal() -> set[OrchTaskStatus]:
    return {
        OrchTaskStatus.SUCCEEDED,
        OrchTaskStatus.FAILED,
        OrchTaskStatus.SKIPPED,
        OrchTaskStatus.CANCELLED,
        OrchTaskStatus.TIMED_OUT,
    }


def _priority_rank(priority: str) -> int:
    return {"critical": 0, "high": 1, "normal": 2, "low": 3}.get(priority, 2)


async def default_runtime_runner(
    spec: TaskSpec,
    agent_id: Optional[UUID],
    child_budget: Budget,
) -> Dict[str, Any]:
    """Production runner wiring Model Router -> Agent Runtime -> Tool Runtime.

    Requires a registered model provider for the agent's model. Without
    provider credentials the task fails honestly with MODEL_UNAVAILABLE
    instead of fabricating output.
    """
    from openagent.runtime.agent_core import (
        AgentBudget,
        AgentCapabilities,
        AgentConfig,
        AgentLoop,
        AgentLoopContext,
        model_provider_registry,
    )
    from openagent.runtime.engine import ExpressionEngine, ConditionEngine

    _ = ExpressionEngine, ConditionEngine
    # Resolve model: caller may override via task input; default to registry default.
    model = "gpt-4"
    if isinstance(spec.input, dict) and spec.input.get("model"):
        model = str(spec.input["model"])
    provider = model_provider_registry.get_for_model(model)
    if provider is None:
        return {"status": "failed", "error": f"MODEL_UNAVAILABLE: no provider for {model}",
                "error_code": "MODEL_UNAVAILABLE"}
    config = AgentConfig(
        name=spec.title,
        instructions=spec.instructions or spec.title,
        model=model,
        budget=AgentBudget(
            max_steps=min(child_budget.max_total_steps, 10),
            max_tool_calls=min(child_budget.max_tool_calls, 20),
            max_duration_seconds=min(child_budget.max_execution_time_seconds, spec.timeout_seconds),
        ),
        capabilities=AgentCapabilities(),
    )
    context = AgentLoopContext(
        execution_id=f"orch_{spec.external_task_id}_{uuid.uuid4().hex[:8]}",
        agent_id=str(agent_id) if agent_id else "unassigned",
        agent_version_id="default",
        organization_id="orchestration",
        config=config,
        input=dict(spec.input or {}),
        max_steps=config.budget.max_steps,
        budget=config.budget,
    )
    loop = AgentLoop(
        context=context,
        model_provider=provider,
        tool_executor=None,  # type: ignore[arg-type]
        expression_engine=ExpressionEngine(),
        condition_engine=ConditionEngine(ExpressionEngine()),
    )
    started = datetime.now(timezone.utc)
    try:
        result = await asyncio.wait_for(loop.run(), timeout=spec.timeout_seconds)
    except asyncio.TimeoutError:
        return {"status": "failed", "error": "agent execution timed out", "error_code": "TIMEOUT"}
    duration = (datetime.now(timezone.utc) - started).total_seconds()
    status = getattr(result, "status", None)
    status_value = getattr(status, "value", str(status))
    if status_value in ("succeeded", "completed"):
        return {
            "status": "succeeded",
            "output": dict(getattr(result, "output", {}) or {}),
            "usage": {
                "tokens": int(getattr(result, "total_tokens", 0) or 0),
                "cost": 0.0,
                "tool_calls": 0,
                "steps": int(getattr(result, "total_steps", 1) or 1),
            },
        }
    return {
        "status": "failed",
        "error": str(getattr(result, "error", "agent failed"))[:2000],
        "error_code": getattr(result, "error_code", "AGENT_FAILED"),
        "usage": {"tokens": 0, "cost": 0.0, "tool_calls": 0, "steps": 1},
    }
