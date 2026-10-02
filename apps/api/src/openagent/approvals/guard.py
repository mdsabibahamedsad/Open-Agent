"""Central guard gate: AI decides -> policy -> risk -> approval -> execute.

Every runtime (tool, MCP, browser, code, sandbox, workflow, agent,
multi-agent) funnels high-risk actions through `evaluate_action`. The model
can only ever receive a structured WAITING_FOR_APPROVAL status; only the
ApprovalEngine (human decision persisted server-side) can release execution.
"""

from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from openagent.approvals.engine import ApprovalEngine, CreateRequest
from openagent.approvals.policy import evaluate_policies
from openagent.approvals.risk import evaluate_risk
from openagent.approvals.taxonomy import is_known_category
from openagent.approvals.types import (ActionContext, ApprovalKind, GuardResult,
                                        HumanBlockReason, PolicyDecision)

logger = structlog.get_logger("openagent.guard")

# Tool name -> (action_category, defaults). Unknown tools -> deny-by-default.
TOOL_ACTION_MAP: dict[str, str] = {
    "browser.navigate": "READ", "browser.extract": "READ",
    "browser.click": "BROWSER_EXTERNAL_ACTION", "browser.submit": "BROWSER_EXTERNAL_ACTION",
    "browser.purchase": "FINANCIAL_ACTION", "browser.publish": "PUBLISH_CONTENT",
    "browser.message": "SEND_MESSAGE", "browser.email": "SEND_EMAIL",
    "code.merge": "MERGE_CODE", "code.deploy": "DEPLOY", "code.commit": "CREATE_COMMIT",
    "code.push": "MODIFY_REPOSITORY", "code.pr": "CREATE_PULL_REQUEST",
    "sandbox.execute": "SANDBOX_EXECUTION", "sandbox.deploy": "DEPLOY",
    "mcp.invoke": "MCP_ACTION", "tool.invoke": "WRITE",
    "email.send": "SEND_EMAIL", "message.send": "SEND_MESSAGE",
    "payment.charge": "FINANCIAL_ACTION", "credential.create": "ACCESS_CREDENTIAL",
    "credential.rotate": "ACCESS_CREDENTIAL", "infra.apply": "INFRASTRUCTURE_ACTION",
    "config.update": "CHANGE_CONFIGURATION", "user.admin": "USER_ADMINISTRATION",
    "org.admin": "ORGANIZATION_ADMINISTRATION", "repo.delete": "DELETE",
    "db.delete": "DELETE", "cloud.delete": "DELETE",
}

BROWSER_HIGH_IMPACT = frozenset({
    "submit purchase", "publish post", "send external message", "delete account",
    "submit application", "change billing settings", "checkout", "payment",
    "purchase", "publish", "submit", "transfer",
})


def action_context_for_tool(*, tool_name: str, arguments: dict[str, Any],
                            organization_id: UUID, environment: str = "development",
                            agent_trust: str = "ORGANIZATION",
                            tool_trust: str = "ORGANIZATION",
                            mcp_trust: str = "ORGANIZATION",
                            mcp_server: str = "",
                            agent_id: str = "") -> ActionContext:
    lowered = tool_name.lower()
    category = TOOL_ACTION_MAP.get(lowered)
    untrusted_origin = False
    if category is None:
        # Prefix match (e.g. "browser.click@v1"), else deny-by-default bucket.
        category = next((cat for name, cat in TOOL_ACTION_MAP.items()
                         if lowered.startswith(name)), None)
        if category is None:
            category = "WRITE"
            untrusted_origin = True  # unknown tool: never elevated trust
    arg_text = str(arguments or {}).lower()
    destructive = any(w in arg_text for w in ("delete", "drop", "destroy", "terminate")) \
        or category == "DELETE"
    financial = category == "FINANCIAL_ACTION" or "purchase" in lowered or "pay" in lowered
    external = category in ("SEND_EMAIL", "SEND_MESSAGE", "PUBLISH_CONTENT",
                            "BROWSER_EXTERNAL_ACTION", "FINANCIAL_ACTION")
    credential = category == "ACCESS_CREDENTIAL"
    return ActionContext(
        action_type=tool_name, action_category=category,
        target_type="tool", target_id=tool_name,
        target_reference=str((arguments or {}).get("target", tool_name))[:256],
        environment=environment,
        params_summary={k: str(v)[:256] for k, v in (arguments or {}).items()},
        external_side_effect=external, financial_impact=financial,
        destructive=destructive, credential_usage=credential,
        network_access="sandbox" in lowered or "browser" in lowered or "http" in lowered,
        tenant_scope="organization", organization_id=str(organization_id),
        agent_trust=agent_trust, tool_trust=tool_trust, mcp_trust=mcp_trust,
        tool_name=tool_name, mcp_server=mcp_server, agent_id=agent_id,
        untrusted_origin=untrusted_origin)


