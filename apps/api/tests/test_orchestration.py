"""Unit tests for the multi-agent orchestration engine (no DB required)."""

from __future__ import annotations

import asyncio

import pytest

from openagent.orchestration.aggregation import (
    AgentResult,
    aggregate_results,
    detect_conflicts,
)
from openagent.orchestration.assignment import AgentCandidate, assign_agent
from openagent.orchestration.budgets import BudgetExceeded, BudgetState
from openagent.orchestration.delegation import (
    DelegationRequest,
    build_handoff,
    evaluate_delegation,
)
from openagent.orchestration.executor import OrchestrationExecutor, TaskSpec
from openagent.orchestration.planner import RuleBasedPlanner, parse_plan_dict
from openagent.orchestration.security import cap_output, sanitize_dict
from openagent.orchestration.supervisor import AgentSupervisor, TaskSnapshot
from openagent.orchestration.task_graph import (
    TaskNode,
    compute_ready,
    dependencies_satisfied,
    detect_deadlock,
    find_cycle,
    topological_order,
)
from openagent.orchestration.types import (
    AggregationStrategy,
    Budget,
    DependencyPolicy,
    OrchestrationStatus,
    OrchTaskStatus,
    PlannedTask,
    RiskLevel,
    TaskPlan,
    can_transition_run,
    can_transition_task,
)
from openagent.orchestration.validator import validate_plan


def _node(task_id: str, deps: list[str], status: OrchTaskStatus = OrchTaskStatus.CREATED,
           policy: DependencyPolicy = DependencyPolicy.ALL_SUCCESS) -> TaskNode:
    return TaskNode(task_id=task_id, dependencies=deps, status=status, dependency_policy=policy)


# -- task graph ------------------------------------------------------------


def test_find_cycle_detects_triangle():
    nodes = {
        "a": _node("a", ["b"]),
        "b": _node("b", ["c"]),
        "c": _node("c", ["a"]),
    }
    cycle = find_cycle(nodes)
    assert cycle is not None
    assert set(cycle) == {"a", "b", "c"}


def test_find_cycle_none_for_dag():
    nodes = {"a": _node("a", []), "b": _node("b", ["a"]), "c": _node("c", ["a"])}
    assert find_cycle(nodes) is None
    assert topological_order(nodes).index("a") == 0


def test_detect_deadlock_unknown_dependency():
    nodes = {"a": _node("a", ["missing"])}
    assert detect_deadlock(nodes) is not None


def test_dependency_policies():
    statuses = {"a": OrchTaskStatus.SUCCEEDED, "b": OrchTaskStatus.FAILED}
    assert dependencies_satisfied(_node("c", ["a", "b"]), statuses) is False
    assert dependencies_satisfied(
        _node("c", ["a", "b"], policy=DependencyPolicy.ANY_SUCCESS), statuses
    ) is True
    assert dependencies_satisfied(
        _node("c", ["a", "b"], policy=DependencyPolicy.IGNORE_FAILURE), statuses
    ) is True
    pending = {"a": OrchTaskStatus.SUCCEEDED, "b": OrchTaskStatus.RUNNING}
    assert dependencies_satisfied(_node("c", ["a", "b"]), pending) is False


def test_compute_ready_only_satisfied():
    nodes = {
        "a": _node("a", [], OrchTaskStatus.SUCCEEDED),
        "b": _node("b", ["a"]),
        "c": _node("c", ["b"]),
    }
    assert compute_ready(nodes) == ["b"]


# -- validator ---------------------------------------------------------------


def _valid_plan() -> TaskPlan:
    return TaskPlan(
        objective="Research and propose",
        tasks=[
            PlannedTask(task_id="research_1", title="Research market"),
            PlannedTask(task_id="spec", title="Write spec", dependencies=["research_1"]),
        ],
    )


def test_validate_plan_accepts_valid():
    assert validate_plan(_valid_plan()).valid


def test_validate_plan_rejects_cycle():
    plan = TaskPlan(
        objective="x",
        tasks=[
            PlannedTask(task_id="a", title="A", dependencies=["c"]),
            PlannedTask(task_id="b", title="B", dependencies=["a"]),
            PlannedTask(task_id="c", title="C", dependencies=["b"]),
        ],
    )
    result = validate_plan(plan)
    assert not result.valid
    assert any(e.code == "CYCLE_DETECTED" for e in result.errors)


def test_validate_plan_rejects_unknown_dependency_and_duplicates():
    plan = TaskPlan(
        objective="x",
        tasks=[
            PlannedTask(task_id="a", title="A", dependencies=["nope"]),
            PlannedTask(task_id="a", title="dup"),
        ],
    )
    result = validate_plan(plan)
    assert not result.valid
    codes = {e.code for e in result.errors}
    assert "UNKNOWN_DEPENDENCY" in codes
    assert "DUPLICATE_TASK_ID" in codes


