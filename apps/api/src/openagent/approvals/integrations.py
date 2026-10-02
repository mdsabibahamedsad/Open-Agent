"""Runtime integration helpers (MP19).

Thin glue between the central guard (policy -> risk -> approval) and the
existing runtimes. Every helper is fail-safe: if approval persistence fails,
the action stays parked (never silently allowed).
"""

from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from openagent.approvals.engine import ApprovalEngine, ApprovalError, CreateRequest
from openagent.approvals.types import ActionContext, ApprovalKind, PolicyDecision

logger = structlog.get_logger("openagent.approvals.integrations")


async def load_org_policies(db: AsyncSession, organization_id: UUID) -> dict[str, list[dict]]:
    """Load active org/team/agent approval policies grouped by level."""
    try:
        from openagent.db.models.approval import ApprovalPolicy
        result = await db.execute(
            select(ApprovalPolicy).where(
                ApprovalPolicy.organization_id == organization_id,
                ApprovalPolicy.is_active.is_(True)))
        grouped: dict[str, list[dict]] = {}
        for policy in result.scalars().all():
            level = str(policy.level or "organization")
            grouped.setdefault(level, []).extend(list(policy.rules or []))
        return grouped
    except Exception as exc:  # pragma: no cover - policies optional pre-migration
        logger.warning("approval policy load skipped", error=str(exc))
        return {}


async def park_for_approval(
    db: AsyncSession, *, organization_id: UUID, action_type: str, action_category: str,
    target_type: str = "", target_id: str = "", target_reference: str = "",
    params: Optional[dict[str, Any]] = None, environment: str = "development",
    impact_summary: str = "", action_description: str = "",
    requester_type: str = "agent", requester_id: Optional[str] = None,
    agent_id: Optional[UUID] = None, agent_run_id: Optional[UUID] = None,
    workflow_id: Optional[UUID] = None, workflow_execution_id: Optional[UUID] = None,
    task_id: Optional[str] = None, risk: Any = None, evaluation: Any = None,
    approval_kind: ApprovalKind = ApprovalKind.SINGLE, required_approvals: int = 1,
    required_role: Optional[str] = None,
) -> Optional[Any]:
    """Persist an approval request. Returns None (stay parked) on failure."""
    try:
        engine = ApprovalEngine(db)
        approval = await engine.create_request(CreateRequest(
            organization_id=organization_id, action_type=action_type,
            action_category=(action_category or "WRITE").upper(),
            requested_action=action_type, requested_params=params or {},
            target_type=target_type, target_id=target_id,
            target_reference=target_reference, impact_summary=impact_summary,
            action_description=action_description or action_type,
            requester_type=requester_type, requester_id=requester_id,
            agent_id=agent_id, agent_run_id=agent_run_id, workflow_id=workflow_id,
            workflow_execution_id=workflow_execution_id, task_id=task_id,
            environment=environment, risk=risk, evaluation=evaluation,
            approval_kind=approval_kind, required_approvals=required_approvals,
            required_role=required_role))
        await db.flush()
        return approval
    except Exception as exc:
        logger.warning("park_for_approval failed; action stays parked", error=str(exc))
        return None


async def consume_approval(
    db: AsyncSession, *, approval_id: UUID, organization_id: UUID, action_type: str,
    action_category: str, target_type: str = "", target_id: str = "",
    params: Optional[dict[str, Any]] = None, environment: str = "development",
) -> tuple[bool, str]:
    """Verify a persisted approval covers this exact action and mark EXECUTING.

    Returns (True, "") or (False, reason). Never trusts client booleans.
    """
    try:
        await ApprovalEngine(db).begin_execution(
            approval_id, organization_id=organization_id, action_type=action_type,
            action_category=(action_category or "WRITE").upper(),
            target_type=target_type or "", target_id=target_id or "",
            params=params or {}, environment=environment)
        await db.flush()
        return True, ""
    except ApprovalError as exc:
        return False, f"{exc.code}: {exc}"
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("consume_approval failed closed", error=str(exc))
        return False, "APPROVAL_VERIFY_FAILED"


