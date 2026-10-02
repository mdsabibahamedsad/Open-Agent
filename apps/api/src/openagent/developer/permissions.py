"""MP28: extension permission enforcement (§26) + trust model (§27).

Security invariants enforced here (§86):
1-4. Extensions cannot bypass RBAC / ABAC / security policy / human approval.
5-6. Execution must pass through Tool Runtime / Sandbox where required.
10. Extensions cannot silently obtain broader permissions.
Trust never bypasses authorization: CORE == VERIFIED == COMMUNITY at the
policy gate; trust only affects review priority and default sandbox profile.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from openagent.developer.types import (
    HIGH_RISK_PERMISSIONS,
    PERMISSION_CATALOG,
    TrustLevel,
)


@dataclass(frozen=True)
class PermissionDecision:
    allowed: bool
    denied: list[str] = field(default_factory=list)
    requires_approval: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


def check_permissions(
    requested: list[str],
    *,
    granted: list[str],
    trust: str = TrustLevel.UNTRUSTED.value,
    approvals_present: bool = False,
) -> PermissionDecision:
    """Decide whether `requested` permissions are covered by `granted`.

    - Unknown permissions are always denied.
    - Any requested permission outside `granted` is denied (no self-grant).
    - High-risk permissions additionally require an approval record unless
      the extension is CORE/VERIFIED/ORGANIZATION trust.
    """
    denied: list[str] = []
    needs_approval: list[str] = []
    reasons: list[str] = []
    granted_set = set(granted)

    for perm in requested:
        if perm not in PERMISSION_CATALOG:
            denied.append(perm)
            reasons.append(f"unknown permission '{perm}'")
            continue
        if perm not in granted_set:
            denied.append(perm)
            reasons.append(f"permission '{perm}' was not granted to this installation")
            continue
        meta = PERMISSION_CATALOG[perm]
        if perm in HIGH_RISK_PERMISSIONS and trust in (
            TrustLevel.COMMUNITY.value,
            TrustLevel.UNTRUSTED.value,
        ):
            if not approvals_present:
                needs_approval.append(perm)
                reasons.append(
                    f"high-risk permission '{perm}' requires human approval "
                    f"for trust level {trust}"
                )
        elif bool(meta.get("requires_approval")) and not approvals_present:
            # Approval-gated even for trusted publishers when no approval
            # record exists for this installation.
            needs_approval.append(perm)
            reasons.append(f"permission '{perm}' requires an approval record")
    return PermissionDecision(
        allowed=not denied and not needs_approval,
        denied=denied,
        requires_approval=needs_approval,
        reasons=reasons,
    )


def least_privilege_suggestions(requested: list[str], used: list[str]) -> list[str]:
    """Suggest permissions to drop (requested but never exercised)."""
    return sorted(set(requested) - set(used))


def approval_gates_for(permissions: list[str]) -> list[str]:
    """Permissions in the request that always need an approval record."""
    return [p for p in permissions if p in HIGH_RISK_PERMISSIONS]


def trust_rank(trust: str) -> int:
    order = ["UNTRUSTED", "COMMUNITY", "ORGANIZATION", "VERIFIED", "CORE"]
    try:
        return order.index(trust)
    except ValueError:
        return -1
