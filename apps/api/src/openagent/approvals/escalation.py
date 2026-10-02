"""Approval escalation chains (MP19). Policy-controlled, loop-free."""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_CHAIN = ("team_lead", "organization_admin", "organization_owner")
MAX_DEPTH = 5


@dataclass
class EscalationRule:
    after_seconds: int = 3600
    escalate_to: str = "organization_admin"
    max_depth: int = MAX_DEPTH


def next_escalation_target(*, current_chain: list[dict] | None,
                           rule: EscalationRule | None = None) -> str | None:
    rule = rule or EscalationRule()
    chain = current_chain or []
    if len(chain) >= min(rule.max_depth, MAX_DEPTH):
        return None  # no infinite loops; stays pending until expiry
    if not chain:
        return rule.escalate_to or DEFAULT_CHAIN[0]
    last = (chain[-1] or {}).get("to", "")
    if last in DEFAULT_CHAIN:
        idx = DEFAULT_CHAIN.index(last)
        if idx + 1 < len(DEFAULT_CHAIN):
            return DEFAULT_CHAIN[idx + 1]
        return None
    return rule.escalate_to
