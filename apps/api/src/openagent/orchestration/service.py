"""Orchestration service: persistence, lifecycle, budgets, audit.

All operations are organization-scoped. Cross-org access is denied at the
repository lookup level (get_by_id_with_org).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from openagent.db.models import Agent, AuditLog
from openagent.db.models.orchestration import (
    AgentHandoff,
    AgentMessage,
    OrchestrationEvent,
    OrchestrationRun,
    OrchestrationRunStatus,
    OrchestrationTask,
    OrchestrationTaskStatus,
)
from openagent.db.repositories.orchestration import (
    AgentHandoffRepository,
    AgentMessageRepository,
    OrchestrationBudgetLedgerRepository,
    OrchestrationEventRepository,
    OrchestrationRunRepository,
    OrchestrationTaskAttemptRepository,
    OrchestrationTaskDependencyRepository,
    OrchestrationTaskRepository,
)
from openagent.orchestration.assignment import AgentCandidate, assign_agent
from openagent.orchestration.config import OrchestrationOrgSettings
from openagent.orchestration.delegation import (
    DelegationRequest,
    build_handoff,
    evaluate_delegation,
)
from openagent.orchestration.events import publish_event, record_metric
from openagent.orchestration.executor import (
    AgentTaskRunner,
    ExecutorResult,
    OrchestrationExecutor,
    TaskSpec,
    default_runtime_runner,
)
from openagent.orchestration.security import sanitize_dict
from openagent.orchestration.supervisor import AgentSupervisor
from openagent.orchestration.types import (
    AgentMessageType,
    Budget,
    DependencyPolicy,
    OrchestrationStatus,
    OrchTaskStatus,
    TaskPlan,
    can_transition_run,
)
from openagent.orchestration.validator import validate_plan

logger = structlog.get_logger("orchestration.service")

class OrchestrationError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class OrchestrationService:
    def __init__(self, db: AsyncSession, settings: Optional[OrchestrationOrgSettings] = None):
        self.db = db
        self.settings = settings or OrchestrationOrgSettings()
        self.runs = OrchestrationRunRepository(db)
        self.tasks = OrchestrationTaskRepository(db)
        self.deps = OrchestrationTaskDependencyRepository(db)
        self.messages = AgentMessageRepository(db)
        self.handoffs = AgentHandoffRepository(db)
        self.attempts = OrchestrationTaskAttemptRepository(db)
        self.ledgers = OrchestrationBudgetLedgerRepository(db)
        self.events = OrchestrationEventRepository(db)

    # -- runs -----------------------------------------------------------
    async def create_run(
        self,
        *,
        organization_id: UUID,
        objective: str,
        budget: Optional[Budget] = None,
        root_agent_id: Optional[UUID] = None,
        team_id: Optional[UUID] = None,
        created_by: Optional[UUID] = None,
        idempotency_key: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> OrchestrationRun:
        if not objective or not objective.strip():
            raise OrchestrationError("EMPTY_OBJECTIVE", "objective must not be empty")
        if idempotency_key:
            existing = await self.runs.get_by_idempotency_key(organization_id, idempotency_key)
            if existing:
                return existing
        limits = budget or self.settings.default_budget
        if root_agent_id:
            agent = await self._require_agent(organization_id, root_agent_id)
            _ = agent
        run = await self.runs.create(
            organization_id=organization_id,
            objective=objective.strip(),
            status=OrchestrationRunStatus.CREATED,
            root_agent_id=root_agent_id,
            team_id=team_id,
            created_by=created_by,
            budget=_budget_to_dict(limits),
            usage={"tokens": 0, "cost": 0.0, "tool_calls": 0, "steps": 0},
            idempotency_key=idempotency_key,
            run_metadata=sanitize_dict(dict(metadata or {})),
        )
        await self.ledgers.create(
            organization_id=organization_id,
            orchestration_run_id=run.id,
            limits=_budget_to_dict(limits),
        )
        await self._record_event(run, "ORCHESTRATION_CREATED", None, None, {"objective": run.objective})
        await publish_event(
            self.db, event_type="ORCHESTRATION_CREATED", organization_id=organization_id,
            aggregate_id=run.id, payload={"objective": run.objective},
        )
        await self._audit(organization_id, created_by, "orchestration.create", "orchestration_run", run.id)
        await self.db.commit()
        record_metric("orchestrations_total")
        return run

    async def get_run(self, organization_id: UUID, run_id: UUID) -> OrchestrationRun:
        run = await self.runs.get_by_id_with_org(run_id, organization_id)
        if run is None:
            raise OrchestrationError("NOT_FOUND", "orchestration run not found")
        return run

    async def plan_run(
        self, organization_id: UUID, run_id: UUID, plan: TaskPlan
    ) -> List[OrchestrationTask]:
        run = await self.get_run(organization_id, run_id)
        self._require_transition(run.status, OrchestrationRunStatus.PLANNING,
                                 allowed_from=(OrchestrationRunStatus.CREATED,))
        known_agents = await self._org_agent_ids(organization_id)
        result = validate_plan(
            plan,
            max_tasks=self.settings.max_tasks_per_run,
            max_depth=12,
            max_delegation_depth=self.settings.max_delegation_depth,
            known_agent_ids=known_agents if _plan_has_assignments(plan) else None,
        )
        if not result.valid:
            run.status = OrchestrationRunStatus.FAILED
            run.error = "; ".join(f"{e.code}: {e.message}" for e in result.errors[:5])
            await self._record_event(run, "PLAN_REJECTED", None, None,
                                     {"errors": [e.code for e in result.errors]})
            await self.db.commit()
            raise OrchestrationError(
                "INVALID_PLAN", "; ".join(f"{e.code}: {e.message}" for e in result.errors[:8])
            )
        run.status = OrchestrationRunStatus.PLANNING
        await self.db.flush()
        # Persist tasks
        created: List[OrchestrationTask] = []
        ext_to_row: Dict[str, OrchestrationTask] = {}
        depth_map = _compute_depths(plan)
        for item in plan.tasks:
            assigned = None
            if item.assigned_agent_id:
                try:
                    assigned = UUID(item.assigned_agent_id)
                except ValueError:
                    assigned = None
            row = await self.tasks.create(
                organization_id=organization_id,
                orchestration_run_id=run.id,
                parent_task_id=None,  # resolved second pass
                assigned_agent_id=assigned,
                external_task_id=item.task_id,
                title=item.title[:500],
                description=item.description or "",
                instructions=item.instructions or "",
                status=OrchestrationTaskStatus.CREATED,
                priority=item.priority.value,
                dependency_policy=item.dependency_policy.value,
                required_capabilities=list(item.required_capabilities or []),
                required_permissions=list(item.required_permissions or []),
                risk_level=item.risk_level.value,
                requires_approval=bool(item.requires_approval),
                task_input=sanitize_dict(dict(item.input or {})),
                retry_count=0,
                max_retries=item.max_retries,
                retry_strategy=item.retry_strategy.value,
                timeout_seconds=item.timeout_seconds,
                depth=depth_map.get(item.task_id, 1),
                aggregation_strategy=item.aggregation_strategy.value if item.aggregation_strategy else None,
                task_metadata=sanitize_dict(dict(item.metadata or {})),
            )
            created.append(row)
            ext_to_row[item.task_id] = row
            await self._record_event(run, "TASK_CREATED", row.id, assigned, {"title": row.title})
        # Parents + dependencies
        for item in plan.tasks:
            row = ext_to_row[item.task_id]
            if item.parent_task_id and item.parent_task_id in ext_to_row:
                row.parent_task_id = ext_to_row[item.parent_task_id].id
            for dep_ext in item.dependencies or []:
                if dep_ext in ext_to_row:
                    await self.deps.create(
                        organization_id=organization_id,
                        orchestration_run_id=run.id,
                        task_id=row.id,
                        depends_on_task_id=ext_to_row[dep_ext].id,
                    )
        # Mark initially-ready tasks
        dep_map = await self._dependency_map(run.id)
        for row in created:
            if not dep_map.get(row.id):
                row.status = OrchestrationTaskStatus.READY
                await self._record_event(run, "TASK_READY", row.id, row.assigned_agent_id, {})
        run.status = OrchestrationRunStatus.READY
        await self._record_event(run, "PLAN_CREATED", None, None, {"tasks": len(created)})
        await self.db.commit()
        return created

    async def transition_run(
        self, organization_id: UUID, run_id: UUID, to: OrchestrationRunStatus,
        *, actor: Optional[UUID] = None,
    ) -> OrchestrationRun:
        run = await self.get_run(organization_id, run_id)
        self._require_transition(run.status, to)
        run.status = to
        now = datetime.now(timezone.utc)
        if to == OrchestrationRunStatus.RUNNING and run.started_at is None:
            run.started_at = now
        if to in (OrchestrationRunStatus.SUCCEEDED, OrchestrationRunStatus.PARTIALLY_SUCCEEDED,
                  OrchestrationRunStatus.FAILED, OrchestrationRunStatus.CANCELLED,
                  OrchestrationRunStatus.TIMED_OUT):
            run.completed_at = now
        name = {
            OrchestrationRunStatus.PAUSED: "ORCHESTRATION_PAUSED",
            OrchestrationRunStatus.CANCELLED: "ORCHESTRATION_CANCELLED",
            OrchestrationRunStatus.RUNNING: "ORCHESTRATION_RESUMED",
        }.get(to, "STATUS_UPDATE")
        await self._record_event(run, name, None, None, {"to": to.value})
        await self._audit(organization_id, actor, f"orchestration.{to.value}", "orchestration_run", run.id)
        await self.db.commit()
        return run

    async def execute_run(
        self,
        organization_id: UUID,
        run_id: UUID,
        *,
        runner: Optional[AgentTaskRunner] = None,
        max_parallel: Optional[int] = None,
    ) -> ExecutorResult:
        run = await self.get_run(organization_id, run_id)
        if run.status == OrchestrationRunStatus.READY:
            run.status = OrchestrationRunStatus.RUNNING
            run.started_at = run.started_at or datetime.now(timezone.utc)
            await self.db.flush()
        if run.status == OrchestrationRunStatus.PAUSED:
            raise OrchestrationError("PAUSED", "run is paused; resume before executing")
        if run.status not in (OrchestrationRunStatus.RUNNING, OrchestrationRunStatus.WAITING):
            raise OrchestrationError("INVALID_STATE", f"cannot execute run in status {run.status.value}")

        rows = await self.tasks.list_by_run(run.id, limit=self.settings.max_tasks_per_run + 10)
        if not rows:
            raise OrchestrationError("EMPTY_PLAN", "run has no tasks; plan first")
        dep_rows = await self.deps.list_by_run(run.id)
        id_to_ext = {r.id: r.external_task_id for r in rows}
        deps_by_task: Dict[UUID, List[str]] = {}
        for d in dep_rows:
            deps_by_task.setdefault(d.task_id, []).append(
                id_to_ext.get(d.depends_on_task_id, str(d.depends_on_task_id))
            )
        specs = [
            TaskSpec(
                id=r.id, external_task_id=r.external_task_id, title=r.title,
                instructions=r.instructions, input=dict(r.task_input or {}),
                required_capabilities=list(r.required_capabilities or []),
                priority=r.priority, dependency_policy=DependencyPolicy(r.dependency_policy),
                dependencies=deps_by_task.get(r.id, []),
                assigned_agent_id=r.assigned_agent_id,
                timeout_seconds=r.timeout_seconds, max_retries=r.max_retries,
                retry_strategy=r.retry_strategy, risk_level=r.risk_level, depth=r.depth,
                requires_approval=bool(r.requires_approval),
            )
            for r in rows
        ]
        # Auto-assign unassigned tasks deterministically.
        await self._auto_assign(run, rows)
        for s, r in zip(specs, rows):
            s.assigned_agent_id = r.assigned_agent_id

        # MP19: tasks requiring approval get a real persisted approval request
        # so humans can review them in the Approval Center. The executor only
        # runs such tasks once their persisted approval exists (no fabricated
        # approvals: `approved` sets must derive from approval records).
        # Dedupe against existing PENDING approvals so resume/retry never
        # spams duplicate requests.
        try:
            from openagent.approvals.integrations import (
                existing_pending as _existing_pending,
                park_for_approval as _park,
            )
            for s in specs:
                if not s.requires_approval:
                    continue
                dup = await _existing_pending(
                    self.db, organization_id=organization_id,
                    target_type="orchestration_task", target_id=s.external_task_id)
                if dup is None:
                    await _park(
                        self.db, organization_id=organization_id,
                        action_type="orchestration.task",
                        action_category="WRITE",
                        target_type="orchestration_task",
                        target_id=s.external_task_id,
                        params={"task": s.external_task_id, "title": s.title},
                        environment="development",
                        impact_summary=f"Orchestration task '{s.title}' requires approval",
                        requester_type="agent",
                        requester_id=s.assigned_agent_id,
                        task_id=s.external_task_id)
        except Exception as exc:  # pragma: no cover - approvals never break runs
            logger.warning("orchestration approval parking skipped", error=str(exc))

        ledger = await self.ledgers.get_by_run(run.id)
        limits_raw = dict(ledger.limits) if ledger and ledger.limits else (run.budget or {})
        budget = _dict_to_budget(limits_raw)

        async def should_stop() -> bool:
            await self.db.refresh(run)
            return run.status in (OrchestrationRunStatus.CANCELLED, OrchestrationRunStatus.PAUSED)

        async def heartbeat(task_id: UUID) -> None:
            row = await self.tasks.get_by_id(task_id)
            if row is not None:
                row.last_heartbeat_at = datetime.now(timezone.utc)
                row.lease_owner = "orchestrator"
                await self.db.flush()

        async def on_event(event_type: str, spec: TaskSpec, payload: Dict[str, Any]) -> None:
            await self._record_event(run, event_type, spec.id, spec.assigned_agent_id, payload)
            if event_type in ("TASK_STARTED", "TASK_COMPLETED", "TASK_FAILED"):
                db_status = {
                    "TASK_STARTED": OrchestrationTaskStatus.RUNNING,
                    "TASK_COMPLETED": OrchestrationTaskStatus.SUCCEEDED,
                    "TASK_FAILED": OrchestrationTaskStatus.FAILED,
                }[event_type]
                row = await self.tasks.get_by_id(spec.id)
                if row is not None:
                    row.status = db_status
                    now = datetime.now(timezone.utc)
                    if db_status == OrchestrationTaskStatus.RUNNING and row.started_at is None:
                        row.started_at = now
                    if db_status in (OrchestrationTaskStatus.SUCCEEDED, OrchestrationTaskStatus.FAILED):
                        row.completed_at = now
                        if db_status == OrchestrationTaskStatus.SUCCEEDED:
                            row.output = payload.get("output", row.output)
                        else:
                            row.error = str(payload.get("error", "failed"))[:4000]
                    message = AgentMessage(
                        organization_id=organization_id,
                        orchestration_run_id=run.id,
                        sender_agent_id=row.assigned_agent_id,
                        recipient_agent_id=None,
                        task_id=row.id,
                        message_type=_event_to_message(event_type),
                        payload=_cap_message_payload(dict(payload or {})),
                    )
                    self.db.add(message)
                    await self.db.flush()

        executor = OrchestrationExecutor(
            runner or default_runtime_runner,
            supervisor=AgentSupervisor(),
            max_parallel_tasks=max_parallel or self.settings.max_parallel_agents,
            heartbeat_callback=heartbeat,
            event_callback=on_event,
            should_stop=should_stop,
        )
        result = await executor.run(
            tasks=specs,
            budget=budget,
            initial={r.external_task_id: _db_task_to_domain(r.status) for r in rows},
            initial_outputs={
                r.external_task_id: dict(r.output or {})
                for r in rows
                if r.output and r.status == OrchestrationTaskStatus.SUCCEEDED
            },
        )
        # Persist final states + outputs
        rows = await self.tasks.list_by_run(run.id, limit=self.settings.max_tasks_per_run + 10)
        # Reconcile in-memory executor statuses by re-reading events is complex;
        # instead mark READY-but-unexecuted tasks cancelled on cancel, and collect outputs.
        if result.status == "succeeded":
            run.status = OrchestrationRunStatus.SUCCEEDED
            record_metric("orchestrations_success_total")
        elif result.status == "partially_succeeded":
            run.status = OrchestrationRunStatus.PARTIALLY_SUCCEEDED
            record_metric("orchestrations_success_total")
        elif result.status == "paused":
            run.status = OrchestrationRunStatus.PAUSED
        elif result.status == "waiting":
            run.status = OrchestrationRunStatus.WAITING
        else:
            run.status = OrchestrationRunStatus.FAILED
            run.error = (result.error or "execution failed")[:4000]
            record_metric("orchestrations_failed_total")
        run.final_result = sanitize_dict(dict(result.final_result or {}))
        run.completed_at = datetime.now(timezone.utc) if run.status not in (
            OrchestrationRunStatus.RUNNING, OrchestrationRunStatus.WAITING,
            OrchestrationRunStatus.PAUSED) else None
        await self._record_event(run, "ORCHESTRATION_COMPLETED", None, None,
                                 {"status": run.status.value, "result": run.final_result})
        await self._audit(organization_id, None, f"orchestration.{run.status.value}",
                          "orchestration_run", run.id)
        await self.db.commit()
        return result

    # -- delegation / handoff / reassignment -----------------------------
    async def delegate_task(
        self,
        organization_id: UUID,
        run_id: UUID,
        task_id: UUID,
        *,
        parent_agent_id: UUID,
        target_agent_id: UUID,
        actor: Optional[UUID] = None,
    ) -> OrchestrationTask:
        run = await self.get_run(organization_id, run_id)
        task = await self.tasks.get_by_id_with_org(task_id, organization_id)
        if task is None or task.orchestration_run_id != run.id:
            raise OrchestrationError("NOT_FOUND", "task not found in run")
        if not self.settings.allow_agent_delegation:
            raise OrchestrationError("DELEGATION_DISABLED", "delegation is disabled for this organization")
        if parent_agent_id == target_agent_id:
            raise OrchestrationError("SELF_DELEGATION", "self-delegation is not allowed")
        parent = await self._require_agent(organization_id, parent_agent_id)
        target = await self._require_agent(organization_id, target_agent_id)
        _ = parent, target
        if task.depth + 1 > self.settings.max_delegation_depth:
            raise OrchestrationError("DELEGATION_TOO_DEEP", "max delegation depth exceeded")
        decision = evaluate_delegation(
            DelegationRequest(
                parent_agent_id=str(parent_agent_id),
                target_agent_id=str(target_agent_id),
                task_id=str(task_id),
                depth=task.depth,
                max_depth=self.settings.max_delegation_depth,
            )
        )
        if not decision.allowed:
            raise OrchestrationError("DELEGATION_DENIED", "; ".join(decision.reasons))
        task.assigned_agent_id = target_agent_id
        task.depth = task.depth + 1
        if task.status == OrchestrationTaskStatus.FAILED:
            task.status = OrchestrationTaskStatus.READY
            task.retry_count = task.retry_count + 1
        await self._record_event(run, "DELEGATION_CREATED", task.id, target_agent_id,
                                 {"from": str(parent_agent_id)})
        await self._audit(organization_id, actor, "orchestration.delegate", "orchestration_task", task.id)
        await self.db.commit()
        record_metric("delegations_total")
        return task

    async def handoff_task(
        self,
        organization_id: UUID,
        run_id: UUID,
        task_id: UUID,
        *,
        from_agent_id: Optional[UUID],
        to_agent_id: Optional[UUID],
        package: Dict[str, Any],
        actor: Optional[UUID] = None,
    ) -> AgentHandoff:
        run = await self.get_run(organization_id, run_id)
        task = await self.tasks.get_by_id_with_org(task_id, organization_id)
        if task is None or task.orchestration_run_id != run.id:
            raise OrchestrationError("NOT_FOUND", "task not found in run")
        built = build_handoff(
            task_id=str(task.id),
            objective=run.objective,
            completed_work=dict(package.get("completed_work", {}) or {}),
            artifacts=list(package.get("artifacts", []) or []),
            relevant_context=dict(package.get("relevant_context", {}) or {}),
            constraints=list(package.get("constraints", []) or []),
            warnings=list(package.get("warnings", []) or []),
            expected_next_action=str(package.get("expected_next_action", "")),
        )
        handoff = await self.handoffs.create(
            organization_id=organization_id,
            orchestration_run_id=run.id,
            task_id=task.id,
            from_agent_id=from_agent_id,
            to_agent_id=to_agent_id,
            package={
                "objective": built.objective,
                "completed_work": built.completed_work,
                "artifacts": built.artifacts,
                "relevant_context": built.relevant_context,
                "constraints": built.constraints,
                "warnings": built.warnings,
                "expected_next_action": built.expected_next_action,
            },
            status="completed",
        )
        if to_agent_id:
            task.assigned_agent_id = to_agent_id
        await self._record_event(run, "HANDOFF_COMPLETED", task.id, to_agent_id,
                                 {"from": str(from_agent_id) if from_agent_id else None})
        await self._audit(organization_id, actor, "orchestration.handoff", "orchestration_task", task.id)
        await self.db.commit()
        record_metric("handoffs_total")
        return handoff

    async def retry_task(
        self, organization_id: UUID, run_id: UUID, task_id: UUID,
        *, actor: Optional[UUID] = None,
    ) -> OrchestrationTask:
        run = await self.get_run(organization_id, run_id)
        task = await self.tasks.get_by_id_with_org(task_id, organization_id)
        if task is None or task.orchestration_run_id != run.id:
            raise OrchestrationError("NOT_FOUND", "task not found in run")
        if task.retry_count >= task.max_retries:
            raise OrchestrationError("RETRIES_EXHAUSTED", "max retries exceeded")
        if task.status not in (OrchestrationTaskStatus.FAILED, OrchestrationTaskStatus.TIMED_OUT,
                               OrchestrationTaskStatus.CANCELLED):
            raise OrchestrationError("INVALID_STATE", "only failed/timed-out tasks can be retried")
        task.retry_count += 1
        task.status = OrchestrationTaskStatus.READY
        task.error = None
        if run.status in (OrchestrationRunStatus.FAILED, OrchestrationRunStatus.PARTIALLY_SUCCEEDED,
                          OrchestrationRunStatus.SUCCEEDED):
            run.status = OrchestrationRunStatus.READY
        await self.attempts.create(
            organization_id=organization_id, orchestration_run_id=run.id, task_id=task.id,
            agent_id=task.assigned_agent_id, agent_run_id=task.agent_run_id,
            attempt_number=task.retry_count, status="retried", error=task.error,
        )
        await self._record_event(run, "TASK_REASSIGNED", task.id, task.assigned_agent_id,
                                 {"reason": "retry"})
        await self._audit(organization_id, actor, "orchestration.retry", "orchestration_task", task.id)
        await self.db.commit()
        return task

    async def reassign_task(
        self, organization_id: UUID, run_id: UUID, task_id: UUID, *,
        agent_id: UUID, actor: Optional[UUID] = None,
    ) -> OrchestrationTask:
        run = await self.get_run(organization_id, run_id)
        task = await self.tasks.get_by_id_with_org(task_id, organization_id)
        if task is None or task.orchestration_run_id != run.id:
            raise OrchestrationError("NOT_FOUND", "task not found in run")
        agent = await self._require_agent(organization_id, agent_id)
        _ = agent
        previous = task.assigned_agent_id
        task.assigned_agent_id = agent_id
        if task.status in (OrchestrationTaskStatus.FAILED, OrchestrationTaskStatus.TIMED_OUT):
            task.status = OrchestrationTaskStatus.READY
        await self.attempts.create(
            organization_id=organization_id, orchestration_run_id=run.id, task_id=task.id,
            agent_id=agent_id, agent_run_id=None, attempt_number=task.retry_count + 1,
            status="reassigned", error=None,
        )
        await self._record_event(run, "TASK_REASSIGNED", task.id, agent_id,
                                 {"previous": str(previous) if previous else None})
        await self._audit(organization_id, actor, "orchestration.reassign", "orchestration_task", task.id)
        await self.db.commit()
        return task

    # -- internals ------------------------------------------------------
    async def _require_agent(self, organization_id: UUID, agent_id: UUID) -> Agent:
        result = await self.db.execute(
            select(Agent).where(Agent.id == agent_id, Agent.organization_id == organization_id)
        )
        agent = result.scalar_one_or_none()
        if agent is None:
            raise OrchestrationError("AGENT_NOT_FOUND", "agent not found in organization")
        return agent

    async def _org_agent_ids(self, organization_id: UUID) -> set[str]:
        result = await self.db.execute(
            select(Agent.id).where(Agent.organization_id == organization_id)
        )
        return {str(row[0]) for row in result.all()}

    async def _auto_assign(self, run: OrchestrationRun, rows: List[OrchestrationTask]) -> None:
        result = await self.db.execute(
            select(Agent).where(Agent.organization_id == run.organization_id)
        )
        agents = list(result.scalars().all())
        if not agents:
            return
        # Workload: count active tasks per agent in this run.
        load: Dict[str, int] = {}
        for r in rows:
            if r.assigned_agent_id and r.status not in (
                OrchestrationTaskStatus.SUCCEEDED, OrchestrationTaskStatus.FAILED,
                OrchestrationTaskStatus.CANCELLED):
                load[str(r.assigned_agent_id)] = load.get(str(r.assigned_agent_id), 0) + 1
        for row in rows:
            if row.assigned_agent_id:
                continue
            candidates = [
                AgentCandidate(
                    agent_id=str(a.id),
                    capabilities=_advertised_capabilities(a),
                    active_tasks=load.get(str(a.id), 0),
                    healthy=True,
                )
                for a in agents
            ]
            decision = assign_agent(
                required_capabilities=list(row.required_capabilities or []),
                candidates=candidates,
            )
            if decision.agent_id:
                row.assigned_agent_id = UUID(decision.agent_id)
                row.status = OrchestrationTaskStatus.ASSIGNED
                load[decision.agent_id] = load.get(decision.agent_id, 0) + 1
                await self._record_event(
                    run, "TASK_ASSIGNED", row.id, row.assigned_agent_id,
                    {"reasons": decision.reasons},
                )
        await self.db.flush()

    async def _dependency_map(self, run_id: UUID) -> Dict[UUID, List[UUID]]:
        rows = await self.deps.list_by_run(run_id)
        grouped: Dict[UUID, List[UUID]] = {}
        for d in rows:
            grouped.setdefault(d.task_id, []).append(d.depends_on_task_id)
        return grouped

    async def _record_event(
        self, run: OrchestrationRun, event_type: str,
        task_id: Optional[UUID], agent_id: Optional[UUID], payload: Dict[str, Any],
    ) -> None:
        import uuid as _uuid

        self.db.add(
            OrchestrationEvent(
                organization_id=run.organization_id,
                orchestration_run_id=run.id,
                task_id=task_id,
                agent_id=agent_id,
                event_type=event_type,
                payload=sanitize_dict(dict(payload or {})),
                trace_id=_uuid.uuid4().hex,
                span_id=_uuid.uuid4().hex[:16],
            )
        )
        await self.db.flush()

    async def _audit(
        self, organization_id: UUID, actor: Optional[UUID],
        action: str, resource_type: str, resource_id: Optional[UUID],
    ) -> None:
        self.db.add(
            AuditLog(
                organization_id=organization_id,
                actor_user_id=actor,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
            )
        )
        await self.db.flush()

    def _require_transition(
        self, current: OrchestrationRunStatus, target: OrchestrationRunStatus,
        *, allowed_from: Optional[tuple[OrchestrationRunStatus, ...]] = None,
    ) -> None:
        current_domain = _to_domain_run(current)
        target_domain = _to_domain_run(target)
        if allowed_from is not None and current not in allowed_from:
            raise OrchestrationError(
                "INVALID_STATE", f"cannot transition from {current.value} to {target.value}"
            )
        if not can_transition_run(current_domain, target_domain):
            raise OrchestrationError(
                "INVALID_TRANSITION", f"cannot transition from {current.value} to {target.value}"
            )


def _cap_message_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    from openagent.orchestration.security import cap_output

    cleaned = sanitize_dict(payload)
    if "output" in cleaned and isinstance(cleaned["output"], dict):
        cleaned = dict(cleaned)
        cleaned["output"] = cap_output(cleaned["output"], 64 * 1024)
    return cleaned


def _event_to_message(event_type: str) -> str:
    mapping = {
        "TASK_STARTED": AgentMessageType.TASK_STARTED.value,
        "TASK_COMPLETED": AgentMessageType.TASK_COMPLETED.value,
        "TASK_FAILED": AgentMessageType.TASK_FAILED.value,
    }
    return mapping.get(event_type, AgentMessageType.STATUS_UPDATE.value)


def _budget_to_dict(budget: Budget) -> Dict[str, Any]:
    return {
        "max_total_steps": budget.max_total_steps,
        "max_total_tokens": budget.max_total_tokens,
        "max_total_cost": budget.max_total_cost,
        "max_execution_time_seconds": budget.max_execution_time_seconds,
        "max_tasks": budget.max_tasks,
        "max_agents": budget.max_agents,
        "max_delegation_depth": budget.max_delegation_depth,
        "max_tool_calls": budget.max_tool_calls,
        "max_parallel_tasks": budget.max_parallel_tasks,
    }


def _dict_to_budget(data: Dict[str, Any]) -> Budget:
    budget = Budget()
    for key in (
        "max_total_steps", "max_total_tokens", "max_total_cost",
        "max_execution_time_seconds", "max_tasks", "max_agents",
        "max_delegation_depth", "max_tool_calls", "max_parallel_tasks",
    ):
        if key in data:
            try:
                setattr(budget, key, data[key])
            except Exception:
                pass
    return budget


def _to_domain_run(status: OrchestrationRunStatus) -> OrchestrationStatus:
    return OrchestrationStatus(status.value)


def _db_task_to_domain(status: OrchestrationTaskStatus) -> OrchTaskStatus:
    return OrchTaskStatus(status.value)


def _plan_has_assignments(plan: TaskPlan) -> bool:
    return any(t.assigned_agent_id for t in plan.tasks)


def _compute_depths(plan: TaskPlan) -> Dict[str, int]:
    by_id = {t.task_id: t for t in plan.tasks}
    depths: Dict[str, int] = {}

    def depth(tid: str, seen: set[str]) -> int:
        if tid in depths:
            return depths[tid]
        if tid in seen:
            return 1
        seen.add(tid)
        parent = by_id.get(tid).parent_task_id if by_id.get(tid) else None
        depths[tid] = 1 if not parent or parent not in by_id else depth(parent, seen) + 1
        return depths[tid]

    for t in plan.tasks:
        depth(t.task_id, set())
    return depths


def _advertised_capabilities(agent: Agent) -> List[str]:
    meta = getattr(agent, "metadata", None)
    if isinstance(meta, dict):
        caps = meta.get("capabilities") or meta.get("advertised_capabilities") or []
        if isinstance(caps, list):
            return [str(c) for c in caps]
    return []
