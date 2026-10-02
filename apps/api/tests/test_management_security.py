"""Security tests for the management layer (MP14). Pure domain, no DB."""

from __future__ import annotations

from openagent.management.authority import ManagerProfile, check_authority
from openagent.management.collaboration import negotiate, NegotiationBid
from openagent.management.delegations import DelegationProposal, select_delegate
from openagent.management.handoff import StructuredHandoff, build_structured_handoff
from openagent.management.messaging import ChannelPolicy, ChannelType, authorize_channel
from openagent.management.types import (
    AgentScope,
    ContextTransferRule,
    DelegationPolicy,
    ManagerAuthority,
)
from openagent.orchestration.assignment import AgentCandidate


def test_cross_team_delegation_denied_by_default():
    profile = ManagerProfile(
        agent_id="m", label="manager", scope=AgentScope.TEAM, team_id="t1",
        allowed_actions={ManagerAuthority.CAN_DELEGATE},
    )
    decision = check_authority(
        profile, ManagerAuthority.CAN_DELEGATE,
        target_scope=AgentScope.TEAM, target_team_id="t2",
        cross_team_allowed=False)
    assert not decision.allowed


def test_manager_cannot_bypass_rbac_actions():
    profile = ManagerProfile(agent_id="m", label="ceo", scope=AgentScope.ORGANIZATION)
    # CEO label alone grants no extra actions.
    assert not check_authority(profile, ManagerAuthority.CAN_CREATE_TEAM).allowed
    assert not check_authority(profile, ManagerAuthority.CAN_CANCEL_CHILD).allowed


def test_private_context_never_leaves():
    handoff = StructuredHandoff(
        source_agent_id="a", target_agent_id="b", task_id="t", objective="o",
        completed_work={"ok": True}, next_action="go",
        relevant_context={"session_cookie": "abc", "password": "hunter2"},
        context_rule=ContextTransferRule.TASK_ONLY,
    )
    built = build_structured_handoff(handoff, task_keys=set(), team_keys=set())
    assert built["relevant_context"] == {}
    assert set(built["context_manifest"]["excluded_items"]) == {"session_cookie", "password"}


def test_handoff_secrets_redacted_not_leaked():
    handoff = StructuredHandoff(
        source_agent_id="a", target_agent_id="b", task_id="t", objective="o",
        completed_work={"token": "Bearer abcdefgh12345"},
        next_action="go",
        relevant_context={"note": "Bearer abcdefgh12345 inside text"},
    )
    built = build_structured_handoff(handoff, task_keys={"note"}, team_keys=set())
    blob = str(built)
    assert "abcdefgh12345" not in blob


def test_negotiation_cannot_grant_permissions_or_scope():
    bids = [NegotiationBid(agent_id="a", task_id="t",
                           terms={"scope": "platform", "budget_override": 999})]
    result = negotiate(bids)
    assert result.selected_agent_id is None


def test_escalation_channel_restricted():
    policy = ChannelPolicy()
    assert not authorize_channel(ChannelType.ESCALATION, policy).allowed
    assert authorize_channel(
        ChannelType.ESCALATION, policy, is_escalation_target=True).allowed


def test_delegation_selects_only_allowed_candidates():
    candidates = [
        AgentCandidate(agent_id="rogue", capabilities=["x"], allowed=False),
        AgentCandidate(agent_id="good", capabilities=["x"], allowed=True),
    ]
    proposal = DelegationProposal(
        source_agent_id="m", task_id="t", required_capabilities=["x"],
        policy=DelegationPolicy.CAPABILITY_BASED)
    assert select_delegate(proposal, candidates).target_agent_id == "good"


def test_contract_permissions_are_requirements_not_grants():
    from openagent.management.contracts import contract_from_dict, validate_contract

    contract = contract_from_dict({
        "objective": "o",
        "responsibilities": ["r"],
        "expected_outputs": {"x": 1},
        "permissions": ["tool:deploy"],
        "acceptance_criteria": [{"description": "d"}],
    })
    assert validate_contract(contract).valid
    # The contract records what is *required*; granting happens in RBAC.
    assert contract.permissions == ["tool:deploy"]
