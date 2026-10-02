"""Centralized, explainable risk engine (MP19).

Pure function: deterministic, no I/O, no model input trusted beyond the
structured ActionContext built server-side by the platform.
"""

from __future__ import annotations

from openagent.approvals.taxonomy import HIGH_RISK_DEFAULTS
from openagent.approvals.types import ActionContext, RiskAssessment, RiskLevel

_ORDER = [RiskLevel.NONE, RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL]

_TRUST_SCORE = {"CORE": 0, "VERIFIED": 5, "ORGANIZATION": 10, "COMMUNITY": 20, "UNTRUSTED": 35}


def _bump(score: int, delta: int) -> int:
    return max(0, min(100, score + delta))


def evaluate_risk(ctx: ActionContext) -> RiskAssessment:
    score = 0
    reasons: list[str] = []

    def add(delta: int, reason: str) -> None:
        nonlocal score
        score = _bump(score, delta)
        reasons.append(reason)

    # Environment
    if ctx.environment == "production":
        add(30, "Production environment")
    elif ctx.environment == "staging":
        add(10, "Staging environment")

    # Effect class
    if ctx.destructive:
        add(30, "Destructive operation")
    if ctx.external_side_effect:
        add(20, "External side effect")
    if ctx.financial_impact:
        add(25, "Financial impact")
    if ctx.credential_usage:
        add(30, "Credential usage")
    if ctx.network_access:
        add(10, "Network access")
    if ctx.data_sensitivity == "restricted":
        add(25, "Restricted data")
    elif ctx.data_sensitivity == "confidential":
        add(15, "Confidential data")

    # Privilege / scope
    if ctx.privilege_level == "platform":
        add(35, "Platform privilege level")
    elif ctx.privilege_level == "admin":
        add(20, "Admin privilege level")
    elif ctx.privilege_level == "elevated":
        add(10, "Elevated privilege level")
    if ctx.tenant_scope in ("organization", "cross_tenant", "platform"):
        add(15 if ctx.tenant_scope == "organization" else 25,
            f"Tenant scope: {ctx.tenant_scope}")
    if ctx.reversibility == "irreversible":
        add(15, "Irreversible action")
    elif ctx.reversibility == "reversible_with_effort":
        add(7, "Reversible with effort")
    if ctx.affected_resources > 10:
        add(15, f"Affects {ctx.affected_resources} resources")
    elif ctx.affected_resources > 1:
        add(5, f"Affects {ctx.affected_resources} resources")

    # Trust of the acting stack (platform-assigned, never model-assigned).
    trust_penalties: list[tuple[int, str]] = []
    for label, trust in (("agent", ctx.agent_trust), ("tool", ctx.tool_trust),
                         ("mcp", ctx.mcp_trust)):
        delta = _TRUST_SCORE.get((trust or "ORGANIZATION").upper(), 10)
        if delta >= 20:
            trust_penalties.append((delta - 10, f"Low {label} trust ({trust})"))

    if ctx.sandbox_profile.upper() in ("FULL_OUTBOUND", "PRIVILEGED", "UNRESTRICTED"):
        add(15, f"Sandbox profile {ctx.sandbox_profile} widens blast radius")

    # Category floor from conservative defaults
    floor = HIGH_RISK_DEFAULTS.get((ctx.action_category or "").upper(), {})
    floor_level = str(floor.get("min_risk", "NONE"))
    floor_score = {"NONE": 0, "LOW": 1, "MEDIUM": 40, "HIGH": 70,
                   "CRITICAL": 90}.get(floor_level, 0)
    if floor_score > score:
        score = floor_score
        reasons.append(f"Category {ctx.action_category} minimum risk {floor_level}")

    # Unknown action categories deny-by-default: force at least HIGH.
    from openagent.approvals.taxonomy import is_known_category
    if not is_known_category(ctx.action_category or ""):
        if score < 70:
            score = 70
        reasons.append("Unknown action category (deny-by-default)")

    # Unverified callers (unknown tools) deny-by-default: force at least HIGH.
    if ctx.untrusted_origin:
        if score < 70:
            score = 70
        reasons.append("Unverified tool origin (deny-by-default)")

    # Low trust escalates above the floor (never hidden beneath it).
    for delta, reason in trust_penalties:
        add(delta, reason)

    level = RiskLevel.from_score(score)
    # Deduplicate reasons while preserving order.
    seen: set[str] = set()
    ordered = [r for r in reasons if not (r in seen or seen.add(r))]
    return RiskAssessment(risk_level=level, risk_score=score, reasons=ordered)
