"""Manager service: persistence + lifecycle for the management layer.

Builds on OrchestrationService (task assignment, handoff execution) without
duplicating it. Every operation is organization-scoped; authority checks run
before any state change; all decisions are audited.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, TYPE_CHECKING
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from openagent.db.models import Agent, AuditLog
from openagent.db.models.approval import Approval, ApprovalStatus, ApprovalType

if TYPE_CHECKING:
    from openagent.db.models.management import (
        AgentAvailability,
        AgentCapacity,
        AgentContract,
        AgentDepartment,
        CollaborationRequest,
        DelegationRequest,
        DynamicTeam,
        DynamicTeamMembership,
        Escalation,
        HandoffPackage,
        ManagerDecision,
        ManagerProfile,
        PlanVersion,
        ReviewResult,
    )

from openagent.db.models.management import (
    DelegationRequestStatus,
    DynamicTeamStatus,
    EscalationStatus,
    HandoffPackageStatus,
    ManagerProfileStatus,
    ReviewResultStatus,
)
from openagent.db.models.orchestration import (
    AgentMessage,
    OrchestrationEvent,
    OrchestrationRun,
)
from openagent.db.repositories.management import (
    AgentAvailabilityRepository,
    AgentCapacityRepository,
    AgentCommitmentRepository,
    AgentContractRepository,
    AgentDepartmentRepository,
    CollaborationRequestRepository,
    DelegationRequestRepository,
    DynamicTeamMembershipRepository,
    DynamicTeamRepository,
    EscalationRepository,
    HandoffPackageRepository,
    ManagerDecisionRepository,
    ManagerProfileRepository,
    PlanVersionRepository,
    ReviewResultRepository,
    TeamCharterRepository,
)
from openagent.management.authority import (
    ManagerProfile as ProfileData,
    check_authority,
)
from openagent.management.collaboration import (
    CollaborationProposal,
    sanitize_progress,
    validate_collaboration,
)
from openagent.management.contracts import (
    contract_from_dict,
    validate_contract,
)
from openagent.management.delegations import (
    DelegationProposal,
    assess_reassignment,
    delegation_expired,
    select_delegate,
)
from openagent.management.escalation import (
    EscalationRequest,
    apply_failure_matrix,
    route_escalation,
    validate_escalation,
)
from openagent.management.handoff import (
    StructuredHandoff,
    build_structured_handoff,
)
from openagent.management.manager_loop import (
    LoopObservation,
    ManagerDecisionLoop,
    ManagerLoopState_,
)
from openagent.management.messaging import (
    ChannelPolicy,
    CommunicationService,
)
from openagent.management.review import (
    RuleBasedQualityGate,
    verify_acceptance,
)
from openagent.management.teams import (
    FormedTeam,
    TeamFormationRequest,
    form_team,
    split_budget,
    validate_dissolution,
)
from openagent.management.types import (
    DEFAULT_FAILURE_MATRIX,
    AgentScope,
    ChannelType,
    CollaborationAction,
    CommitmentStatus,
    DelegationPolicy,
    DelegationStatus,
    DynamicTeamType,
    EscalationPolicyConfig,
    EscalationSeverity,
    HandoffMode,
    HandoffStatus,
    ManagerAuthority,
    ReviewStatus,
    TeamMembershipStatus,
    can_transition_delegation,
    can_transition_escalation,
    can_transition_handoff,
    can_transition_team,
)
from openagent.management.workforce import allocate_deadlines
from openagent.orchestration.assignment import AgentCandidate
from openagent.orchestration.config import OrchestrationOrgSettings
from openagent.orchestration.events import record_metric
from openagent.orchestration.security import sanitize_dict
from openagent.orchestration.service import OrchestrationError, OrchestrationService

logger = structlog.get_logger("management.service")


class ManagementService:
    def __init__(self, db: AsyncSession, settings: Optional[OrchestrationOrgSettings] = None):
        self.db = db
        self.settings = settings or OrchestrationOrgSettings()
        self.profiles = ManagerProfileRepository(db)
        self.contracts = AgentContractRepository(db)
        self.delegations = DelegationRequestRepository(db)
        self.commitments = AgentCommitmentRepository(db)
        self.handoffs = HandoffPackageRepository(db)
        self.reviews = ReviewResultRepository(db)
        self.escalations = EscalationRepository(db)
        self.departments = AgentDepartmentRepository(db)
        self.teams = DynamicTeamRepository(db)
        self.charters = TeamCharterRepository(db)
        self.memberships = DynamicTeamMembershipRepository(db)
        self.availability = AgentAvailabilityRepository(db)
        self.capacity = AgentCapacityRepository(db)
        self.versions = PlanVersionRepository(db)
        self.collaborations = CollaborationRequestRepository(db)
        self.decisions = ManagerDecisionRepository(db)
        self.orchestrator = OrchestrationService(db, self.settings)
        self.communication = CommunicationService(
            persist=self._persist_message, audit=self._audit_message
        )

    # -- helpers ---------------------------------------------------------
    async def _require_agent(self, organization_id: UUID, agent_id: UUID) -> Agent:
        result = await self.db.execute(
            select(Agent).where(
                Agent.id == agent_id, Agent.organization_id == organization_id
            )
        )
        agent = result.scalar_one_or_none()
        if agent is None:
            raise OrchestrationError("AGENT_NOT_FOUND", "agent not found in organization")
        return agent

    async def _require_profile(self, organization_id: UUID, agent_id: UUID) -> ManagerProfile:
        profile = await self.profiles.get_by_agent(organization_id, agent_id)
        if profile is None:
            raise OrchestrationError("NOT_MANAGER", "agent has no manager profile")
        if profile.status != ManagerProfileStatus.ACTIVE:
            raise OrchestrationError("MANAGER_SUSPENDED", "manager profile is not active")
        return profile

    def _profile_data(self, profile: ManagerProfile) -> ProfileData:
        try:
            actions = {ManagerAuthority(a) for a in (profile.allowed_actions or [])}
        except ValueError:
            actions = set()
        try:
            scope = AgentScope(profile.scope)
        except ValueError:
            scope = AgentScope.ORGANIZATION
        try:
            policy = DelegationPolicy(profile.delegation_policy)
        except ValueError:
            policy = DelegationPolicy.HYBRID
        return ProfileData(
            agent_id=str(profile.agent_id),
            label=profile.label,
            managed_capabilities=list(profile.managed_capabilities or []),
            delegation_policy=policy,
            review_required=bool(profile.review_required),
            escalation_policy=profile.escalation_policy,
            team_policy=profile.team_policy,
            budget_share=float(profile.budget_share),
            max_workers=profile.max_workers,
            max_depth=profile.max_depth,
            max_direct_reports=profile.max_direct_reports,
            max_active_tasks=profile.max_active_tasks,
            max_delegations=profile.max_delegations,
            max_replans=profile.max_replans,
            max_team_size=profile.max_team_size,
            allowed_actions=actions,
            scope=scope,
            department_id=str(profile.department_id) if profile.department_id else None,
            team_id=str(profile.team_id) if profile.team_id else None,
        )

    async def _audit(self, organization_id: UUID, actor: Optional[UUID],
                     action: str, resource_type: str, resource_id: Optional[UUID]) -> None:
        self.db.add(
            AuditLog(
                organization_id=organization_id, actor_user_id=actor, action=action,
                resource_type=resource_type, resource_id=resource_id,
            )
        )
        await self.db.flush()

    async def _record_run_event(self, run: OrchestrationRun, event_type: str,
                                task_id: Optional[UUID], agent_id: Optional[UUID],
                                payload: Dict[str, Any]) -> None:
        import uuid as _uuid

        self.db.add(
            OrchestrationEvent(
                organization_id=run.organization_id, orchestration_run_id=run.id,
                task_id=task_id, agent_id=agent_id, event_type=event_type,
                payload=sanitize_dict(dict(payload or {})),
                trace_id=_uuid.uuid4().hex, span_id=_uuid.uuid4().hex[:16],
            )
        )
        await self.db.flush()

    async def _persist_message(self, **kwargs: Any) -> AgentMessage:
        record = AgentMessage(
            organization_id=kwargs["organization_id"],
            orchestration_run_id=kwargs["orchestration_run_id"],
            sender_agent_id=kwargs.get("sender_agent_id"),
            recipient_agent_id=kwargs.get("recipient_agent_id"),
            task_id=kwargs.get("task_id"),
            message_type=f"{kwargs.get('channel', 'direct')}:{kwargs.get('message_type', 'status')}",
            payload=dict(kwargs.get("payload", {}) or {}),
        )
        self.db.add(record)
        await self.db.flush()
        return record

    async def _audit_message(self, **kwargs: Any) -> None:
        await self._audit(
            kwargs["organization_id"], None, "management.message_routed",
            "agent_message", None,
        )

    # -- manager profiles --------------------------------------------------
    async def create_profile(
        self, organization_id: UUID, agent_id: UUID, *,
        label: str = "manager", actor: Optional[UUID] = None,
        allowed_actions: Optional[List[str]] = None,
        scope: str = "organization", **overrides: Any,
    ) -> ManagerProfile:
        await self._require_agent(organization_id, agent_id)
        existing = await self.profiles.get_by_agent(organization_id, agent_id)
        if existing is not None:
            raise OrchestrationError("ALREADY_MANAGER", "agent already has a manager profile")
        actions = allowed_actions or [
            ManagerAuthority.CAN_DELEGATE.value, ManagerAuthority.CAN_REVIEW.value,
            ManagerAuthority.CAN_REQUEST_REVISION.value, ManagerAuthority.CAN_ESCALATE.value,
        ]
        profile = await self.profiles.create(
            organization_id=organization_id, agent_id=agent_id, label=label,
            status=ManagerProfileStatus.ACTIVE, allowed_actions=actions, scope=scope,
            **{k: v for k, v in overrides.items()
               if k in {"managed_capabilities", "delegation_policy", "review_required",
                        "escalation_policy", "team_policy", "budget_share", "max_workers",
                        "max_depth", "max_direct_reports", "max_active_tasks",
                        "max_delegations", "max_replans", "max_team_size",
                        "department_id", "team_id"}},
        )
        await self._audit(organization_id, actor, "management.profile_create",
                          "manager_profile", profile.id)
        await self.db.commit()
        record_metric("manager_decisions_total")
        return profile

    async def check_manager_authority(
        self, organization_id: UUID, manager_agent_id: UUID, action: ManagerAuthority,
    ) -> ProfileData:
        profile = await self._require_profile(organization_id, manager_agent_id)
        data = self._profile_data(profile)
        decision = check_authority(data, action)
        if not decision.allowed:
            raise OrchestrationError("AUTHORITY_DENIED", "; ".join(decision.reasons))
        return data

    # -- contracts -----------------------------------------------------------
    async def create_contract(
        self, organization_id: UUID, data: Dict[str, Any], *,
        manager_agent_id: Optional[UUID] = None,
        task_id: Optional[UUID] = None, run_id: Optional[UUID] = None,
        actor: Optional[UUID] = None, idempotency_key: Optional[str] = None,
    ) -> AgentContract:
        if idempotency_key:
            existing = await self.contracts.get_by_idempotency_key(organization_id, idempotency_key)
            if existing:
                return existing
        contract = contract_from_dict(sanitize_dict(data))
        validation = validate_contract(contract)
        if not validation.valid:
            raise OrchestrationError("INVALID_CONTRACT", "; ".join(validation.errors))
        agent_ref = contract.inputs.pop("agent_id", None)
        agent_uuid: Optional[UUID] = None
        if agent_ref:
            try:
                agent_uuid = UUID(str(agent_ref))
            except ValueError:
                raise OrchestrationError("INVALID_CONTRACT", "agent_id must be a valid UUID")
            await self._require_agent(organization_id, agent_uuid)
        row = await self.contracts.create(
            organization_id=organization_id, orchestration_run_id=run_id, task_id=task_id,
            agent_id=agent_uuid,
            manager_agent_id=manager_agent_id,
            objective=contract.objective, responsibilities=contract.responsibilities,
            inputs=contract.inputs, expected_outputs=contract.expected_outputs,
            capabilities=contract.capabilities, constraints=contract.constraints,
            required_permissions=contract.permissions, budget=contract.budget,
            quality_requirements=contract.quality_requirements,
            acceptance_criteria=[
                {"description": c.description, "verification": c.verification,
                 "satisfied": c.satisfied}
                for c in contract.acceptance_criteria
            ],
            escalation_conditions=contract.escalation_conditions,
            max_revisions=contract.max_revisions, idempotency_key=idempotency_key,
        )
        await self._audit(organization_id, actor, "management.contract_create",
                          "agent_contract", row.id)
        await self.db.commit()
        return row

    # -- delegations -----------------------------------------------------------
    async def request_delegation(
        self, organization_id: UUID, *,
        source_agent_id: UUID, task_id: Optional[UUID] = None,
        run_id: Optional[UUID] = None, reason: str = "",
        contract: Optional[Dict[str, Any]] = None, contract_id: Optional[UUID] = None,
        required_capabilities: Optional[List[str]] = None,
        policy: str = "hybrid", budget: Optional[Dict[str, Any]] = None,
        deadline: Optional[datetime] = None, explicit_target_id: Optional[UUID] = None,
        actor: Optional[UUID] = None, idempotency_key: Optional[str] = None,
    ) -> DelegationRequest:
        if idempotency_key:
            existing = await self.delegations.get_by_idempotency_key(organization_id, idempotency_key)
            if existing:
                return existing
        source = await self._require_agent(organization_id, source_agent_id)
        _ = source
        # Authority: source must be a manager with CAN_DELEGATE, or the task owner.
        try:
            profile = await self._require_profile(organization_id, source_agent_id)
            data = self._profile_data(profile)
            decision = check_authority(data, ManagerAuthority.CAN_DELEGATE)
            if not decision.allowed:
                raise OrchestrationError("AUTHORITY_DENIED", "; ".join(decision.reasons))
            effective_policy = DelegationPolicy(data.delegation_policy.value)
        except OrchestrationError as exc:
            if exc.code not in ("NOT_MANAGER", "MANAGER_SUSPENDED"):
                raise
            # Non-manager task owners may delegate only explicitly.
            effective_policy = DelegationPolicy.EXPLICIT_ONLY
            if not explicit_target_id:
                raise OrchestrationError(
                    "AUTHORITY_DENIED", "non-managers may only delegate to an explicit target")
        try:
            requested_policy = DelegationPolicy(policy)
        except ValueError:
            requested_policy = effective_policy
        if effective_policy == DelegationPolicy.EXPLICIT_ONLY:
            requested_policy = DelegationPolicy.EXPLICIT_ONLY

        # Inline contract: a delegation may carry its work agreement; it is
        # validated and persisted like any other contract.
        if contract_id is None and contract:
            inline = await self.create_contract(
                organization_id, sanitize_dict(dict(contract)),
                manager_agent_id=source_agent_id, task_id=task_id, run_id=run_id,
                actor=actor,
            )
            contract_id = inline.id

        target_id = explicit_target_id
        reasons: List[str] = []
        if target_id is None and requested_policy != DelegationPolicy.EXPLICIT_ONLY:
            selection = await self._select_specialist(
                organization_id, required_capabilities or [], requested_policy, run_id)
            target_id = UUID(selection["agent_id"]) if selection.get("agent_id") else None
            reasons = selection.get("reasons", [])
        if target_id is not None:
            await self._require_agent(organization_id, target_id)
            if target_id == source_agent_id:
                raise OrchestrationError("SELF_DELEGATION", "self-delegation is not allowed")
        # Deadline propagation (§74): a child deadline must remain within the
        # parent task's constraints and can never extend the root deadline.
        if deadline is not None and task_id is not None:
            parent_deadline = await self._parent_deadline(organization_id, task_id)
            if parent_deadline is not None:
                requested = deadline if deadline.tzinfo else deadline.replace(tzinfo=timezone.utc)
                if requested > parent_deadline:
                    deadline = parent_deadline
        row = await self.delegations.create(
            organization_id=organization_id, orchestration_run_id=run_id, task_id=task_id,
            contract_id=contract_id, source_agent_id=source_agent_id,
            target_agent_id=target_id, reason=reason[:4000],
            required_capabilities=list(required_capabilities or []),
            constraints=[], budget=sanitize_dict(dict(budget or {})),
            deadline=deadline, policy=requested_policy.value,
            status=DelegationRequestStatus.PENDING, idempotency_key=idempotency_key,
        )
        if run_id is not None:
            run = await self.orchestrator.get_run(organization_id, run_id)
            await self._record_run_event(
                run, "DELEGATION_CREATED", task_id, source_agent_id,
                {"delegation_id": str(row.id), "reasons": reasons})
        await self._audit(organization_id, actor, "management.delegation_request",
                          "delegation_request", row.id)
        await self.db.commit()
        record_metric("delegations_total")
        return row

    async def transition_delegation(
        self, organization_id: UUID, delegation_id: UUID, to: DelegationRequestStatus, *,
        reason: str = "", actor: Optional[UUID] = None, decided_by: Optional[UUID] = None,
    ) -> DelegationRequest:
        row = await self.delegations.get_by_id_with_org(delegation_id, organization_id)
        if row is None:
            raise OrchestrationError("NOT_FOUND", "delegation not found")
        current = DelegationStatus(row.status.value)
        target = DelegationStatus(to.value)
        if not can_transition_delegation(current, target):
            raise OrchestrationError(
                "INVALID_TRANSITION", f"cannot transition delegation {current.value} -> {target.value}")
        if target == DelegationStatus.ACCEPTED and row.target_agent_id is None:
            raise OrchestrationError("NO_TARGET", "cannot accept delegation without a target agent")
        row.status = to
        row.decision_reason = reason[:2000] or None
        row.decided_by = decided_by
        row.decided_at = datetime.now(timezone.utc)
        # Link into orchestration: accepted delegations assign the task and
        # create a commitment; completed delegations close the loop.
        if target == DelegationStatus.ACCEPTED and row.task_id and row.orchestration_run_id:
            try:
                await self.orchestrator.reassign_task(
                    organization_id, row.orchestration_run_id, row.task_id,
                    agent_id=row.target_agent_id, actor=actor)  # type: ignore[arg-type]
            except OrchestrationError:
                pass  # task may already be assigned; commitment still recorded
            await self.commitments.create(
                organization_id=organization_id, orchestration_run_id=row.orchestration_run_id,
                delegation_id=row.id, task_id=row.task_id, agent_id=row.target_agent_id,  # type: ignore[arg-type]
                budget=dict(row.budget or {}), status=CommitmentStatus.ACCEPTED.value,
                accepted_at=datetime.now(timezone.utc),
            )
            if row.orchestration_run_id:
                run = await self.orchestrator.get_run(organization_id, row.orchestration_run_id)
                await self._record_run_event(
                    run, "DELEGATION_ACCEPTED", row.task_id, row.target_agent_id,
                    {"delegation_id": str(row.id)})
        if row.orchestration_run_id:
            try:
                run = await self.orchestrator.get_run(organization_id, row.orchestration_run_id)
                await self._record_run_event(
                    run, f"DELEGATION_{target.value.upper()}", row.task_id,
                    row.target_agent_id, {"delegation_id": str(row.id), "reason": reason[:500]})
            except OrchestrationError:
                pass
        await self._audit(organization_id, actor, f"management.delegation_{target.value}",
                          "delegation_request", row.id)
        await self.db.commit()
        if target in (DelegationStatus.REJECTED, DelegationStatus.EXPIRED):
            record_metric("delegations_failed")
        return row

    async def _select_specialist(
        self, organization_id: UUID, required: List[str], policy: DelegationPolicy,
        run_id: Optional[UUID],
    ) -> Dict[str, Any]:
        from openagent.orchestration.discovery import discover_agents

        agents = await discover_agents(
            self.db, organization_id=organization_id, capabilities=None, limit=100)
        candidates: List[AgentCandidate] = []
        for agent in agents:
            meta = getattr(agent, "metadata", None) or {}
            caps = meta.get("capabilities") or meta.get("advertised_capabilities") or []
            avail = await self.availability.get_by_agent(agent.id)
            state = (avail.state if avail else "available")
            healthy = state not in ("offline", "disabled", "unhealthy")
            # Capacity enforcement (§45): agents at max concurrent tasks are
            # not selectable. No availability row means no recorded load.
            if healthy and avail is not None:
                capacity = await self.capacity.get_by_agent(agent.id)
                if capacity and avail.active_tasks >= capacity.max_concurrent_tasks:
                    healthy = False
            candidates.append(
                AgentCandidate(
                    agent_id=str(agent.id),
                    capabilities=[str(c) for c in caps] if isinstance(caps, list) else [],
                    active_tasks=avail.active_tasks if avail else 0,
                    healthy=state not in ("offline", "disabled", "unhealthy"),
                    cost_hint=float(meta.get("cost_hint", 0.0)) if isinstance(meta, dict) else 0.0,
                    metadata={"trust": meta.get("trust", "organization")} if isinstance(meta, dict) else {},
                )
            )
        proposal = DelegationProposal(
            source_agent_id="", task_id="", required_capabilities=required, policy=policy)
        selection = select_delegate(proposal, candidates)
        return {"agent_id": selection.target_agent_id, "reasons": selection.reasons}

    async def reassign_with_rules(
        self, organization_id: UUID, run_id: UUID, task_id: UUID, *,
        manager_agent_id: UUID, actor: Optional[UUID] = None,
    ) -> Dict[str, Any]:
        await self.check_manager_authority(
            organization_id, manager_agent_id, ManagerAuthority.CAN_REASSIGN)
        task = await self.orchestrator.tasks.get_by_id_with_org(task_id, organization_id)
        if task is None:
            raise OrchestrationError("NOT_FOUND", "task not found")
        from openagent.orchestration.discovery import discover_agents

        agents = await discover_agents(
            self.db, organization_id=organization_id, capabilities=None, limit=100)
        candidates = [
            AgentCandidate(
                agent_id=str(a.id),
                capabilities=_caps_of(a),
                active_tasks=0, healthy=True,
                metadata={"trust": ((getattr(a, "metadata", None) or {}).get("trust", "organization"))},
            )
            for a in agents
        ]
        assessment = assess_reassignment(
            required_capabilities=list(task.required_capabilities or []),
            candidates=candidates,
            previous_agent_id=str(task.assigned_agent_id) if task.assigned_agent_id else None,
            attempts=task.retry_count,
        )
        if assessment.new_agent_id is None:
            raise OrchestrationError("NO_CANDIDATE", "; ".join(assessment.reasons))
        reassigned = await self.orchestrator.reassign_task(
            organization_id, run_id, task_id, agent_id=UUID(assessment.new_agent_id), actor=actor)
        record_metric("reassignments_total")
        return {"task_id": str(reassigned.id), "agent_id": assessment.new_agent_id,
                "reasons": assessment.reasons,
                "attempts_preserved": assessment.attempts_preserved}

    async def replace_worker(
        self, organization_id: UUID, run_id: UUID, task_id: UUID, *,
        manager_agent_id: UUID, actor: Optional[UUID] = None,
    ) -> Dict[str, Any]:
        """Worker replacement: only authorized task context transfers."""
        result = await self.reassign_with_rules(
            organization_id, run_id, task_id, manager_agent_id=manager_agent_id, actor=actor)
        run = await self.orchestrator.get_run(organization_id, run_id)
        await self._record_run_event(
            run, "TASK_REASSIGNED", task_id, UUID(result["agent_id"]),
            {"reason": "worker_replacement", "manager": str(manager_agent_id)})
        await self.db.commit()
        record_metric("agent_replacements")
        return result

    # -- handoffs ------------------------------------------------------------
    async def prepare_handoff(
        self, organization_id: UUID, run_id: UUID, task_id: UUID, *,
        source_agent_id: Optional[UUID] = None, target_agent_id: Optional[UUID] = None,
        mode: str = "full_handoff", package: Dict[str, Any],
        contract_id: Optional[UUID] = None, actor: Optional[UUID] = None,
        idempotency_key: Optional[str] = None,
    ) -> HandoffPackage:
        if idempotency_key:
            existing = await self.handoffs.get_by_idempotency_key(organization_id, idempotency_key)
            if existing:
                return existing
        run = await self.orchestrator.get_run(organization_id, run_id)
        task = await self.orchestrator.tasks.get_by_id_with_org(task_id, organization_id)
        if task is None or task.orchestration_run_id != run.id:
            raise OrchestrationError("NOT_FOUND", "task not found in run")
        if source_agent_id:
            await self._require_agent(organization_id, source_agent_id)
        if target_agent_id:
            await self._require_agent(organization_id, target_agent_id)
            if target_agent_id == source_agent_id:
                raise OrchestrationError("SELF_HANDOFF", "self-handoff is not allowed")
        try:
            handoff_mode = HandoffMode(mode)
        except ValueError:
            raise OrchestrationError("INVALID_MODE", f"unknown handoff mode: {mode}")
        structured = StructuredHandoff(
            source_agent_id=str(source_agent_id) if source_agent_id else None,
            target_agent_id=str(target_agent_id) if target_agent_id else None,
            task_id=str(task.id), objective=run.objective,
            completed_work=dict(package.get("completed_work", {}) or {}),
            pending_work=dict(package.get("pending_work", {}) or {}),
            decisions=list(package.get("decisions", []) or []),
            assumptions=list(package.get("assumptions", []) or []),
            constraints=list(package.get("constraints", []) or []),
            references=list(package.get("references", []) or []),
            warnings=list(package.get("warnings", []) or []),
            known_failures=list(package.get("known_failures", []) or []),
            acceptance_criteria=list(package.get("acceptance_criteria", []) or []),
            next_action=str(package.get("next_action", "")),
            mode=handoff_mode,
            relevant_context=dict(package.get("relevant_context", {}) or {}),
        )
        for artifact in package.get("artifacts", []) or []:
            from openagent.management.handoff import HandoffArtifact

            if isinstance(artifact, dict):
                try:
                    size = int(artifact.get("size_bytes", 0) or 0)
                except (ValueError, TypeError):
                    raise OrchestrationError("INVALID_HANDOFF", "artifact size_bytes must be a number")
                structured.artifacts.append(HandoffArtifact(
                    kind=str(artifact.get("kind", "file")),
                    name=str(artifact.get("name", "")),
                    reference=str(artifact.get("reference", "")),
                    size_bytes=size,
                ))
        try:
            built = build_structured_handoff(structured)
        except ValueError as exc:
            raise OrchestrationError("INVALID_HANDOFF", str(exc))
        manifest = built.pop("context_manifest")
        row = await self.handoffs.create(
            organization_id=organization_id, orchestration_run_id=run.id, task_id=task.id,
            contract_id=contract_id, source_agent_id=source_agent_id,
            target_agent_id=target_agent_id, mode=handoff_mode.value, package=built,
            context_manifest=manifest, status=HandoffPackageStatus.PREPARING,
            idempotency_key=idempotency_key,
        )
        # PREPARING -> PENDING_ACCEPTANCE (validated above).
        row.status = HandoffPackageStatus.PENDING_ACCEPTANCE
        await self._record_run_event(
            run, "HANDOFF_PREPARED", task.id, source_agent_id,
            {"handoff_id": str(row.id), "mode": handoff_mode.value})
        await self.db.flush()
        # Route through the communication service (policy + budget + audit).
        await self.communication.send(
            organization_id=organization_id, orchestration_run_id=run.id,
            sender_agent_id=source_agent_id, recipient_agent_id=target_agent_id,
            channel=ChannelType.DIRECT,
            policy=ChannelPolicy(allowed_channels=[ChannelType.DIRECT, ChannelType.MANAGER]),
            message_type="handoff_request", payload={"handoff_id": str(row.id)},
            task_id=task.id, kind="handoff",
        )
        await self._audit(organization_id, actor, "management.handoff_prepare",
                          "handoff_package", row.id)
        await self.db.commit()
        record_metric("handoffs_total")
        return row

    async def transition_handoff(
        self, organization_id: UUID, handoff_id: UUID, to: HandoffPackageStatus, *,
        actor: Optional[UUID] = None,
    ) -> HandoffPackage:
        row = await self.handoffs.get_by_id_with_org(handoff_id, organization_id)
        if row is None:
            raise OrchestrationError("NOT_FOUND", "handoff not found")
        current = HandoffStatus(row.status.value)
        target = HandoffStatus(to.value)
        if not can_transition_handoff(current, target):
            raise OrchestrationError(
                "INVALID_TRANSITION",
                f"cannot transition handoff {current.value} -> {target.value}")
        now = datetime.now(timezone.utc)
        # Source task stays incomplete until the target accepts (unless policy
        # explicitly allows auto-complete on prepare — it does not by default).
        if target == HandoffStatus.ACCEPTED:
            row.accepted_at = now
            # Mirror into the MP13 handoff record for backward compatibility.
            await self.orchestrator.handoff_task(
                organization_id, row.orchestration_run_id, row.task_id,
                from_agent_id=row.source_agent_id, to_agent_id=row.target_agent_id,
                package={
                    "completed_work": (row.package or {}).get("completed_work", {}),
                    "artifacts": (row.package or {}).get("artifacts", []),
                    "relevant_context": (row.package or {}).get("relevant_context", {}),
                    "constraints": (row.package or {}).get("constraints", []),
                    "warnings": (row.package or {}).get("warnings", []),
                    "expected_next_action": (row.package or {}).get("next_action", ""),
                },
                actor=actor,
            )
        if target == HandoffStatus.COMPLETED:
            row.completed_at = now
        row.status = to
        try:
            run = await self.orchestrator.get_run(organization_id, row.orchestration_run_id)
            await self._record_run_event(
                run, f"HANDOFF_{target.value.upper()}", row.task_id,
                row.target_agent_id, {"handoff_id": str(row.id)})
        except OrchestrationError:
            pass
        await self._audit(organization_id, actor, f"management.handoff_{target.value}",
                          "handoff_package", row.id)
        await self.db.commit()
        if target in (HandoffStatus.REJECTED, HandoffStatus.EXPIRED):
            record_metric("handoffs_failed")
        return row

    # -- reviews ---------------------------------------------------------------
    async def submit_review(
        self, organization_id: UUID, run_id: UUID, task_id: UUID, *,
        reviewer_agent_id: Optional[UUID] = None, output: Optional[Dict[str, Any]] = None,
        status_override: Optional[str] = None, actor: Optional[UUID] = None,
    ) -> ReviewResult:
        from openagent.management.types import AcceptanceCriterion

        run = await self.orchestrator.get_run(organization_id, run_id)
        task = await self.orchestrator.tasks.get_by_id_with_org(task_id, organization_id)
        if task is None or task.orchestration_run_id != run.id:
            raise OrchestrationError("NOT_FOUND", "task not found in run")
        if reviewer_agent_id:
            await self._require_agent(organization_id, reviewer_agent_id)
        contracts = await self.contracts.list_by_task(task.id)
        criteria = []
        max_revisions = 3
        if contracts:
            latest = contracts[0]
            max_revisions = latest.max_revisions
            for item in latest.acceptance_criteria or []:
                if isinstance(item, dict):
                    criteria.append(AcceptanceCriterion(
                        description=str(item.get("description", "")),
                        verification=str(item.get("verification", ""))))
        previous = await self.reviews.list_by_task(task.id)
        revision_number = len(previous)
        if revision_number >= max_revisions and not status_override:
            raise OrchestrationError("REVISIONS_EXHAUSTED",
                                     f"max revisions ({max_revisions}) exceeded; escalate instead")
        result = verify_acceptance(
            criteria, sanitize_dict(dict(output or task.output or {})),
            reviewer_agent_id=str(reviewer_agent_id) if reviewer_agent_id else None,
            revision_number=revision_number,
        )
        if status_override:
            try:
                result.status = ReviewStatus(status_override)
            except ValueError:
                raise OrchestrationError("INVALID_STATUS", f"unknown review status: {status_override}")
        gate = await RuleBasedQualityGate().evaluate(
            output=sanitize_dict(dict(output or {})), review=result)
        row = await self.reviews.create(
            organization_id=organization_id, orchestration_run_id=run.id, task_id=task.id,
            reviewer_agent_id=reviewer_agent_id, status=ReviewResultStatus(result.status.value),
            criteria_results=[
                {"description": c.description, "satisfied": c.satisfied, "evidence": c.evidence}
                for c in result.criteria_results
            ],
            issues=list(result.issues), required_changes=list(result.required_changes),
            evidence=list(result.evidence), revision_number=revision_number,
            gate_result=gate.value,
        )
        await self._record_run_event(
            run, "REVIEW_SUBMITTED", task.id, reviewer_agent_id,
            {"review_id": str(row.id), "status": result.status.value, "gate": gate.value})
        if result.status == ReviewStatus.REVISION_REQUIRED:
            await self._record_run_event(
                run, "REVISION_REQUESTED", task.id, reviewer_agent_id,
                {"review_id": str(row.id), "changes": result.required_changes})
            record_metric("revision_cycles")
        await self._audit(organization_id, actor, f"management.review_{result.status.value}",
                          "review_result", row.id)
        await self.db.commit()
        return row

    # -- escalations ---------------------------------------------------------------
    async def open_escalation(
        self, organization_id: UUID, *,
        source_agent_id: Optional[UUID] = None, task_id: Optional[UUID] = None,
        run_id: Optional[UUID] = None, trigger: str = "blocked", reason: str = "",
        severity: str = "warning", recommended_action: str = "",
        chain: Optional[List[str]] = None, actor: Optional[UUID] = None,
        idempotency_key: Optional[str] = None,
    ) -> Escalation:
        if idempotency_key:
            existing = await self.escalations.get_by_idempotency_key(organization_id, idempotency_key)
            if existing:
                return existing
        try:
            sev = EscalationSeverity(severity)
        except ValueError:
            raise OrchestrationError("INVALID_SEVERITY", f"unknown severity: {severity}")
        request = EscalationRequest(
            source_agent_id=str(source_agent_id) if source_agent_id else None,
            task_id=str(task_id) if task_id else None, reason=reason, trigger=trigger,
            severity=sev, recommended_action=recommended_action,
        )
        errors = validate_escalation(request)
        if errors:
            raise OrchestrationError("INVALID_ESCALATION", "; ".join(errors))
        if source_agent_id:
            await self._require_agent(organization_id, source_agent_id)
        routing = route_escalation(
            request, EscalationPolicyConfig(), current_level=0, chain=chain)
        holder: Optional[UUID] = None
        if routing.target in ("manager", "senior_manager", "ceo") and task_id and run_id:
            holder = await self._find_manager_for_task(organization_id, task_id)
        row = await self.escalations.create(
            organization_id=organization_id, orchestration_run_id=run_id, task_id=task_id,
            source_agent_id=source_agent_id, current_holder_agent_id=holder,
            trigger=trigger, reason=reason[:4000], severity=sev.value,
            status=EscalationStatus.OPEN, chain=chain or ["manager", "senior_manager", "ceo", "human"],
            chain_level=routing.level, recommended_action=recommended_action[:2000],
            history=[{"event": "opened", "target": routing.target,
                      "at": datetime.now(timezone.utc).isoformat()}],
            idempotency_key=idempotency_key,
        )
        if routing.human_required:
            approval = Approval(
                organization_id=organization_id, approval_type=ApprovalType.AGENT_ACTION,
                status=ApprovalStatus.PENDING, requested_by=actor,
                payload=sanitize_dict({
                    "escalation_id": str(row.id), "trigger": trigger,
                    "severity": sev.value, "reason": reason[:2000],
                    "task_id": str(task_id) if task_id else None,
                    "run_id": str(run_id) if run_id else None,
                }),
            )
            self.db.add(approval)
            await self.db.flush()
            row.human_approval_id = approval.id
        if run_id:
            try:
                run = await self.orchestrator.get_run(organization_id, run_id)
                await self._record_run_event(
                    run, "ESCALATION_OPENED", task_id, source_agent_id,
                    {"escalation_id": str(row.id), "severity": sev.value,
                     "target": routing.target})
            except OrchestrationError:
                pass
        await self._audit(organization_id, actor, "management.escalation_open",
                          "escalation", row.id)
        await self.db.commit()
        record_metric("escalations_total")
        return row

    async def transition_escalation(
        self, organization_id: UUID, escalation_id: UUID, to: EscalationStatus, *,
        note: str = "", actor: Optional[UUID] = None,
    ) -> Escalation:
        row = await self.escalations.get_by_id_with_org(escalation_id, organization_id)
        if row is None:
            raise OrchestrationError("NOT_FOUND", "escalation not found")
        from openagent.management.types import EscalationStatus as DomainStatus

        current = DomainStatus(row.status.value)
        target = DomainStatus(to.value)
        if not can_transition_escalation(current, target):
            raise OrchestrationError(
                "INVALID_TRANSITION",
                f"cannot transition escalation {current.value} -> {target.value}")
        if target == DomainStatus.ESCALATED:
            chain = list(row.chain or ["manager", "senior_manager", "ceo", "human"])
            nxt = min(row.chain_level + 1, len(chain) - 1)
            row.chain_level = nxt
            history = list(row.history or [])
            history.append({"event": "chained", "target": chain[nxt],
                            "at": datetime.now(timezone.utc).isoformat(), "note": note[:500]})
            row.history = history
            if row.orchestration_run_id:
                try:
                    run = await self.orchestrator.get_run(organization_id, row.orchestration_run_id)
                    await self._record_run_event(
                        run, "ESCALATION_CHAINED", row.task_id, row.current_holder_agent_id,
                        {"escalation_id": str(row.id), "level": nxt, "target": chain[nxt]})
                except OrchestrationError:
                    pass
        if target == DomainStatus.RESOLVED:
            row.resolved_at = datetime.now(timezone.utc)
        row.status = to
        history = list(row.history or [])
        history.append({"event": target.value, "note": note[:500],
                        "at": datetime.now(timezone.utc).isoformat()})
        row.history = history
        await self._audit(organization_id, actor, f"management.escalation_{target.value}",
                          "escalation", row.id)
        await self.db.commit()
        return row

    async def _parent_deadline(
        self, organization_id: UUID, task_id: UUID,
    ) -> Optional[datetime]:
        """Latest contract deadline for a task (parent constraint)."""
        contracts = await self.contracts.list_by_task(task_id)
        for contract in contracts:
            if contract.organization_id == organization_id and contract.deadline:
                deadline = contract.deadline
                if deadline.tzinfo is None:
                    deadline = deadline.replace(tzinfo=timezone.utc)
                return deadline
        return None

    async def _find_manager_for_task(
        self, organization_id: UUID, task_id: UUID,
    ) -> Optional[UUID]:
        # Manager resolution: prefer the task's supervising chain via
        # relationships (MANAGES / CAN_REVIEW) — fallback None (chain target).
        from openagent.db.models.orchestration import AgentRelationship

        task = await self.orchestrator.tasks.get_by_id(task_id)
        if task is None or not task.assigned_agent_id:
            return None
        result = await self.db.execute(
            select(AgentRelationship).where(
                AgentRelationship.organization_id == organization_id,
                AgentRelationship.target_agent_id == task.assigned_agent_id,
                AgentRelationship.relationship_type.in_(["manages", "can_review"]),
            ).limit(1)
        )
        rel = result.scalar_one_or_none()
        return rel.source_agent_id if rel else None

    # -- teams -------------------------------------------------------------------
    async def create_team(
        self, organization_id: UUID, *,
        name: str, manager_agent_id: Optional[UUID] = None,
        team_type: str = "temporary", run_id: Optional[UUID] = None,
        task_id: Optional[UUID] = None, department_id: Optional[UUID] = None,
        charter: Optional[Dict[str, Any]] = None, budget: Optional[Dict[str, Any]] = None,
        actor: Optional[UUID] = None, idempotency_key: Optional[str] = None,
    ) -> DynamicTeam:
        if idempotency_key:
            existing = await self.teams.get_by_idempotency_key(organization_id, idempotency_key)
            if existing:
                return existing
        try:
            dtype = DynamicTeamType(team_type)
        except ValueError:
            raise OrchestrationError("INVALID_TEAM_TYPE", f"unknown team type: {team_type}")
        if manager_agent_id:
            await self._require_agent(organization_id, manager_agent_id)
            # Authority: only managers with CAN_CREATE_TEAM (or team_policy allow).
            try:
                profile = await self._require_profile(organization_id, manager_agent_id)
                data = self._profile_data(profile)
                if data.team_policy == "deny":
                    raise OrchestrationError("AUTHORITY_DENIED", "team creation denied by policy")
                decision = check_authority(data, ManagerAuthority.CAN_CREATE_TEAM)
                if not decision.allowed and data.team_policy != "allow":
                    raise OrchestrationError("AUTHORITY_DENIED", "; ".join(decision.reasons))
            except OrchestrationError as exc:
                if exc.code not in ("NOT_MANAGER", "MANAGER_SUSPENDED"):
                    raise
        team = await self.teams.create(
            organization_id=organization_id, orchestration_run_id=run_id, task_id=task_id,
            manager_agent_id=manager_agent_id, department_id=department_id,
            name=name[:255], team_type=dtype.value, status=DynamicTeamStatus.CREATED,
            budget=sanitize_dict(dict(budget or {})), idempotency_key=idempotency_key,
        )
        if charter:
            await self.charters.create(
                organization_id=organization_id, team_id=team.id,
                objective=str(charter.get("objective", name))[:4000],
                scope=str(charter.get("scope", ""))[:2000],
                responsibilities=dict(charter.get("responsibilities", {}) or {}),
                communication_rules=list(charter.get("communication_rules", []) or []),
                completion_criteria=list(charter.get("completion_criteria", []) or []),
                budget=sanitize_dict(dict(charter.get("budget", {}) or {})),
            )
        if run_id:
            try:
                run = await self.orchestrator.get_run(organization_id, run_id)
                await self._record_run_event(
                    run, "TEAM_CREATED", task_id, manager_agent_id,
                    {"team_id": str(team.id), "name": name})
            except OrchestrationError:
                pass
        await self._audit(organization_id, actor, "management.team_create",
                          "dynamic_team", team.id)
        await self.db.commit()
        record_metric("team_creation_total")
        return team

    async def transition_team(
        self, organization_id: UUID, team_id: UUID, to: DynamicTeamStatus, *,
        actor: Optional[UUID] = None,
    ) -> DynamicTeam:
        from openagent.management.types import TeamStatus as DomainStatus

        team = await self.teams.get_by_id_with_org(team_id, organization_id)
        if team is None:
            raise OrchestrationError("NOT_FOUND", "team not found")
        current = DomainStatus(team.status.value)
        target = DomainStatus(to.value)
        if not can_transition_team(current, target):
            raise OrchestrationError(
                "INVALID_TRANSITION",
                f"cannot transition team {current.value} -> {target.value}")
        if target == DomainStatus.COMPLETED:
            pending = 0
            if team.orchestration_run_id:
                run_tasks = await self.orchestrator.tasks.list_by_run(
                    team.orchestration_run_id, limit=10000)
                pending = sum(
                    1 for t in run_tasks
                    if t.status.value not in ("succeeded", "failed", "skipped",
                                              "cancelled", "timed_out"))
            errors = validate_dissolution(current, pending)
            if errors:
                raise OrchestrationError("INVALID_STATE", "; ".join(errors))
        team.status = to
        if team.orchestration_run_id:
            try:
                run = await self.orchestrator.get_run(organization_id, team.orchestration_run_id)
                await self._record_run_event(
                    run, f"TEAM_{target.value.upper()}", team.task_id,
                    team.manager_agent_id, {"team_id": str(team.id)})
            except OrchestrationError:
                pass
        await self._audit(organization_id, actor, f"management.team_{target.value}",
                          "dynamic_team", team.id)
        await self.db.commit()
        return team

    async def add_member(
        self, organization_id: UUID, team_id: UUID, agent_id: UUID, *,
        role: str = "worker", responsibilities: Optional[List[str]] = None,
        actor: Optional[UUID] = None,
    ) -> DynamicTeamMembership:
        team = await self.teams.get_by_id_with_org(team_id, organization_id)
        if team is None:
            raise OrchestrationError("NOT_FOUND", "team not found")
        if team.status.value not in ("created", "forming", "active"):
            raise OrchestrationError("INVALID_STATE", "team is not accepting members")
        await self._require_agent(organization_id, agent_id)
        members = await self.memberships.list_by_team(team.id)
        active = [m for m in members if m.status == "active"]
        profile_limit = 12
        if team.manager_agent_id:
            try:
                profile = await self._require_profile(organization_id, team.manager_agent_id)
                profile_limit = self._profile_data(profile).max_team_size
            except OrchestrationError:
                pass
        if len(active) >= profile_limit:
            raise OrchestrationError("TEAM_FULL", f"team size limit ({profile_limit}) reached")
        existing = next((m for m in members if m.agent_id == agent_id), None)
        if existing is not None:
            if existing.status == "active":
                return existing
            existing.status = TeamMembershipStatus.ACTIVE.value
            existing.role = role
            await self.db.commit()
            return existing
        row = await self.memberships.create(
            organization_id=organization_id, team_id=team.id, agent_id=agent_id,
            role=role, responsibilities=list(responsibilities or []),
            status=TeamMembershipStatus.ACTIVE.value,
        )
        await self._audit(organization_id, actor, "management.team_member_add",
                          "dynamic_team_membership", row.id)
        await self.db.commit()
        return row

    async def remove_member(
        self, organization_id: UUID, team_id: UUID, agent_id: UUID, *,
        actor: Optional[UUID] = None,
    ) -> DynamicTeamMembership:
        team = await self.teams.get_by_id_with_org(team_id, organization_id)
        if team is None:
            raise OrchestrationError("NOT_FOUND", "team not found")
        members = await self.memberships.list_by_team(team.id)
        row = next((m for m in members if m.agent_id == agent_id), None)
        if row is None:
            raise OrchestrationError("NOT_FOUND", "membership not found")
        row.status = TeamMembershipStatus.REMOVED.value
        await self._audit(organization_id, actor, "management.team_member_remove",
                          "dynamic_team_membership", row.id)
        await self.db.commit()
        return row

    async def form_team_from_roles(
        self, organization_id: UUID, request: TeamFormationRequest, *,
        run_id: Optional[UUID] = None, manager_agent_id: Optional[UUID] = None,
        actor: Optional[UUID] = None,
    ) -> Dict[str, Any]:
        from openagent.orchestration.discovery import discover_agents

        by_role: Dict[str, List[AgentCandidate]] = {}
        for role, capabilities in request.required_roles.items():
            agents = await discover_agents(
                self.db, organization_id=organization_id, capabilities=None, limit=100)
            candidates = []
            for agent in agents:
                meta = getattr(agent, "metadata", None) or {}
                caps = meta.get("capabilities") or meta.get("advertised_capabilities") or []
                avail = await self.availability.get_by_agent(agent.id)
                candidates.append(AgentCandidate(
                    agent_id=str(agent.id),
                    capabilities=[str(c) for c in caps] if isinstance(caps, list) else [],
                    active_tasks=avail.active_tasks if avail else 0,
                    healthy=(avail.state if avail else "available") not in (
                        "offline", "disabled", "unhealthy"),
                ))
            by_role[role] = candidates
        formed: FormedTeam = form_team(request, by_role)
        # Budget inheritance (§73): member shares subdivide the team budget
        # and can never exceed the parent allocation.
        total_budget = float((request.budget or {}).get("total", 0.0) or 0.0)
        shares = split_budget(total_budget, [1.0] * max(1, len(formed.members)))
        member_budgets = {
            member.agent_id: share for member, share in zip(formed.members, shares)
        }
        # Deadline propagation (§74): stagger member deadlines within the
        # charter window; none may extend the parent deadline.
        member_deadlines: Dict[str, str] = {}
        charter_deadline = (request.charter.deadline if request.charter else None)
        if charter_deadline and formed.members:
            try:
                parent = datetime.fromisoformat(charter_deadline)
                deadlines = allocate_deadlines(parent, [1.0] * len(formed.members))
                member_deadlines = {
                    member.agent_id: deadlines[i].isoformat()
                    for i, member in enumerate(formed.members)
                }
            except ValueError:
                pass
        team = await self.create_team(
            organization_id, name=f"team-{request.objective[:40]}",
            manager_agent_id=manager_agent_id, team_type=request.team_type.value,
            run_id=run_id,
            charter={"objective": request.objective,
                     "completion_criteria": (request.charter.completion_criteria
                                             if request.charter else [])},
            budget=dict(request.budget or {}), actor=actor,
        )
        # Activate: CREATED -> FORMING -> ACTIVE.
        team.status = DynamicTeamStatus.FORMING
        await self.db.flush()
        for member in formed.members:
            await self.memberships.create(
                organization_id=organization_id, team_id=team.id,
                agent_id=UUID(member.agent_id), role=member.role,
                responsibilities=list(member.responsibilities),
                status=TeamMembershipStatus.ACTIVE.value,
            )
        if not formed.uncovered_roles:
            team.status = DynamicTeamStatus.ACTIVE
        await self.db.commit()
        return {"team_id": str(team.id), "status": team.status.value,
                "members": [{"agent_id": m.agent_id, "role": m.role,
                             "budget_share": member_budgets.get(m.agent_id, 0.0),
                             "deadline": member_deadlines.get(m.agent_id)}
                            for m in formed.members],
                "uncovered_roles": formed.uncovered_roles, "reasons": formed.reasons}

    # -- plan versions -----------------------------------------------------------
    async def record_plan_version(
        self, organization_id: UUID, run_id: UUID, *,
        reason: str, snapshot: Dict[str, Any], changes: Optional[List[str]] = None,
        created_by_agent_id: Optional[UUID] = None, actor: Optional[UUID] = None,
    ) -> PlanVersion:
        run = await self.orchestrator.get_run(organization_id, run_id)
        latest = await self.versions.latest_version(run.id)
        row = await self.versions.create(
            organization_id=organization_id, orchestration_run_id=run.id,
            version=latest + 1, reason=reason[:2000],
            created_by_agent_id=created_by_agent_id,
            changes=list(changes or []),
            parent_version=latest or None,
            plan_snapshot=sanitize_dict(dict(snapshot or {})),
        )
        await self._record_run_event(
            run, "PLAN_VERSION_CREATED", None, created_by_agent_id,
            {"version": row.version, "reason": reason[:500]})
        await self._audit(organization_id, actor, "management.plan_version",
                          "plan_version", row.id)
        await self.db.commit()
        return row

    # -- collaboration / commitments / progress ------------------------------------
    async def request_collaboration(
        self, organization_id: UUID, run_id: UUID, *,
        from_agent_id: UUID, to_agent_id: UUID, action: str,
        task_id: Optional[UUID] = None, payload: Optional[Dict[str, Any]] = None,
        actor: Optional[UUID] = None,
    ) -> CollaborationRequest:
        try:
            act = CollaborationAction(action)
        except ValueError:
            raise OrchestrationError("INVALID_ACTION", f"unknown collaboration action: {action}")
        proposal = CollaborationProposal(
            action=act, from_agent_id=str(from_agent_id), to_agent_id=str(to_agent_id),
            task_id=str(task_id) if task_id else None,
            payload=sanitize_dict(dict(payload or {})),
        )
        errors = validate_collaboration(proposal)
        if errors:
            raise OrchestrationError("INVALID_COLLABORATION", "; ".join(errors))
        await self._require_agent(organization_id, from_agent_id)
        await self._require_agent(organization_id, to_agent_id)
        ok, reason = self.communication.budget.check_kind("collaboration")
        if not ok:
            raise OrchestrationError("BUDGET_EXHAUSTED", reason)
        row = await self.collaborations.create(
            organization_id=organization_id, orchestration_run_id=run_id, task_id=task_id,
            from_agent_id=from_agent_id, to_agent_id=to_agent_id,
            action=act.value, payload=proposal.payload, status="pending",
        )
        self.communication.budget.record_kind("collaboration")
        await self._audit(organization_id, actor, "management.collaboration_request",
                          "collaboration_request", row.id)
        await self.db.commit()
        return row

    async def transition_collaboration(
        self, organization_id: UUID, collaboration_id: UUID, to: str, *,
        actor: Optional[UUID] = None,
    ) -> CollaborationRequest:
        row = await self.collaborations.get_by_id_with_org(collaboration_id, organization_id)
        if row is None:
            raise OrchestrationError("NOT_FOUND", "collaboration not found")
        allowed = {
            "pending": {"accepted", "declined", "cancelled"},
            "accepted": {"completed", "cancelled"},
            "declined": set(), "completed": set(), "cancelled": set(),
        }
        if to not in allowed.get(row.status, set()):
            raise OrchestrationError(
                "INVALID_TRANSITION", f"cannot transition collaboration {row.status} -> {to}")
        row.status = to
        if to == "accepted":
            record_metric("manager_decisions_total")
        await self._audit(organization_id, actor, f"management.collaboration_{to}",
                          "collaboration_request", row.id)
        await self.db.commit()
        return row

    async def report_progress(
        self, organization_id: UUID, run_id: UUID, task_id: UUID, *,
        agent_id: UUID, report: Dict[str, Any],
    ) -> Dict[str, Any]:
        run = await self.orchestrator.get_run(organization_id, run_id)
        task = await self.orchestrator.tasks.get_by_id_with_org(task_id, organization_id)
        if task is None or task.orchestration_run_id != run.id:
            raise OrchestrationError("NOT_FOUND", "task not found in run")
        progress = sanitize_progress(report)
        if progress.blocked and progress.blocked_reason:
            await self._record_run_event(
                run, "TASK_PROGRESS", task.id, agent_id,
                {"progress": progress.progress, "blocked": True,
                 "blocked_reason": progress.blocked_reason.value,
                 "current_step": progress.current_step[:500]})
            # Blocked tasks surface to the manager console; auto-escalation
            # only for configured triggers.
            if progress.blocked_reason.value in ("missing_permission", "dependency_failure"):
                await self.open_escalation(
                    organization_id, source_agent_id=agent_id, task_id=task.id,
                    run_id=run.id, trigger="blocked",
                    reason=f"blocked: {progress.blocked_reason.value} — {progress.current_step[:500]}",
                    severity="warning", recommended_action="manager triage",
                )
                await self.db.commit()
        else:
            await self._record_run_event(
                run, "TASK_PROGRESS", task.id, agent_id,
                {"progress": progress.progress, "status": progress.status,
                 "current_step": progress.current_step[:500]})
            await self.db.commit()
        return {"progress": progress.progress, "blocked": progress.blocked,
                "blocked_reason": progress.blocked_reason.value if progress.blocked_reason else None}

    # -- availability / capacity -----------------------------------------------------
    async def set_availability(
        self, organization_id: UUID, agent_id: UUID, state: str, *,
        actor: Optional[UUID] = None,
    ) -> AgentAvailability:
        from openagent.management.types import AvailabilityState

        try:
            AvailabilityState(state)
        except ValueError:
            raise OrchestrationError("INVALID_STATE", f"unknown availability: {state}")
        await self._require_agent(organization_id, agent_id)
        row = await self.availability.get_by_agent(agent_id)
        if row is None:
            row = await self.availability.create(
                organization_id=organization_id, agent_id=agent_id, state=state)
        else:
            row.state = state
        await self._audit(organization_id, actor, "management.availability_set",
                          "agent_availability", row.id)
        await self.db.commit()
        return row

    async def set_capacity(
        self, organization_id: UUID, agent_id: UUID, values: Dict[str, Any], *,
        actor: Optional[UUID] = None,
    ) -> AgentCapacity:
        await self._require_agent(organization_id, agent_id)
        row = await self.capacity.get_by_agent(agent_id)
        allowed = {"max_concurrent_tasks", "max_concurrent_runs", "max_daily_cost", "max_token_budget"}
        clean = {k: v for k, v in values.items() if k in allowed}
        if row is None:
            row = await self.capacity.create(
                organization_id=organization_id, agent_id=agent_id, **clean)
        else:
            for key, value in clean.items():
                setattr(row, key, value)
        await self._audit(organization_id, actor, "management.capacity_set",
                          "agent_capacity", row.id)
        await self.db.commit()
        return row

    # -- departments -------------------------------------------------------------------
    async def create_department(
        self, organization_id: UUID, name: str, *,
        description: str = "", actor: Optional[UUID] = None,
    ) -> AgentDepartment:
        from openagent.management.workforce import BUILTIN_DEPARTMENTS

        slug = name.strip().lower().replace(" ", "_")[:128]
        if not slug:
            raise OrchestrationError("INVALID_NAME", "department name must not be empty")
        existing = await self.departments.get_by_slug(organization_id, slug)
        if existing:
            return existing
        _ = BUILTIN_DEPARTMENTS
        row = await self.departments.create(
            organization_id=organization_id, name=name[:128], slug=slug,
            description=description[:2000])
        await self._audit(organization_id, actor, "management.department_create",
                          "agent_department", row.id)
        await self.db.commit()
        return row

    # -- decisions / loop tick --------------------------------------------------------------
    async def record_decision(
        self, organization_id: UUID, *,
        manager_agent_id: Optional[UUID] = None, run_id: Optional[UUID] = None,
        task_id: Optional[UUID] = None, decision_type: str = "general",
        selected_action: str = "", alternatives: Optional[List[str]] = None,
        policy_basis: str = "", rationale: str = "",
        actor: Optional[UUID] = None,
    ) -> ManagerDecision:
        row = await self.decisions.create(
            organization_id=organization_id, orchestration_run_id=run_id,
            manager_agent_id=manager_agent_id, task_id=task_id,
            decision_type=decision_type[:64], selected_action=selected_action[:128],
            alternatives=list(alternatives or []), policy_basis=policy_basis[:2000],
            rationale=rationale[:2000],
        )
        await self._audit(organization_id, actor, "management.decision_record",
                          "manager_decision", row.id)
        await self.db.commit()
        record_metric("manager_decisions_total")
        return row

    async def manager_tick(
        self, organization_id: UUID, run_id: UUID, manager_agent_id: UUID, *,
        actor: Optional[UUID] = None,
    ) -> Dict[str, Any]:
        """Drive one controlled manager-loop step from live run state."""
        profile = await self._require_profile(organization_id, manager_agent_id)
        _ = self._profile_data(profile)
        run = await self.orchestrator.get_run(organization_id, run_id)
        tasks = await self.orchestrator.tasks.list_by_run(run.id, limit=10000)
        blocked = sum(1 for t in tasks if (t.task_metadata or {}).get("blocked"))
        failed = sum(1 for t in tasks if t.status.value in ("failed", "timed_out"))
        active = sum(1 for t in tasks if t.status.value in ("running", "assigned", "ready"))
        delegations = await self.delegations.list_by_run(run.id, limit=1000)
        pending_delegations = sum(1 for d in delegations if d.status.value == "pending")
        open_escalations = await self.escalations.list_open(organization_id, limit=1000)
        observation = LoopObservation(
            active_tasks=active, blocked_tasks=blocked, failed_tasks=failed,
            pending_delegations=pending_delegations,
            open_escalations=len([e for e in open_escalations
                                  if not e.orchestration_run_id or e.orchestration_run_id == run.id]),
        )
        loop = ManagerDecisionLoop()
        state = ManagerLoopState_()
        # Resume: the last recorded decision's outcome is this tick's start.
        from openagent.management.types import ManagerLoopState as LoopStateEnum

        decisions = await self.decisions.list_by_run(run.id, limit=50)
        for decision in decisions:
            try:
                state.state = LoopStateEnum(decision.selected_action)
                break
            except ValueError:
                continue
        state.decisions = min(len(decisions), 50)
        step = loop.step(state, observation)
        loop.apply(state, step)
        recorded = await self.record_decision(
            organization_id, manager_agent_id=manager_agent_id, run_id=run.id,
            decision_type=f"loop:{step.action}", selected_action=step.next_state.value,
            policy_basis="manager_loop", rationale=step.reason, actor=actor,
        )
        # Corrective hooks: expired delegations, failure-matrix escalation.
        expired = 0
        for delegation in delegations:
            if delegation.status.value == "pending" and delegation_expired(delegation.expires_at):
                delegation.status = DelegationRequestStatus.EXPIRED
                expired += 1
        if expired:
            await self.db.commit()
        if failed:
            action = apply_failure_matrix(failed, list(DEFAULT_FAILURE_MATRIX))
            if action in ("escalate", "immediate_escalate"):
                await self.open_escalation(
                    organization_id, source_agent_id=manager_agent_id, run_id=run.id,
                    trigger="repeated_failure",
                    reason=f"{failed} failed tasks under manager supervision",
                    severity="high" if action == "escalate" else "critical",
                    recommended_action="manager triage",
                )
                await self.db.commit()
        return {"state": state.state.value, "action": step.action,
                "reason": step.reason, "decision_id": str(recorded.id),
                "observation": {"active": active, "blocked": blocked, "failed": failed,
                                "pending_delegations": pending_delegations},
                "expired_delegations": expired}

    async def recover_manager(
        self, organization_id: UUID, failed_manager_id: UUID, *,
        replacement_manager_id: UUID, run_id: Optional[UUID] = None,
        actor: Optional[UUID] = None,
    ) -> Dict[str, Any]:
        """Manager recovery: child tasks never disappear; they reattach to the
        replacement manager via supervised reassignment."""
        await self._require_agent(organization_id, failed_manager_id)
        await self._require_agent(organization_id, replacement_manager_id)
        profile = await self.profiles.get_by_agent(organization_id, failed_manager_id)
        if profile:
            profile.status = ManagerProfileStatus.SUSPENDED
        moved = 0
        if run_id:
            tasks = await self.orchestrator.tasks.list_by_run(run_id, limit=10000)
            for task in tasks:
                if task.assigned_agent_id == failed_manager_id and task.status.value in (
                        "created", "ready", "assigned", "waiting", "paused"):
                    task.assigned_agent_id = replacement_manager_id
                    moved += 1
        await self._audit(organization_id, actor, "management.manager_recover",
                          "manager_profile", profile.id if profile else None)
        await self.db.commit()
        record_metric("manager_decisions_total")
        return {"moved_tasks": moved, "replacement": str(replacement_manager_id)}


def _caps_of(agent: Agent) -> List[str]:
    meta = getattr(agent, "metadata", None) or {}
    caps = meta.get("capabilities") or meta.get("advertised_capabilities") or []
    return [str(c) for c in caps] if isinstance(caps, list) else []
