"""Declarative guardrail policy engine (MP19).

Precedence: platform > organization > team > agent > workflow > tool > request.
Higher levels can only make decisions MORE restrictive; a lower level can never
weaken a mandatory platform requirement. Policies are safe declarative dicts —
never executable code.

Policy rule shape:
  {"decision": "REQUIRE_APPROVAL"|"ALLOW"|"DENY"|"REQUIRE_MULTI_APPROVAL"|"REQUIRE_ESCALATION",
   "when": {"environment": "production", "risk_gte": "HIGH", ...},
   "approval_kind": "SINGLE", "required_role": "organization_owner",
   "required_approvals": 2, "reason": "...", "mandatory": true}
"""

from __future__ import annotations

from typing import Any, Optional

from openagent.approvals.types import (ActionContext, ApprovalKind, PolicyDecision,
                                        PolicyEvaluation, RiskAssessment, RiskLevel)

_LEVELS = ("platform", "organization", "team", "agent", "workflow", "tool", "request")

_RISK_ORDER = {"NONE": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}

_DECISION_RANK = {PolicyDecision.DENY: 4, PolicyDecision.REQUIRE_ESCALATION: 3,
                  PolicyDecision.REQUIRE_MULTI_APPROVAL: 2,
                  PolicyDecision.REQUIRE_APPROVAL: 1, PolicyDecision.ALLOW: 0}

# Platform mandatory baseline: cannot be weakened by lower levels.
# Most specific rules first: when several match with equal restrictiveness,
# the earliest (most specific) rule supplies approval_kind/required_role.
PLATFORM_BASELINE: list[dict[str, Any]] = [
    {"decision": "REQUIRE_APPROVAL", "approval_kind": "PLATFORM",
     "required_role": "platform_owner",
     "when": {"privilege_level": "platform"},
     "reason": "Platform guardrail: platform privilege requires platform owner",
     "mandatory": True},
    {"decision": "DENY",
     "when": {"action_category": "DELETE", "environment": "production",
              "target_type": "database"},
     "reason": "Platform guardrail: production database deletion is denied",
     "mandatory": True},
    {"decision": "REQUIRE_APPROVAL", "approval_kind": "SINGLE",
     "required_role": "organization_owner",
     "when": {"risk_gte": "HIGH"},
     "reason": "Platform guardrail: HIGH+ risk requires owner approval",
     "mandatory": True},
    {"decision": "REQUIRE_APPROVAL", "approval_kind": "SINGLE",
     "when": {"external_side_effect": True},
     "reason": "Platform guardrail: external side effects require approval",
     "mandatory": True},
    {"decision": "REQUIRE_APPROVAL", "approval_kind": "SINGLE",
     "when": {"financial_impact": True},
     "reason": "Platform guardrail: financial actions require approval",
     "mandatory": True},
    {"decision": "REQUIRE_APPROVAL", "approval_kind": "SINGLE",
     "when": {"credential_usage": True},
     "reason": "Platform guardrail: credential usage requires approval",
     "mandatory": True},
]

PLATFORM_VERSION = "platform-v1"


def _risk_gte(risk: RiskLevel, threshold: str) -> bool:
    return _RISK_ORDER[risk.value] >= _RISK_ORDER.get(threshold.upper(), 0)


def _match(when: dict[str, Any], ctx: ActionContext, risk: RiskAssessment) -> bool:
    for key, expected in when.items():
        if key == "risk_gte":
            if not _risk_gte(risk.risk_level, str(expected)):
                return False
            continue
        if key == "risk_lte":
            if _RISK_ORDER[risk.risk_level.value] > _RISK_ORDER.get(str(expected).upper(), 4):
                return False
            continue
        actual: Any = getattr(ctx, key, None)
        if isinstance(expected, bool):
            if bool(actual) is not expected:
                return False
        elif isinstance(expected, (list, tuple, set)):
            wanted = {str(v).lower() for v in expected}
            if str(actual or "").lower() not in wanted:
                return False
        else:
            if str(actual or "").lower() != str(expected).lower():
                return False
    return True


def _coerce_decision(raw: str) -> PolicyDecision:
    try:
        return PolicyDecision(str(raw).upper())
    except ValueError:
        return PolicyDecision.REQUIRE_APPROVAL


def evaluate_policies(*, ctx: ActionContext, risk: RiskAssessment,
                      policies_by_level: Optional[dict[str, list[dict[str, Any]]]] = None,
                      ) -> PolicyEvaluation:
    """Evaluate from highest to lowest precedence; most restrictive wins.

    A lower level may add restrictions but platform mandatory DENY decisions
    can never be downgraded — enforced structurally since we take the maximum
    restrictiveness across all matching rules.
    """
    merged: dict[str, list[dict[str, Any]]] = {"platform": list(PLATFORM_BASELINE)}
    for level, rules in (policies_by_level or {}).items():
        if level in _LEVELS and level != "platform":
            merged.setdefault(level, []).extend(rules or [])

    best = PolicyDecision.ALLOW
    best_rule: Optional[dict[str, Any]] = None
    best_level = "platform"
    matched_reasons: list[str] = []

    for level in _LEVELS:
        for rule in merged.get(level, []):
            when = rule.get("when", {}) or {}
            if not isinstance(when, dict) or not _match(when, ctx, risk):
                continue
            decision = _coerce_decision(rule.get("decision", "REQUIRE_APPROVAL"))
            matched_reasons.append(f"[{level}] {rule.get('reason', decision.value)}")
            if _DECISION_RANK[decision] > _DECISION_RANK[best]:
                best = decision
                best_rule = rule
                best_level = level

    kind = ApprovalKind.SINGLE
    required_role: Optional[str] = None
    required_approvals = 1
    if best_rule:
        try:
            kind = ApprovalKind(str(best_rule.get("approval_kind", "SINGLE")).upper())
        except ValueError:
            kind = ApprovalKind.SINGLE
        required_role = best_rule.get("required_role")
        try:
            required_approvals = max(1, int(best_rule.get("required_approvals", 1)))
        except (TypeError, ValueError):
            required_approvals = 1
        if best == PolicyDecision.REQUIRE_MULTI_APPROVAL and required_approvals < 2:
            required_approvals = 2

    # Unknown categories are deny-by-default at policy layer too.
    from openagent.approvals.taxonomy import is_known_category
    if not is_known_category(ctx.action_category or "") and best == PolicyDecision.ALLOW:
        best = PolicyDecision.REQUIRE_APPROVAL
        matched_reasons.append("[platform] Unknown action category requires approval")

    return PolicyEvaluation(decision=best, risk_level=risk.risk_level,
                            approval_kind=kind, required_role=required_role,
                            required_approvals=required_approvals,
                            reasons=matched_reasons,
                            policy_version=f"{PLATFORM_VERSION}+{best_level}")
