"""Manager profile and authority enforcement.

A manager is an Agent Runtime entity with explicitly granted authority.
Authority never implies RBAC bypass: every management operation still passes
through authorization checks in the service layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from openagent.management.types import AgentScope, DelegationPolicy, ManagerAuthority


@dataclass
class ManagerProfile:
    agent_id: str
    label: str = "manager"  # ceo | executive | manager | lead ... (not hard-coded)
    managed_capabilities: List[str] = field(default_factory=list)
    delegation_policy: DelegationPolicy = DelegationPolicy.HYBRID
    review_required: bool = True
    escalation_policy: str = "default"
    team_policy: str = "allow"  # allow | deny | approval_required
    budget_share: float = 1.0  # fraction of parent allocation this manager may spend
    max_workers: int = 20
    max_depth: int = 5
    max_direct_reports: int = 10
    max_active_tasks: int = 30
    max_delegations: int = 100
    max_replans: int = 3
    max_team_size: int = 12
    allowed_actions: Set[ManagerAuthority] = field(
        default_factory=lambda: {
            ManagerAuthority.CAN_DELEGATE,
            ManagerAuthority.CAN_REVIEW,
            ManagerAuthority.CAN_REQUEST_REVISION,
            ManagerAuthority.CAN_ESCALATE,
        }
    )
    scope: AgentScope = AgentScope.ORGANIZATION
    department_id: Optional[str] = None
    team_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AuthorityDecision:
    allowed: bool
    reasons: List[str]


def check_authority(
    profile: ManagerProfile,
    action: ManagerAuthority,
    *,
    target_scope: Optional[AgentScope] = None,
    target_department_id: Optional[str] = None,
    target_team_id: Optional[str] = None,
    cross_team_allowed: bool = False,
) -> AuthorityDecision:
    """Pure authority check: profile actions + scope boundaries."""
    if action not in profile.allowed_actions:
        return AuthorityDecision(False, [f"action {action.value} not granted to {profile.label}"])

    # Scope enforcement: a manager only supervises its configured scope.
    if target_scope is not None and not _scope_covers(
        profile.scope, target_scope,
        profile.department_id, target_department_id,
        profile.team_id, target_team_id,
        cross_team_allowed,
    ):
        return AuthorityDecision(False, ["target outside manager scope"])
    return AuthorityDecision(True, [f"{action.value} authorized within scope"])


def _scope_covers(
    manager_scope: AgentScope,
    target_scope: AgentScope,
    manager_dept: Optional[str],
    target_dept: Optional[str],
    manager_team: Optional[str],
    target_team: Optional[str],
    cross_team_allowed: bool,
) -> bool:
    order = {
        AgentScope.PLATFORM: 4,
        AgentScope.ORGANIZATION: 3,
        AgentScope.DEPARTMENT: 2,
        AgentScope.TEAM: 1,
        AgentScope.PRIVATE: 0,
    }
    if manager_scope == AgentScope.PLATFORM:
        # Platform scope still does not grant platform-admin rights; it only
        # covers coordination visibility. Actual permissions come from RBAC.
        return True
    if order.get(manager_scope, 0) < order.get(target_scope, 0):
        return False
    if manager_scope == AgentScope.DEPARTMENT and target_scope == AgentScope.DEPARTMENT:
        return manager_dept is not None and manager_dept == target_dept
    if manager_scope == AgentScope.TEAM:
        if target_team is None or manager_team is None:
            return False
        if manager_team != target_team and not cross_team_allowed:
            return False
    if target_scope == AgentScope.PRIVATE:
        return False  # private agent resources never auto-visible
    return True


def is_root_label(label: str) -> bool:
    return label.strip().lower() in {"ceo", "executive", "root manager", "root", "lead agent", "orchestrator"}