def test_validate_plan_rejects_risk_downgrade_and_dangerous():
    plan = TaskPlan(
        objective="x",
        tasks=[
            PlannedTask(task_id="parent", title="Parent", risk_level=RiskLevel.HIGH),
            PlannedTask(
                task_id="child", title="Drop database now",
                parent_task_id="parent", risk_level=RiskLevel.LOW,
            ),
        ],
    )
    result = validate_plan(plan)
    assert not result.valid
    codes = {e.code for e in result.errors}
    assert "RISK_DOWNGRADE" in codes
    assert "DANGEROUS_ACTION" in codes


def test_validate_plan_rejects_too_many_tasks():
    plan = TaskPlan(
        objective="x",
        tasks=[PlannedTask(task_id=f"t{i}", title=f"T{i}") for i in range(5)],
    )
    result = validate_plan(plan, max_tasks=2)
    assert not result.valid
    assert any(e.code == "TOO_MANY_TASKS" for e in result.errors)


# -- budgets -----------------------------------------------------------------


def test_budget_consume_and_child_bounded():
    state = BudgetState(limits=Budget(max_total_tokens=100, max_total_cost=5.0,
                                      max_tool_calls=10, max_total_steps=10,
                                      max_tasks=5, max_agents=3))
    state.consume(tokens=40, cost=1.0)
    child = state.child_budget(fraction=1.0)
    assert child.max_total_tokens == 60
    with pytest.raises(BudgetExceeded):
        state.consume(tokens=1000)


def test_budget_warning():
    state = BudgetState(limits=Budget(max_total_tokens=100, max_total_cost=5.0))
    state.consume(tokens=85)
    assert state.warning_triggered()


# -- assignment ---------------------------------------------------------------


def test_assign_agent_explicit_and_capability():
    candidates = [
        AgentCandidate(agent_id="a1", capabilities=["research.web"], active_tasks=5),
        AgentCandidate(agent_id="a2", capabilities=["research.web"], active_tasks=0),
    ]
    result = assign_agent(required_capabilities=["research.web"], candidates=candidates)
    assert result.agent_id == "a2"
    explicit = assign_agent(required_capabilities=[], candidates=candidates, explicit_agent_id="a1")
    assert explicit.agent_id == "a1"
    missing = assign_agent(required_capabilities=["coding.rust"], candidates=candidates)
    assert missing.agent_id is None


def test_assign_agent_denied_and_unhealthy():
    candidates = [AgentCandidate(agent_id="a1", capabilities=["x"], allowed=False)]
    assert assign_agent(required_capabilities=["x"], candidates=candidates).agent_id is None


# -- delegation / handoff ------------------------------------------------------


def test_delegation_depth_and_self_denied():
    ok = evaluate_delegation(DelegationRequest(
        parent_agent_id="p", target_agent_id="t", task_id="task",
        depth=1, max_depth=4,
    ))
    assert ok.allowed
    deep = evaluate_delegation(DelegationRequest(
        parent_agent_id="p", target_agent_id="t", task_id="task",
        depth=4, max_depth=4,
    ))
    assert not deep.allowed
    self_dep = evaluate_delegation(DelegationRequest(
        parent_agent_id="p", target_agent_id="p", task_id="task",
        depth=1, max_depth=4,
    ))
    assert not self_dep.allowed


def test_handoff_redacts_private_context():
    package = build_handoff(
        task_id="t1", objective="obj",
        completed_work={"summary": "done"},
        relevant_context={"api_key": "secret-123", "notes": "public"},
        expected_next_action="review",
    )
    assert package.relevant_context["api_key"] == "[REDACTED]"
    assert package.relevant_context["notes"] == "public"


# -- lifecycle -----------------------------------------------------------------


def test_run_transitions():
    assert can_transition_run(OrchestrationStatus.CREATED, OrchestrationStatus.PLANNING)
    assert not can_transition_run(OrchestrationStatus.SUCCEEDED, OrchestrationStatus.RUNNING)
    assert can_transition_task(OrchTaskStatus.CREATED, OrchTaskStatus.READY)
    assert not can_transition_task(OrchTaskStatus.SUCCEEDED, OrchTaskStatus.RUNNING)


# -- supervisor -----------------------------------------------------------------


def test_supervisor_retry_then_reassign():
    sup = AgentSupervisor()
    snap = TaskSnapshot(task_id="t", status=OrchTaskStatus.FAILED, retry_count=0, max_retries=2)
    decisions = asyncio.run(sup.supervise([snap]))
    assert decisions[0].action == "retry"
    snap.retry_count = 2
    decisions = asyncio.run(sup.supervise([snap]))
    assert decisions[0].action == "reassign"


def test_supervisor_loop_detection():
    sup = AgentSupervisor()
    assert sup.detect_delegation_loop(["a", "b", "a"])
    assert not sup.detect_delegation_loop(["a", "b", "c"])


# -- aggregation -----------------------------------------------------------------


def test_conflict_detection_and_merge():
    results = [
        AgentResult(task_id="a", agent_id="a1", output={"estimate": "$20"}),
        AgentResult(task_id="b", agent_id="a2", output={"estimate": "$50"}),
    ]
    conflicts = detect_conflicts(results)
    assert len(conflicts) == 1
    assert conflicts[0].resolution_status == "open"
    merged = aggregate_results(AggregationStrategy.MERGE, results)
    assert "_conflicts" in merged


