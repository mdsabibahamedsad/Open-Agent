"""MP23: entitlement evaluation + install feature gate.

Marketplace package security and core authorization stay separate:
entitlements only answer "may this org install this listing commercially".
FREE listings always pass. Paid listings require an ACTIVE (or TRIAL, when
the product allows trials) entitlement covering the org (or user). When no
billing provider is configured, paid listings are uninstallable with an
explicit code — never silently free, never silently granted.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        moment = value
    else:
        try:
            moment = datetime.fromisoformat(str(value))
        except ValueError:
            return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def entitlement_is_live(entitlement: dict[str, Any],
                        *, now: datetime | None = None) -> tuple[bool, str]:
    """Check status + validity window. Returns (live, reason)."""
    status = str(entitlement.get("status", "")).upper()
    if status == "REVOKED":
        return False, "entitlement revoked"
    if status == "EXPIRED":
        return False, "entitlement expired"
    if status not in ("ACTIVE", "TRIAL"):
        return False, f"entitlement not active ({status or 'unknown'})"
    moment = now or datetime.now(timezone.utc)
    valid_until = _parse_dt(entitlement.get("valid_until"))
    if valid_until is not None and moment > valid_until:
        return False, "entitlement past valid_until"
    valid_from = _parse_dt(entitlement.get("valid_from"))
    if valid_from is not None and moment < valid_from:
        return False, "entitlement not yet valid"
    return True, "entitlement active"


def can_install_listing(
    *,
    pricing_model: str,
    entitlements: list[dict[str, Any]],
    organization_id: str = "",
    user_id: str = "",
    commerce_configured: bool = False,
    now: datetime | None = None,
) -> tuple[bool, str, str]:
    """Gate installation. Returns (allowed, code, message).

    Codes: OK_FREE, OK_ENTITLED, NEED_ENTITLEMENT, COMMERCE_DISABLED.
    Entitlements never grant runtime permissions — the installer and RBAC
    still enforce everything downstream.
    """
    model = str(pricing_model or "FREE").upper()
    if model == "FREE":
        return True, "OK_FREE", "free listing"
    live = [
        e for e in entitlements
        if (not organization_id or str(e.get("organization_id", "")) in ("", organization_id))
        and (not user_id or str(e.get("user_id", "")) in ("", user_id))
        and entitlement_is_live(e, now=now)[0]
    ]
    if live:
        return True, "OK_ENTITLED", "active entitlement"
    if not commerce_configured:
        return False, "COMMERCE_DISABLED", (
            "paid listing with no billing provider configured; "
            "purchase is unavailable")
    return False, "NEED_ENTITLEMENT", (
        "an active entitlement is required to install this listing")
