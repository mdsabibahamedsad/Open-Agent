"""Unit tests for the management layer (MP14). Pure domain, no DB."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from openagent.management.authority import ManagerProfile, check_authority, is_root_label
from openagent.management.collaboration import (
    CollaborationProposal,
    negotiate,
    NegotiationBid,
    sanitize_progress,
    validate_collaboration,
)
from openagent.management.contracts import (
    AgentContract,
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
    classify_context,
)
from openagent.management.manager_loop import (
    LoopObservation,
    ManagerDecisionLoop,
    ManagerLoopState,
    LoopBudgetExceeded,
    should_replan,
)
from openagent.management.messaging import (
    ChannelPolicy,
    ChannelType,
    MessageBudget,
    RateLimiter,
    authorize_channel,
)
from openagent.management.prompts import build_manager_prompt, compress_messages, ManagerPromptContext
from openagent.management.review import (
    RuleBasedQualityGate,
    verify_acceptance,
)
from openagent.management.teams import (
    TeamCharter,
    TeamFormationRequest,
    form_team,
    split_budget,
    validate_dissolution,
)
from openagent.management.types import (
    AcceptanceCriterion,
    AgentScope,
    CollaborationAction,
    ContextTransferRule,
    DelegationPolicy,
    DelegationStatus,
    DynamicTeamType,
    EscalationPolicyConfig,
    EscalationSeverity,
    EscalationStatus,
    HandoffMode,
    HandoffStatus,
    ManagerAuthority,
    ManagerLoopBudget,
    QualityGateResult,
    ReviewStatus,
    TeamStatus,
    can_transition_delegation,
    can_transition_escalation,
    can_transition_handoff,
    can_transition_team,
)
from openagent.management.workforce import (
    AgentCapacity,
    allocate_deadlines,
    availability_from_load,
    can_accept,
)
from openagent.orchestration.assignment import AgentCandidate


def _candidate(agent_id: str, caps: list[str], load: int = 0, **kwargs) -> AgentCandidate:
    return AgentCandidate(agent_id=agent_id, capabilities=caps, active_tasks=load, **kwargs)


# -- authority ---------------------------------------------------------------


def test_manager_authority_granted_and_scoped():
    profile = ManagerProfile(agent_id="m1", label="manager", scope=AgentScope.ORGANIZATION)
    decision = check_authority(profile, ManagerAuthority.CAN_DELEGATE)
    assert decision.allowed
    # Managers do not get CAN_CREATE_TEAM by default.
    denied = check_authority(profile, ManagerAuthority.CAN_CREATE_TEAM)
    assert not denied.allowed


def test_manager_scope_enforcement():
    profile = ManagerProfile(
        agent_id="m1", label="manager", scope=AgentScope.TEAM, team_id="t1",
        allowed_actions={ManagerAuthority.CAN_DELEGATE},
    )
    ok = check_authority(
        profile, ManagerAuthority.CAN_DELEGATE,
        target_scope=AgentScope.TEAM, target_team_id="t1")
    assert ok.allowed
    cross = check_authority(
        profile, ManagerAuthority.CAN_DELEGATE,
        target_scope=AgentScope.TEAM, target_team_id="t2")
    assert not cross.allowed
    private = check_authority(
        profile, ManagerAuthority.CAN_REVIEW, target_scope=AgentScope.PRIVATE)
    assert not private.allowed


def test_root_labels():
    assert is_root_label("CEO")
    assert is_root_label("root manager")
    assert not is_root_label("worker")


# -- contracts -----------------------------------------------------------------


def test_contract_valid_and_invalid():
    good = AgentContract(
        objective="Build API",
        responsibilities=["implement endpoints"],
        expected_outputs={"api": "running"},
        acceptance_criteria=[AcceptanceCriterion(description="tests pass")],
    )
    assert validate_contract(good).valid
    bad = AgentContract(objective="", responsibilities=[],
                        inputs={"api_key": "secret!"})
    result = validate_contract(bad)
    assert not result.valid
    assert any("secret" in e.lower() for e in result.errors)


def test_contract_roundtrip():
    contract = AgentContract(
        objective="o", responsibilities=["r"], expected_outputs={"x": 1},
        acceptance_criteria=[AcceptanceCriterion(description="d", verification="field_present:x")],
    )
    data = contract_from_dict(__import__("openagent.management.contracts", fromlist=["contract_to_dict"]).contract_to_dict(contract))
    assert data.objective == "o"


# -- delegation ------------------------------------------------------------------


def test_delegation_explicit_only():
    candidates = [_candidate("a1", ["coding.python"]), _candidate("a2", ["coding.python"])]
    proposal = DelegationProposal(
        source_agent_id="m", task_id="t", required_capabilities=["coding.python"],
        policy=DelegationPolicy.EXPLICIT_ONLY)
    assert select_delegate(proposal, candidates).target_agent_id is None
    proposal.explicit_target_id = "a2"
    assert select_delegate(proposal, candidates).target_agent_id == "a2"


def test_delegation_load_aware_picks_lighter():
    candidates = [_candidate("busy", ["x"], load=5), _candidate("free", ["x"], load=0)]
    proposal = DelegationProposal(
        source_agent_id="m", task_id="t", required_capabilities=["x"],
        policy=DelegationPolicy.LOAD_AWARE)
    assert select_delegate(proposal, candidates).target_agent_id == "free"


def test_delegation_lifecycle_transitions():
    assert can_transition_delegation(DelegationStatus.PENDING, DelegationStatus.ACCEPTED)
    assert not can_transition_delegation(DelegationStatus.ACCEPTED, DelegationStatus.PENDING)
    assert not can_transition_delegation(DelegationStatus.COMPLETED, DelegationStatus.CANCELLED)


def test_reassignment_skips_untrusted_and_previous():
    candidates = [
        _candidate("prev", ["x"], metadata={"trust": "verified"}),
        _candidate("new", ["x"], metadata={"trust": "organization"}),
        _candidate("shady", ["x"], metadata={"trust": "untrusted"}),
    ]
    assessment = assess_reassignment(
        required_capabilities=["x"], candidates=candidates,
        previous_agent_id="prev", attempts=2)
    assert assessment.new_agent_id == "new"
    assert assessment.attempts_preserved == 2


def test_delegation_expiry():
    past = datetime.now(timezone.utc) - timedelta(seconds=1)
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    assert delegation_expired(past)
    assert not delegation_expired(future)
    assert not delegation_expired(None)


# -- handoff ----------------------------------------------------------------------


def test_handoff_manifest_and_redaction():
    handoff = StructuredHandoff(
        source_agent_id="a", target_agent_id="b", task_id="t", objective="o",
        completed_work={"done": True}, next_action="review",
        relevant_context={"api_key": "sk-123", "notes": "hello", "internal": "x"},
    )
    built = build_structured_handoff(
        handoff, task_keys={"api_key", "notes"}, team_keys=set())
    manifest = built["context_manifest"]
    assert "notes" in manifest["included_items"]
    assert "internal" in manifest["excluded_items"]
    assert "api_key" in manifest["redacted_items"]
    assert built["relevant_context"]["api_key"] == "[REDACTED]"


def test_handoff_private_never_transfers():
    transferred, manifest = classify_context(
        {"secret": "x", "note": "y"}, ContextTransferRule.PRIVATE,
        task_keys={"secret", "note"})
    assert transferred == {}
    assert set(manifest.excluded_items) == {"secret", "note"}


def test_handoff_full_requires_next_action():
    handoff = StructuredHandoff(
        source_agent_id="a", target_agent_id="b", task_id="t", objective="o")
    with pytest.raises(ValueError):
        build_structured_handoff(handoff)


def test_handoff_lifecycle_transitions():
    assert can_transition_handoff(HandoffStatus.PREPARING, HandoffStatus.PENDING_ACCEPTANCE)
    assert can_transition_handoff(HandoffStatus.PENDING_ACCEPTANCE, HandoffStatus.ACCEPTED)
    assert not can_transition_handoff(HandoffStatus.PREPARING, HandoffStatus.ACCEPTED)
    assert not can_transition_handoff(HandoffStatus.COMPLETED, HandoffStatus.CANCELLED)


# -- review -------------------------------------------------------------------------


def test_review_verifies_criteria():
    criteria = [AcceptanceCriterion(description="has api", verification="field_present:api")]
    approved = verify_acceptance(criteria, {"api": "running"})
    assert approved.status == ReviewStatus.APPROVED
    assert all(c.satisfied for c in approved.criteria_results)
    revision = verify_acceptance(criteria, {"other": 1})
    assert revision.status == ReviewStatus.REVISION_REQUIRED
    assert revision.required_changes == ["has api"]


def test_review_manual_criteria_need_approval():
    criteria = [AcceptanceCriterion(description="looks good", verification="manual")]
    result = verify_acceptance(criteria, {"anything": True})
    assert result.status == ReviewStatus.REVISION_REQUIRED


def test_quality_gate():
    gate = RuleBasedQualityGate()
    approved = verify_acceptance([], {})
    assert asyncio.run(gate.evaluate(output={}, review=approved)) == QualityGateResult.PASS


# -- escalation -----------------------------------------------------------------------


def test_escalation_routing_and_chain():
    request = EscalationRequest(
        source_agent_id="w", task_id="t", reason="blocked on input",
        trigger="blocked", severity=EscalationSeverity.HIGH)
    assert validate_escalation(request) == []
    routing = route_escalation(request, EscalationPolicyConfig())
    assert routing.target == "manager"
    critical = EscalationRequest(
        source_agent_id="w", task_id="t", reason="breach",
        trigger="high_risk_action", severity=EscalationSeverity.CRITICAL)
    routing = route_escalation(critical, EscalationPolicyConfig())
    assert routing.human_required


def test_escalation_bad_trigger():
    request = EscalationRequest(
        source_agent_id="w", task_id="t", reason="", trigger="nope")
    assert len(validate_escalation(request)) == 2


def test_failure_matrix():
    from openagent.management.types import DEFAULT_FAILURE_MATRIX

    assert apply_failure_matrix(1, list(DEFAULT_FAILURE_MATRIX)) == "retry"
    assert apply_failure_matrix(2, list(DEFAULT_FAILURE_MATRIX)) == "reassign"
    assert apply_failure_matrix(5, list(DEFAULT_FAILURE_MATRIX)) == "escalate"
    assert apply_failure_matrix(1, list(DEFAULT_FAILURE_MATRIX), policy_violation=True) == "immediate_escalate"


def test_escalation_transitions():
    assert can_transition_escalation(EscalationStatus.OPEN, EscalationStatus.ACKNOWLEDGED)
    assert can_transition_escalation(EscalationStatus.IN_PROGRESS, EscalationStatus.ESCALATED)
    assert not can_transition_escalation(EscalationStatus.CLOSED, EscalationStatus.OPEN)


# -- teams -----------------------------------------------------------------------------


def test_team_formation_covers_roles():
    pool = {
        "backend": [_candidate("be", ["coding.python"])],
        "frontend": [_candidate("fe", ["coding.react"])],
        "qa": [],
    }
    formed = form_team(
        TeamFormationRequest(
            objective="ship", required_roles={
                "backend": ["coding.python"], "frontend": ["coding.react"],
                "qa": ["testing.automation"]},
            team_type=DynamicTeamType.TEMPORARY),
        pool,
    )
    assert {m.role for m in formed.members} == {"backend", "frontend"}
    assert formed.uncovered_roles == ["qa"]


def test_team_transitions_and_dissolution():
    assert can_transition_team(TeamStatus.CREATED, TeamStatus.FORMING)
    assert can_transition_team(TeamStatus.WINDING_DOWN, TeamStatus.COMPLETED)
    assert not can_transition_team(TeamStatus.ACTIVE, TeamStatus.COMPLETED)
    assert validate_dissolution(TeamStatus.WINDING_DOWN, 0) == []
    assert validate_dissolution(TeamStatus.ACTIVE, 0) != []
    assert validate_dissolution(TeamStatus.WINDING_DOWN, 2) != []


def test_budget_split_never_exceeds_parent():
    assert split_budget(100.0, [60.0, 60.0]) == [50.0, 50.0]
    assert sum(split_budget(100.0, [20.0, 20.0, 20.0])) <= 100.0
    assert split_budget(90.0, []) == []


# -- manager loop --------------------------------------------------------------------------


def test_manager_loop_transitions():
    loop = ManagerDecisionLoop(ManagerLoopBudget(max_decisions=100))
    state = loop.initial()
    assert state.state == ManagerLoopState.OBSERVE
    step = loop.step(state, LoopObservation())
    assert step.next_state == ManagerLoopState.UNDERSTAND
    loop.apply(state, step)
    blocked = loop.step(state, LoopObservation(blocked_tasks=2))
    assert blocked.next_state == ManagerLoopState.CORRECT


def test_manager_loop_budget_enforced():
    loop = ManagerDecisionLoop(ManagerLoopBudget(max_decisions=1))
    state = loop.initial()
    step = loop.step(state, LoopObservation())
    loop.apply(state, step)
    with pytest.raises(LoopBudgetExceeded):
        loop.step(state, LoopObservation())


def test_should_replan():
    assert should_replan("task_failure", replans_used=0, max_replans=3)
    assert not should_replan("task_failure", replans_used=3, max_replans=3)
    assert not should_replan("unknown", replans_used=0, max_replans=3)


# -- collaboration ------------------------------------------------------------------------------


def test_collaboration_no_ownership_transfer():
    proposal = CollaborationProposal(
        action=CollaborationAction.REQUEST_REVIEW,
        from_agent_id="a", to_agent_id="b", transfer_ownership=True)
    assert validate_collaboration(proposal) != []


def test_negotiation_strips_permissions():
    bids = [
        NegotiationBid(agent_id="a", task_id="t",
                       terms={"estimated_effort": 5, "permissions": ["admin"]}),
        NegotiationBid(agent_id="b", task_id="t", terms={"estimated_effort": 10}),
    ]
    result = negotiate(bids)
    assert result.selected_agent_id == "b"
    assert result.rejected == ["a"]


def test_progress_is_informational():
    report = sanitize_progress({"progress": 2.5, "status": "running"})
    assert report.progress == 1.0
    blocked = sanitize_progress({"progress": 0.5, "blocked": True, "blocked_reason": "missing_input"})
    assert blocked.blocked_reason is not None


# -- messaging -------------------------------------------------------------------------------------


def test_channel_authorization():
    policy = ChannelPolicy()
    assert authorize_channel(ChannelType.DIRECT, policy).allowed
    assert not authorize_channel(ChannelType.BROADCAST, policy).allowed
    assert not authorize_channel(
        ChannelType.TEAM, policy, same_team=False).allowed
    assert authorize_channel(
        ChannelType.TEAM,
        ChannelPolicy(allowed_channels=[ChannelType.TEAM], allow_cross_team=True),
        same_team=False).allowed


def test_message_budget_backpressure():
    budget = MessageBudget(max_per_task=2)
    assert budget.check_message(task_id="t", agent_id="a", size_bytes=10)[0]
    budget.record_message(task_id="t", agent_id="a")
    budget.record_message(task_id="t", agent_id="a")
    assert not budget.check_message(task_id="t", agent_id="a", size_bytes=10)[0]
    assert not budget.check_message(task_id="x", agent_id="y", size_bytes=10**9)[0]


def test_rate_limiter():
    limiter = RateLimiter(per_minute=2)
    assert limiter.check("a")[0]
    assert limiter.check("a")[0]
    assert not limiter.check("a")[0]


# -- workforce -------------------------------------------------------------------------------------------------


def test_capacity_and_availability():
    capacity = AgentCapacity(max_concurrent_tasks=1, active_tasks=1)
    assert availability_from_load(capacity).value == "overloaded"
    ok, _ = can_accept(AgentCapacity(), estimated_cost=1.0)
    assert ok
    denied, _ = can_accept(AgentCapacity(max_daily_cost=1.0, daily_cost_used=1.0),
                           estimated_cost=0.5)
    assert not denied


def test_deadlines_within_parent():
    parent = datetime.now(timezone.utc) + timedelta(hours=2)
    deadlines = allocate_deadlines(parent, [1.0, 1.0])
    assert len(deadlines) == 2
    assert all(d <= parent for d in deadlines)
    assert deadlines[-1] == parent


# -- prompts -----------------------------------------------------------------------------------------------------------------


def test_manager_prompt_bounded_and_sanitized():
    context = ManagerPromptContext(
        system_policy="Be safe.",
        manager_role="engineering manager",
        objective="Ship API",
        active_tasks=[{"title": f"task {i}", "status": "running"} for i in range(50)],
        constraints=["no secrets"],
        budget_summary="$5 of $10",
        selected_messages=[{"message_type": "x", "payload": {"api_key": "sk-1"}}],
    )
    prompt = build_manager_prompt(context, max_tasks=5, max_chars=2000)
    assert "task 49" not in prompt
    assert "sk-1" not in prompt
    assert len(prompt) <= 2100


def test_compress_messages():
    messages = [{"message_type": "a"}] * 30 + [{"message_type": "b"}] * 5
    compressed = compress_messages(messages)
    assert compressed["total"] == 35
    assert compressed["by_type"] == {"a": 30, "b": 5}