def tool_action_context(*, tool_name: str, tool_category: str = "",
                        risk_level: str = "LOW", trust_level: str = "ORGANIZATION",
                        tool_arguments: Optional[dict[str, Any]] = None,
                        organization_id: UUID, environment: str = "development",
                        mcp_server: str = "", mcp_trust: str = "ORGANIZATION",
                        ) -> ActionContext:
    """Build a server-side ActionContext for a tool invocation.

    The category comes from the platform taxonomy map — never from
    model-supplied tool descriptions.
    """
    from openagent.approvals.guard import action_context_for_tool
    ctx = action_context_for_tool(
        tool_name=tool_name, arguments=tool_arguments or {},
        organization_id=organization_id, environment=environment,
        tool_trust=trust_level, mcp_trust=mcp_trust, mcp_server=mcp_server)
    # Blend DB-registered risk/trust: DB risk can only escalate, never de-escalate.
    if (risk_level or "").upper() in ("HIGH", "CRITICAL") and \
            ctx.action_category in ("WRITE", "UPDATE", "READ", "MCP_ACTION"):
        order = {"READ": 0, "WRITE": 1, "UPDATE": 1, "MCP_ACTION": 1}
        _ = order  # category kept; risk engine re-derives from flags
        ctx.destructive = ctx.destructive or (risk_level.upper() == "CRITICAL")
        if risk_level.upper() == "CRITICAL":
            ctx.credential_usage = True
    if tool_category:
        ctx.target_reference = f"{tool_category}:{tool_name}"[:256]
    return ctx


def agent_tool_gate(*, tool_name: str, arguments: dict[str, Any],
                    organization_id: UUID, environment: str = "development",
                    ) -> dict[str, Any]:
    """Pure (DB-free) pre-execution gate for the agent tool loop.

    Returns {"allowed": True} or {"allowed": False, "waiting": {...}}.
    The durable approval is created by the service/API layer; the agent loop
    must pause with WAITING_FOR_APPROVAL and never treat it as success.
    """
    from openagent.approvals.guard import action_context_for_tool
    from openagent.approvals.policy import evaluate_policies
    from openagent.approvals.risk import evaluate_risk
    ctx = action_context_for_tool(tool_name=tool_name, arguments=arguments or {},
                                  organization_id=organization_id,
                                  environment=environment)
    risk = evaluate_risk(ctx)
    evaluation = evaluate_policies(ctx=ctx, risk=risk)
    if evaluation.decision == PolicyDecision.ALLOW:
        return {"allowed": True, "risk_level": risk.risk_level.value,
                "risk_score": risk.risk_score}
    if evaluation.decision == PolicyDecision.DENY:
        return {"allowed": False, "denied": True,
                "risk_level": risk.risk_level.value,
                "reasons": risk.reasons + evaluation.reasons,
                "message": "Action denied by guardrail policy"}
    return {"allowed": False, "waiting": True, "risk_level": risk.risk_level.value,
            "risk_score": risk.risk_score,
            "reasons": risk.reasons + evaluation.reasons,
            "policy_decision": evaluation.decision.value,
            "message": "Human approval required"}


async def existing_pending(db: AsyncSession, *, organization_id: UUID,
                           target_type: str, target_id: str) -> Optional[Any]:
    """Return an existing PENDING approval for the same target, if any.

    Used to avoid duplicate approval requests when a run is retried/resumed.
    Matching is done on the redacted payload (no secrets involved).
    """
    try:
        from openagent.db.models.approval import Approval, ApprovalStatus
        result = await db.execute(
            select(Approval).where(
                Approval.organization_id == organization_id,
                Approval.status == ApprovalStatus.PENDING))
        for approval in result.scalars().all():
            payload = approval.payload or {}
            if payload.get("target_type") == target_type \
                    and payload.get("target_id") == target_id:
                return approval
        return None
    except Exception:
        return None