def browser_action_blocked(action: str, page_text: str = "") -> Optional[str]:
    lowered = (action or "").lower()
    for pattern in BROWSER_HIGH_IMPACT:
        if pattern in lowered:
            return pattern
    return None


async def evaluate_action(*, db: AsyncSession, organization_id: UUID,
                          ctx: ActionContext,
                          requester_type: str = "agent",
                          requester_id: Optional[str] = None,
                          agent_id: Optional[UUID] = None,
                          agent_run_id: Optional[UUID] = None,
                          workflow_id: Optional[UUID] = None,
                          workflow_execution_id: Optional[UUID] = None,
                          task_id: Optional[str] = None,
                          team_id: Optional[UUID] = None,
                          action_description: str = "",
                          impact_summary: str = "",
                          requested_params: Optional[dict[str, Any]] = None,
                          policies_by_level: Optional[dict] = None,
                          ) -> GuardResult:
    """Policy -> risk -> approval-request-or-allow. Never executes anything."""
    from openagent.approvals.hashing import redact_params
    risk = evaluate_risk(ctx)
    evaluation = evaluate_policies(ctx=ctx, risk=risk, policies_by_level=policies_by_level)
    if evaluation.decision == PolicyDecision.ALLOW:
        return GuardResult(decision=evaluation.decision, risk=risk,
                           evaluation=evaluation, approval_required=False)
    if evaluation.decision == PolicyDecision.DENY:
        logger.warning("guard denied action", action=ctx.action_type,
                       reasons=evaluation.reasons)
        return GuardResult(decision=evaluation.decision, risk=risk,
                           evaluation=evaluation, approval_required=False)
    engine = ApprovalEngine(db)
    kind = (ApprovalKind.MULTI if evaluation.decision == PolicyDecision.REQUIRE_MULTI_APPROVAL
            else ApprovalKind.SINGLE)
    if evaluation.decision == PolicyDecision.REQUIRE_ESCALATION:
        kind = ApprovalKind.ORGANIZATION
    approval = await engine.create_request(CreateRequest(
        organization_id=organization_id, action_type=ctx.action_type,
        action_category=ctx.action_category, requested_action=ctx.action_type,
        requested_params=redact_params(requested_params or ctx.params_summary),
        target_type=ctx.target_type, target_id=ctx.target_id,
        target_reference=ctx.target_reference, impact_summary=impact_summary,
        action_description=action_description or ctx.action_type,
        requester_type=requester_type, requester_id=requester_id,
        agent_id=agent_id, agent_run_id=agent_run_id, workflow_id=workflow_id,
        workflow_execution_id=workflow_execution_id, task_id=task_id, team_id=team_id,
        environment=ctx.environment, risk=risk, evaluation=evaluation,
        approval_kind=kind, required_approvals=evaluation.required_approvals,
        required_role=evaluation.required_role), policies_by_level=policies_by_level)
    await db.flush()
    return GuardResult(decision=evaluation.decision, risk=risk, evaluation=evaluation,
                       approval_required=True, approval_id=approval.id)


def waiting_payload(*, approval_id: Any, reason: HumanBlockReason,
                    message: str = "", expires_at: Any = None) -> dict[str, Any]:
    return {"status": "WAITING_FOR_HUMAN" if reason != HumanBlockReason.APPROVAL_REQUIRED
            else "WAITING_FOR_APPROVAL",
            "approval_id": str(approval_id) if approval_id else None,
            "reason": reason.value, "message": message or "Human input required",
            "expires_at": str(expires_at) if expires_at else None}


def is_known_action_category(category: str) -> bool:
    return is_known_category(category)
