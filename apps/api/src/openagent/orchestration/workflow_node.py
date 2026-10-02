"""Workflow Engine node: AI Workforce (multi-agent orchestration).

Node configuration:
    objective | template | root_agent_id | planning_mode | max_agents |
    budget | timeout_seconds | execution_policy

Execution starts an orchestration run and returns WAITING with a resume
token (the orchestration run id); the workflow engine resumes the node
when the run reaches a terminal state. Crash-safe: resume token is the
persisted run id.
"""

from __future__ import annotations

from typing import Any, Dict, List
from uuid import UUID

from openagent.runtime.executors.base import (
    NodeExecutionContext,
    NodeExecutionResult,
    NodeExecutor,
)
from openagent.runtime.models import NodeRunStatus


class OrchestrationNodeExecutor(NodeExecutor):
    node_type = "orchestration"
    required_capabilities = ["agent_runtime"]
    supports_parallel = True
    default_timeout = 3600

    def get_timeout(self, node_config: Dict[str, Any]) -> int:
        timeout = node_config.get("timeout_seconds")
        if isinstance(timeout, (int, float)) and timeout > 0:
            return int(timeout)
        return self.default_timeout

    def validate_config(self, config: Dict[str, Any]) -> List[str]:
        from openagent.orchestration.templates import TEMPLATES

        errors: List[str] = []
        if not config.get("objective") and not config.get("template"):
            errors.append("orchestration node requires 'objective' or 'template'")
        if config.get("template") and config["template"] not in TEMPLATES:
            errors.append(f"unknown template: {config['template']}")
        return errors

    async def execute(
        self, node_config: Dict[str, Any], context: NodeExecutionContext
    ) -> NodeExecutionResult:
        from openagent.orchestration.config import OrchestrationOrgSettings
        from openagent.orchestration.planner import RuleBasedPlanner
        from openagent.orchestration.service import OrchestrationService
        from openagent.orchestration.templates import TEMPLATES
        from openagent.orchestration.types import Budget

        errors = self.validate_config(node_config)
        if errors:
            return NodeExecutionResult(
                status=NodeRunStatus.FAILED, error="; ".join(errors), error_code="INVALID_CONFIG"
            )
        resume_token = getattr(context, "resume_token", None)
        if resume_token:
            return await self._check_run(context, str(resume_token))

        from openagent.db.session import get_db

        organization_id = UUID(str(context.organization_id))
        db_gen = get_db()
        db = await db_gen.__anext__()
        try:
            service = OrchestrationService(db, OrchestrationOrgSettings())
            budget = _budget_from_config(node_config.get("budget", {}))
            root_agent = node_config.get("root_agent_id")
            run = await service.create_run(
                organization_id=organization_id,
                objective=str(node_config.get("objective") or node_config.get("template")),
                budget=budget,
                root_agent_id=UUID(str(root_agent)) if root_agent else None,
                metadata={"trigger": "workflow", "node_id": context.node_id},
            )
            template = node_config.get("template")
            if template in TEMPLATES:
                plan = TEMPLATES[template](run.objective)
            else:
                plan = await RuleBasedPlanner().create_plan(run.objective)
            try:
                await service.plan_run(organization_id, run.id, plan)
            except Exception as exc:  # noqa: BLE001
                return NodeExecutionResult(
                    status=NodeRunStatus.FAILED, error=str(exc)[:2000],
                    error_code="PLAN_REJECTED",
                )
            return NodeExecutionResult(
                status=NodeRunStatus.WAITING,
                outputs={"orchestration_run_id": str(run.id), "status": "running"},
                resume_token=str(run.id),
                metadata={"orchestration_run_id": str(run.id)},
            )
        finally:
            await db.close()

    async def _check_run(self, context: NodeExecutionContext, resume_token: str) -> NodeExecutionResult:
        from openagent.db.session import get_db
        from openagent.orchestration.config import OrchestrationOrgSettings
        from openagent.orchestration.service import OrchestrationService

        organization_id = UUID(str(context.organization_id))
        db_gen = get_db()
        db = await db_gen.__anext__()
        try:
            service = OrchestrationService(db, OrchestrationOrgSettings())
            try:
                run = await service.get_run(organization_id, UUID(resume_token))
            except Exception as exc:  # noqa: BLE001
                return NodeExecutionResult(
                    status=NodeRunStatus.FAILED, error=str(exc)[:2000],
                    error_code="RUN_NOT_FOUND",
                )
            status_value = run.status.value
            if status_value in ("succeeded", "partially_succeeded"):
                return NodeExecutionResult(
                    status=NodeRunStatus.SUCCEEDED,
                    outputs={"orchestration_run_id": str(run.id),
                             "result": run.final_result or {}},
                )
            if status_value in ("failed", "cancelled", "timed_out"):
                terminal = {
                    "failed": NodeRunStatus.FAILED,
                    "cancelled": NodeRunStatus.CANCELLED,
                    "timed_out": NodeRunStatus.TIMED_OUT,
                }
                return NodeExecutionResult(
                    status=terminal[status_value],
                    error=(run.error or "orchestration failed")[:2000],
                    error_code="ORCHESTRATION_FAILED",
                )
            return NodeExecutionResult(
                status=NodeRunStatus.WAITING,
                outputs={"orchestration_run_id": str(run.id), "status": status_value},
                resume_token=resume_token,
            )
        finally:
            await db.close()


def _budget_from_config(data: Dict[str, Any]) -> Budget:
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