# -- security --------------------------------------------------------------------


def test_sanitize_and_cap():
    cleaned = sanitize_dict({"api_key": "abc", "nested": {"token": "xyz", "ok": 1}})
    assert cleaned["api_key"] == "[REDACTED]"
    assert cleaned["nested"]["token"] == "[REDACTED]"
    big = {"blob": "x" * (300 * 1024)}
    capped = cap_output(big, 1024)
    assert capped.get("_truncated") is True


# -- planner ----------------------------------------------------------------------


def test_rule_based_planner_produces_valid_plan():
    planner = RuleBasedPlanner()
    plan = asyncio.run(planner.create_plan("Research the AI automation market"))
    assert plan.tasks
    assert validate_plan(plan).valid


def test_parse_plan_dict():
    plan = parse_plan_dict(
        {"objective": "o", "tasks": [{"task_id": "a", "title": "A"}]}, objective="o"
    )
    assert len(plan.tasks) == 1


# -- executor ----------------------------------------------------------------------


def _spec(ext_id: str, deps: list[str], **kwargs) -> TaskSpec:
    import uuid as _uuid

    return TaskSpec(
        id=_uuid.uuid4(), external_task_id=ext_id, title=ext_id,
        instructions="", input={}, required_capabilities=[],
        priority="normal", dependency_policy=DependencyPolicy.ALL_SUCCESS,
        dependencies=deps, assigned_agent_id=None, timeout_seconds=60,
        max_retries=kwargs.get("max_retries", 0), retry_strategy="none",
        risk_level="low", depth=1,
    )


def test_executor_parallel_and_sequential():
    calls: list[str] = []

    async def runner(spec, agent_id, budget):
        calls.append(spec.external_task_id)
        return {"status": "succeeded", "output": {"value": spec.external_task_id},
                "usage": {"tokens": 10, "cost": 0.01, "tool_calls": 0, "steps": 1}}

    executor = OrchestrationExecutor(runner, max_parallel_tasks=5)
    tasks = [
        _spec("a", []),
        _spec("b", []),
        _spec("c", ["a", "b"]),
    ]
    result = asyncio.run(executor.run(tasks=tasks, budget=Budget()))
    assert result.status == "succeeded"
    assert set(calls) == {"a", "b", "c"}
    assert calls.index("c") > calls.index("a")
    assert result.final_result is not None


def test_executor_retry_and_partial_success():
    attempts: dict[str, int] = {}

    async def runner(spec, agent_id, budget):
        attempts[spec.external_task_id] = attempts.get(spec.external_task_id, 0) + 1
        if spec.external_task_id == "flaky" and attempts["flaky"] == 1:
            return {"status": "failed", "error": "boom"}
        return {"status": "succeeded", "output": {"ok": True},
                "usage": {"tokens": 1, "cost": 0.0, "tool_calls": 0, "steps": 1}}

    executor = OrchestrationExecutor(runner)
    flaky = _spec("flaky", [], max_retries=1)
    flaky.retry_strategy = "fixed"
    result = asyncio.run(executor.run(tasks=[flaky], budget=Budget()))
    assert result.status == "succeeded"
    assert attempts["flaky"] == 2


def test_executor_budget_exceeded_fails_honestly():
    async def runner(spec, agent_id, budget):
        return {"status": "succeeded", "output": {"ok": True},
                "usage": {"tokens": 10_000_000, "cost": 999.0, "tool_calls": 0, "steps": 1}}

    executor = OrchestrationExecutor(runner)
    result = asyncio.run(executor.run(tasks=[_spec("a", [])], budget=Budget()))
    assert result.status in ("failed", "partially_succeeded")


def test_executor_rejects_cycle():
    async def runner(spec, agent_id, budget):  # pragma: no cover
        return {"status": "succeeded", "output": {}}

    executor = OrchestrationExecutor(runner)
    result = asyncio.run(executor.run(
        tasks=[_spec("a", ["b"]), _spec("b", ["a"])], budget=Budget()))
    assert result.status == "failed"


def test_executor_approval_hook_waits():
    import uuid as _uuid

    async def runner(spec, agent_id, budget):  # pragma: no cover
        return {"status": "succeeded", "output": {}}

    gated = TaskSpec(
        id=_uuid.uuid4(), external_task_id="gated", title="gated",
        instructions="", input={}, required_capabilities=[],
        priority="normal", dependency_policy=DependencyPolicy.ALL_SUCCESS,
        dependencies=[], assigned_agent_id=None, timeout_seconds=60,
        max_retries=0, retry_strategy="none", risk_level="high", depth=1,
        requires_approval=True,
    )
    executor = OrchestrationExecutor(runner)
    waiting = asyncio.run(executor.run(tasks=[gated], budget=Budget()))
    assert waiting.status == "waiting"
    approved = asyncio.run(
        executor.run(tasks=[gated], budget=Budget(), approved={"gated"})
    )
    assert approved.status == "succeeded"
