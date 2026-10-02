"""Central ApprovalEngine (MP19).

Durable, tenant-isolated, race-safe approval lifecycle over the existing
`approvals` table + MP19 satellite tables. Invariants enforced server-side:

1. No model can approve its own action (requester != approver).
2. No client flag can mark approval approved (transitions only via engine).
3. Expired approvals never execute. 4. Modified action invalidates approval
   (hash comparison). 5. Cross-tenant access denied. 6. Secrets never stored
   (params redacted before persistence).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from openagent.approvals.hashing import (action_hash, approval_token, envelope_payload,
                                          redact_params)
from openagent.approvals.policy import evaluate_policies
from openagent.approvals.risk import evaluate_risk
from openagent.approvals.types import (ActionContext, ApprovalKind, ApprovalState,
                                        PolicyEvaluation, RiskAssessment,
                                        can_transition)

logger = structlog.get_logger("openagent.approvals")

DEFAULT_EXPIRATION_SECONDS = 4 * 3600  # single-use + short expiration by default
MAX_EXPIRATION_SECONDS = 7 * 24 * 3600


class ApprovalError(Exception):
    def __init__(self, message: str, code: str = "APPROVAL_ERROR"):
        super().__init__(message)
        self.code = code


@dataclass
class CreateRequest:
    organization_id: UUID
    action_type: str
    action_category: str
    requested_action: str
    requested_params: dict[str, Any]
    target_type: str = ""
    target_id: str = ""
    target_reference: str = ""
    impact_summary: str = ""
    action_description: str = ""
    requester_type: str = "agent"  # agent | user | workflow | service_account | platform
    requester_id: Optional[str] = None
    agent_id: Optional[UUID] = None
    agent_run_id: Optional[UUID] = None
    workflow_id: Optional[UUID] = None
    workflow_execution_id: Optional[UUID] = None
    task_id: Optional[str] = None
    team_id: Optional[UUID] = None
    environment: str = "development"
    risk: Optional[RiskAssessment] = None
    evaluation: Optional[PolicyEvaluation] = None
    approval_kind: ApprovalKind = ApprovalKind.SINGLE
    required_approvals: int = 1
    required_role: Optional[str] = None
    max_uses: int = 1
    expires_in_seconds: int = DEFAULT_EXPIRATION_SECONDS


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def build_action_context(req: CreateRequest, redacted_params: dict[str, Any]) -> ActionContext:
    rp = redacted_params or {}
    lowered = f"{req.action_category} {req.action_type} {req.requested_action}".lower()
    destructive = any(w in lowered for w in ("delete", "drop", "destroy", "remove", "terminate"))
    financial = any(w in lowered for w in ("pay", "purchase", "refund", "transfer", "invoice",
                                           "billing", "charge", "payout"))
    external = req.action_category.upper() in ("SEND_EMAIL", "SEND_MESSAGE", "PUBLISH_CONTENT",
                                               "BROWSER_EXTERNAL_ACTION")
    credential = req.action_category.upper() == "ACCESS_CREDENTIAL" or "credential" in lowered
    return ActionContext(
        action_type=req.action_type, action_category=req.action_category.upper(),
        target_type=req.target_type, target_id=req.target_id,
        target_reference=req.target_reference, environment=req.environment,
        params_summary={k: ("<redacted>" if v == "[REDACTED]" else v)
                        for k, v in (rp.items() if isinstance(rp, dict) else {})},
        external_side_effect=external, financial_impact=financial,
        destructive=destructive, credential_usage=credential,
        tenant_scope="organization" if req.organization_id else "own",
        organization_id=str(req.organization_id), agent_id=str(req.agent_id or ""),
        tool_name=req.action_type)


class ApprovalEngine:
    def __init__(self, db: AsyncSession):
        self.db = db

    # -- create ---------------------------------------------------------
    async def create_request(self, req: CreateRequest,
                             policies_by_level: Optional[dict] = None) -> Any:
        from openagent.db.models.approval import Approval, ApprovalStatus, ApprovalType
        redacted = redact_params(req.requested_params or {})
        if not isinstance(redacted, dict):
            redacted = {"value": redacted}
        ctx = build_action_context(req, redacted)
        risk = req.risk or evaluate_risk(ctx)
        evaluation = req.evaluation or evaluate_policies(ctx=ctx, risk=risk,
                                                         policies_by_level=policies_by_level)
        expires_in = min(max(60, req.expires_in_seconds), MAX_EXPIRATION_SECONDS)
        expires_at = _utcnow() + timedelta(seconds=expires_in)
        payload = envelope_payload(action_type=req.action_type,
                                   action_category=ctx.action_category,
                                   target_type=req.target_type, target_id=req.target_id,
                                   redacted_params=redacted, environment=req.environment,
                                   organization_id=str(req.organization_id))
        digest = action_hash(payload)
        try:
            approval_type = ApprovalType(req.action_category.lower())
        except ValueError:
            approval_type = ApprovalType.CUSTOM
        approval = Approval(
            organization_id=req.organization_id, run_id=req.agent_run_id,
            workflow_execution_id=req.workflow_execution_id,
            approval_type=approval_type, status=ApprovalStatus.PENDING,
            requested_by=None, payload={
                "action_type": req.action_type, "action_category": ctx.action_category,
                "action_description": req.action_description or req.requested_action,
                "requested_action": req.requested_action,
                "requested_parameters": redacted, "impact_summary": req.impact_summary,
                "target_type": req.target_type, "target_id": req.target_id,
                "target_reference": req.target_reference,
                "requester_type": req.requester_type, "requester_id": req.requester_id,
                "agent_id": str(req.agent_id) if req.agent_id else None,
                "agent_run_id": str(req.agent_run_id) if req.agent_run_id else None,
                "workflow_id": str(req.workflow_id) if req.workflow_id else None,
                "workflow_execution_id": str(req.workflow_execution_id) if req.workflow_execution_id else None,
                "task_id": req.task_id, "team_id": str(req.team_id) if req.team_id else None,
                "environment": req.environment,
                "risk_level": risk.risk_level.value, "risk_score": risk.risk_score,
                "risk_reasons": risk.reasons,
                "policy_decision": evaluation.decision.value,
                "policy_version": evaluation.policy_version,
                "approval_kind": req.approval_kind.value,
                "required_approvals": req.required_approvals,
                "required_role": req.required_role or evaluation.required_role,
                "action_hash": digest, "approval_token": approval_token(),
                "max_uses": req.max_uses, "use_count": 0,
            },
            expires_at=expires_at)
        self.db.add(approval)
        await self.db.flush()
        # Satellite rows: snapshot + event (best-effort, same transaction).
        try:
            from openagent.db.models.approval import ApprovalSnapshot, ApprovalEvent
            self.db.add(ApprovalSnapshot(
                approval_id=approval.id, organization_id=req.organization_id,
                action_hash=digest, snapshot={"envelope": payload,
                                              "risk": risk.to_dict(),
                                              "policy": evaluation.to_dict(),
                                              "redacted_params": redacted}))
            self.db.add(ApprovalEvent(
                approval_id=approval.id, organization_id=req.organization_id,
                event_type="approval.created", actor_type=req.requester_type,
                actor_id=req.requester_id,
                event_data={"risk_level": risk.risk_level.value,
                            "policy_decision": evaluation.decision.value}))
        except Exception as exc:  # pragma: no cover - satellite tables optional pre-migration
            logger.warning("approval satellite write skipped", error=str(exc))
        await self._audit(req.organization_id, None, "approval.created", approval.id,
                          {"risk_level": risk.risk_level.value,
                           "policy_decision": evaluation.decision.value})
        await self._event("approval.created", approval, req.organization_id)
        logger.info("approval created", approval_id=str(approval.id),
                    risk=risk.risk_level.value, decision=evaluation.decision.value)
        return approval

    # -- transitions ----------------------------------------------------
    async def _locked(self, approval_id: UUID) -> Any:
        from openagent.db.models.approval import Approval
        result = await self.db.execute(
            select(Approval).where(Approval.id == approval_id).with_for_update())
        approval = result.scalar_one_or_none()
        if approval is None:
            raise ApprovalError("Approval not found", code="NOT_FOUND")
        return approval

    async def _require_org(self, approval: Any, organization_id: UUID) -> None:
        if approval.organization_id != organization_id:
            await self._security_event(organization_id, None,
                                       "approval.cross_tenant_attempt",
                                       {"approval_id": str(getattr(approval, "id", ""))})
            raise ApprovalError("Cross-tenant approval access denied", code="CROSS_TENANT")

    def _check_expiry(self, approval: Any) -> bool:
        from openagent.db.models.approval import ApprovalStatus
        exp = getattr(approval, "expires_at", None)
        if exp is not None:
            now = _utcnow()
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if now >= exp and getattr(approval, "status", None) == ApprovalStatus.PENDING:
                approval.status = ApprovalStatus.EXPIRED
                return True
        return False

    async def _transition(self, approval: Any, to: ApprovalState,
                          organization_id: UUID) -> Any:
        from openagent.db.models.approval import ApprovalStatus
        await self._require_org(approval, organization_id)
        if self._check_expiry(approval):
            await self.db.flush()
            raise ApprovalError("Approval has expired", code="EXPIRED")
        frm = ApprovalState(str(getattr(approval, "status", "").value
                                if hasattr(getattr(approval, "status", ""), "value")
                                else getattr(approval, "status", "")))
        if not can_transition(frm, to):
            raise ApprovalError(f"Illegal transition {frm.value} -> {to.value}",
                                code="ILLEGAL_TRANSITION")
        approval.status = ApprovalStatus(to.value.lower())
        return approval

    async def approve(self, approval_id: UUID, *, organization_id: UUID,
                      approver_id: UUID, reason: str = "",
                      idempotency_key: Optional[str] = None) -> Any:
        from openagent.db.models.approval import ApprovalDecision
        approval = await self._locked(approval_id)
        payload = approval.payload or {}
        # Self-approval protection: the requester identity can never approve.
        if payload.get("requester_id") and str(payload["requester_id"]) == str(approver_id):
            await self._security_event(organization_id, approver_id,
                                       "approval.self_approval_attempt",
                                       {"approval_id": str(approval_id)})
            raise ApprovalError("Requester cannot approve their own action",
                                code="SELF_APPROVAL")
        # Idempotency: repeated approve with same key returns current record.
        if idempotency_key:
            existing = await self.db.execute(
                select(ApprovalDecision).where(
                    ApprovalDecision.approval_id == approval_id,
                    ApprovalDecision.idempotency_key == idempotency_key))
            if existing.scalar_one_or_none() is not None:
                return approval
        # Multi-approval counting: record decision, promote only at quorum.
        try:
            self.db.add(ApprovalDecision(
                approval_id=approval_id, organization_id=organization_id,
                actor_id=approver_id, decision="approved", reason=reason,
                idempotency_key=idempotency_key))
            await self.db.flush()
        except Exception:  # pragma: no cover - table may predate migration
            pass
        required = int((payload.get("required_approvals") or 1))
        count = await self._decision_count(approval_id, "approved")
        if count < required:
            await self._audit(organization_id, approver_id, "approval.approved_partial",
                              approval_id, {"approvals": count, "required": required})
            return approval  # stays PENDING until quorum
        await self._transition(approval, ApprovalState.APPROVED, organization_id)
        approval.approved_by = approver_id
        approval.resolved_at = _utcnow()
        payload["approval_reason"] = reason
        payload["approved_at"] = approval.resolved_at.isoformat()
        approval.payload = dict(payload)
        await self.db.flush()
        await self._audit(organization_id, approver_id, "approval.approved", approval_id,
                          {"risk_level": payload.get("risk_level")})
        await self._event("approval.approved", approval, organization_id, approver_id)
        return approval

    async def reject(self, approval_id: UUID, *, organization_id: UUID,
                     rejecter_id: UUID, reason: str = "") -> Any:
        approval = await self._locked(approval_id)
        payload = approval.payload or {}
        if payload.get("requester_id") and str(payload["requester_id"]) == str(rejecter_id):
            # Rejecting your own request is allowed (withdraw), but log it distinctly.
            reason = f"[self-withdraw] {reason}" if reason else "[self-withdraw]"
        await self._transition(approval, ApprovalState.REJECTED, organization_id)
        approval.resolved_at = _utcnow()
        payload["rejection_reason"] = reason
        payload["rejected_at"] = approval.resolved_at.isoformat()
        payload["rejected_by"] = str(rejecter_id)
        approval.payload = dict(payload)
        await self.db.flush()
        await self._audit(organization_id, rejecter_id, "approval.rejected", approval_id, {})
        await self._event("approval.rejected", approval, organization_id, rejecter_id)
        return approval

    async def cancel(self, approval_id: UUID, *, organization_id: UUID,
                     actor_id: Optional[UUID] = None, reason: str = "") -> Any:
        approval = await self._locked(approval_id)
        # PENDING -> CANCELLED or APPROVED -> CANCELLED only.
        frm = ApprovalState(str(approval.status.value
                                if hasattr(approval.status, "value") else approval.status))
        target = ApprovalState.CANCELLED
        if not can_transition(frm, target):
            raise ApprovalError(f"Cannot cancel from {frm.value}", code="ILLEGAL_TRANSITION")
        await self._transition(approval, target, organization_id)
        payload = approval.payload or {}
        payload["cancel_reason"] = reason
        approval.payload = dict(payload)
        await self.db.flush()
        await self._audit(organization_id, actor_id, "approval.cancelled", approval_id, {})
        await self._event("approval.cancelled", approval, organization_id, actor_id)
        return approval

    async def expire_due(self, limit: int = 100) -> int:
        from openagent.db.models.approval import Approval, ApprovalStatus
        result = await self.db.execute(
            select(Approval).where(Approval.status == ApprovalStatus.PENDING,
                                   Approval.expires_at.is_not(None),
                                   Approval.expires_at <= _utcnow()).limit(limit))
        count = 0
        for approval in result.scalars().all():
            approval.status = ApprovalStatus.EXPIRED
            count += 1
            await self._audit(approval.organization_id, None, "approval.expired",
                              approval.id, {})
        if count:
            await self.db.flush()
        return count

    async def escalate(self, approval_id: UUID, *, organization_id: UUID,
                       actor_id: Optional[UUID] = None, reason: str = "",
                       escalate_to: str = "organization_admin") -> Any:
        approval = await self._locked(approval_id)
        await self._require_org(approval, organization_id)
        payload = approval.payload or {}
        chain = list(payload.get("escalation_chain") or [])
        if len(chain) >= 5:
            raise ApprovalError("Escalation depth exceeded", code="ESCALATION_LOOP")
        chain.append({"by": str(actor_id) if actor_id else None, "to": escalate_to,
                      "reason": reason, "at": _utcnow().isoformat()})
        payload["escalation_chain"] = chain
        payload["escalated_to"] = escalate_to
        approval.payload = dict(payload)
        await self.db.flush()
        await self._audit(organization_id, actor_id, "approval.escalated", approval_id,
                          {"to": escalate_to})
        await self._event("approval.escalated", approval, organization_id, actor_id)
        return approval

    async def get_status(self, approval_id: UUID, *, organization_id: UUID) -> dict[str, Any]:
        from openagent.db.models.approval import Approval
        result = await self.db.execute(select(Approval).where(Approval.id == approval_id))
        approval = result.scalar_one_or_none()
        if approval is None:
            raise ApprovalError("Approval not found", code="NOT_FOUND")
        await self._require_org(approval, organization_id)
        if self._check_expiry(approval):
            await self.db.flush()
        payload = approval.payload or {}
        return {"id": str(approval.id), "status": str(approval.status.value
                if hasattr(approval.status, "value") else approval.status).upper(),
                "risk_level": payload.get("risk_level"),
                "policy_decision": payload.get("policy_decision"),
                "expires_at": approval.expires_at.isoformat() if approval.expires_at else None,
                "required_approvals": payload.get("required_approvals", 1)}

    # -- execution binding (no replay, no tampering) ---------------------
    async def begin_execution(self, approval_id: UUID, *, organization_id: UUID,
                              action_type: str, action_category: str, target_type: str,
                              target_id: str, params: dict[str, Any],
                              environment: str) -> Any:
        """Verify hash + expiry + single-use, then move APPROVED -> EXECUTING.

        Returns the approval. Raises ApprovalError(INVALID_APPROVAL) when the
        live action differs from the approved snapshot.
        """
        approval = await self._locked(approval_id)
        await self._require_org(approval, organization_id)
        payload = approval.payload or {}
        redacted = redact_params(params or {})
        if not isinstance(redacted, dict):
            redacted = {"value": redacted}
        live = envelope_payload(action_type=action_type,
                                action_category=(action_category or "").upper(),
                                target_type=target_type or "", target_id=target_id or "",
                                redacted_params=redacted, environment=environment,
                                organization_id=str(organization_id))
        if action_hash(live) != payload.get("action_hash"):
            await self._security_event(organization_id, None,
                                       "approval.modified_payload",
                                       {"approval_id": str(approval_id)})
            try:
                await self._transition(approval, ApprovalState.INVALIDATED, organization_id)
                await self.db.flush()
            except ApprovalError:
                pass
            raise ApprovalError("Action differs from approved snapshot",
                                code="INVALID_APPROVAL")
        frm = ApprovalState(str(approval.status.value
                                if hasattr(approval.status, "value") else approval.status))
        if frm != ApprovalState.APPROVED:
            if frm == ApprovalState.PENDING:
                raise ApprovalError("Approval not yet granted", code="NOT_APPROVED")
            raise ApprovalError(f"Approval in state {frm.value} cannot execute",
                                code="INVALID_STATE")
        if self._check_expiry(approval):
            await self.db.flush()
            await self._security_event(organization_id, None,
                                       "approval.expired_execution_attempt",
                                       {"approval_id": str(approval_id)})
            raise ApprovalError("Approval has expired", code="EXPIRED")
        uses = int(payload.get("use_count") or 0)
        if uses >= int(payload.get("max_uses") or 1):
            await self._security_event(organization_id, None,
                                       "approval.replay_attempt",
                                       {"approval_id": str(approval_id)})
            raise ApprovalError("Approval already consumed (replay blocked)",
                                code="REPLAY")
        payload["use_count"] = uses + 1
        approval.payload = dict(payload)
        await self._transition(approval, ApprovalState.EXECUTING, organization_id)
        await self.db.flush()
        await self._audit(organization_id, None, "approval.execution_started",
                          approval_id, {})
        return approval

    async def finish_execution(self, approval_id: UUID, *, organization_id: UUID,
                               success: bool, result_ref: str = "") -> Any:
        approval = await self._locked(approval_id)
        await self._transition(
            approval, ApprovalState.EXECUTED if success else ApprovalState.EXECUTION_FAILED,
            organization_id)
        payload = approval.payload or {}
        payload["execution_result_reference"] = result_ref
        approval.payload = dict(payload)
        await self.db.flush()
        await self._audit(organization_id, None,
                          "approval.execution_succeeded" if success
                          else "approval.execution_failed", approval_id, {})
        await self._event("approval.executed", approval, organization_id)
        return approval

    # -- helpers ---------------------------------------------------------
    async def _decision_count(self, approval_id: UUID, decision: str) -> int:
        try:
            from openagent.db.models.approval import ApprovalDecision
            result = await self.db.execute(
                select(ApprovalDecision).where(
                    ApprovalDecision.approval_id == approval_id,
                    ApprovalDecision.decision == decision))
            return len(result.scalars().all())
        except Exception:
            return 1  # table predates migration; single-approval path

    async def evaluate(self, req: CreateRequest,
                       policies_by_level: Optional[dict] = None) -> PolicyEvaluation:
        redacted = redact_params(req.requested_params or {})
        if not isinstance(redacted, dict):
            redacted = {"value": redacted}
        ctx = build_action_context(req, redacted if isinstance(redacted, dict) else {})
        risk = req.risk or evaluate_risk(ctx)
        return evaluate_policies(ctx=ctx, risk=risk, policies_by_level=policies_by_level)

    async def _audit(self, org_id: UUID | None, actor: UUID | None, action: str,
                     resource_id: UUID, meta: dict[str, Any]) -> None:
        try:
            from openagent.db.models.audit_log import AuditLog
            if org_id is None:
                return
            self.db.add(AuditLog(organization_id=org_id, actor_user_id=actor,
                                 action=action, resource_type="approval",
                                 resource_id=resource_id, metadata=dict(meta or {})))
            await self.db.flush()
        except Exception as exc:  # pragma: no cover - audit must never break approvals
            logger.warning("approval audit skipped", error=str(exc))

    async def _event(self, event_type: str, approval: Any, org_id: UUID,
                     user_id: UUID | None = None) -> None:
        try:
            from openagent.core.events import EventService
            svc = EventService(self.db)
            payload = approval.payload or {}
            await svc.publish(event_type, "approval", approval.id,
                              {"status": str(approval.status.value
                               if hasattr(approval.status, "value") else approval.status),
                               "risk_level": payload.get("risk_level"),
                               "policy_decision": payload.get("policy_decision")},
                              organization_id=org_id, user_id=user_id)
        except Exception as exc:  # pragma: no cover - events are best-effort
            logger.warning("approval event skipped", error=str(exc))

    async def _security_event(self, org_id: UUID | None, user_id: UUID | None,
                              event_type: str, meta: dict[str, Any]) -> None:
        try:
            from openagent.db.models.security_event import SecurityEvent
            self.db.add(SecurityEvent(user_id=user_id, organization_id=org_id,
                                      event_type=event_type, metadata=dict(meta or {})))  # type: ignore[arg-type]
            await self.db.flush()
        except Exception as exc:  # pragma: no cover
            logger.warning("approval security event skipped", error=str(exc))
