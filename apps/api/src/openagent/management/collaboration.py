"""Collaboration, negotiation, commitments, progress, blocked states."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from openagent.management.types import (
    NON_NEGOTIABLE_FIELDS,
    NEGOTIABLE_FIELDS,
    BlockedReason,
    CollaborationAction,
    ProgressReport,
)

MANAGER_RESPONSES = frozenset(
    {
        "provide_input",
        "grant_authorized_access",
        "delegate",
        "retry",
        "replan",
        "escalate",
        "cancel",
    }
)


@dataclass
class CollaborationProposal:
    action: CollaborationAction
    from_agent_id: str
    to_agent_id: str
    task_id: Optional[str] = None
    payload: Dict[str, Any] = field(default_factory=dict)
    # Ownership never transfers via collaboration.
    transfer_ownership: bool = False


def validate_collaboration(proposal: CollaborationProposal) -> List[str]:
    errors: List[str] = []
    if proposal.transfer_ownership:
        errors.append("collaboration cannot transfer task ownership; use handoff")
    if proposal.from_agent_id == proposal.to_agent_id:
        errors.append("self-collaboration is not allowed")
    return errors


@dataclass
class NegotiationBid:
    agent_id: str
    task_id: str
    terms: Dict[str, Any] = field(default_factory=dict)


@dataclass
class NegotiationResult:
    selected_agent_id: Optional[str]
    reasons: List[str]
    rejected: List[str] = field(default_factory=list)


def negotiate(bids: List[NegotiationBid], *, policy: str = "lowest_effort") -> NegotiationResult:
    """Limited negotiation over availability/effort/completion only.
    Agents can never negotiate permissions — such terms are stripped and the
    bid is rejected."""
    valid: List[NegotiationBid] = []
    rejected: List[str] = []
    for bid in bids:
        terms = dict(bid.terms or {})
        if any(k in NON_NEGOTIABLE_FIELDS for k in terms):
            rejected.append(bid.agent_id)
            continue
        negotiable = {k: v for k, v in terms.items() if k in NEGOTIABLE_FIELDS}
        valid.append(NegotiationBid(agent_id=bid.agent_id, task_id=bid.task_id, terms=negotiable))
    if not valid:
        return NegotiationResult(None, ["no valid bids"], rejected)
    if policy == "lowest_effort":
        valid.sort(key=lambda b: (float(b.terms.get("estimated_effort", 1e9)), b.agent_id))
    elif policy == "earliest_completion":
        valid.sort(key=lambda b: (str(b.terms.get("expected_completion", "9999")), b.agent_id))
    else:  # availability_first
        availability_rank = {"available": 0, "busy": 1}
        valid.sort(
            key=lambda b: (availability_rank.get(str(b.terms.get("availability", "busy")), 2),
                           b.agent_id)
        )
    winner = valid[0]
    return NegotiationResult(
        winner.agent_id,
        [f"policy={policy}", f"terms={sorted(winner.terms)}"],
        rejected,
    )


@dataclass
class Commitment:
    task_id: str
    agent_id: str
    deadline: Optional[datetime] = None
    budget: Dict[str, Any] = field(default_factory=dict)
    expected_output: str = ""
    accepted_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def check_commitment(commitment: Commitment, *, now: Optional[datetime] = None) -> str:
    """Return commitment health: on_track | overdue."""
    if commitment.deadline is None:
        return "on_track"
    ref = now or datetime.now(timezone.utc)
    deadline = commitment.deadline
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    return "overdue" if ref > deadline else "on_track"


def sanitize_progress(report: Dict[str, Any]) -> ProgressReport:
    """Progress is informational — never authoritative completion proof."""
    blocked_reason = report.get("blocked_reason")
    try:
        reason = BlockedReason(blocked_reason) if blocked_reason else None
    except ValueError:
        reason = None
    return ProgressReport(
        progress=float(report.get("progress", 0.0) or 0.0),
        status=str(report.get("status", "running")),
        current_step=str(report.get("current_step", "")),
        blocked=bool(report.get("blocked", False)),
        blocked_reason=reason,
    ).clamped()
