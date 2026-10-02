"""Approval delegation validation (MP19). Delegates can never exceed the
delegator's authority; delegation is scoped and time-bound."""

from __future__ import annotations

from datetime import datetime, timezone


def validate_delegation(*, delegator_permissions: set[str], scope: str,
                        expires_at: datetime | None,
                        requested_permission: str = "approval:approve") -> list[str]:
    errors: list[str] = []
    if requested_permission not in delegator_permissions and "*" not in delegator_permissions:
        errors.append("Delegator lacks the delegated permission")
    if not (scope or "").strip():
        errors.append("Delegation scope is required")
    if expires_at is None:
        errors.append("Delegation must have an expiration")
    else:
        exp = expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=timezone.utc)
        if exp <= datetime.now(timezone.utc):
            errors.append("Delegation is expired")
    return errors
