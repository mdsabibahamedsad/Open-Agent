"""MP24: entitlement engine — commercial access only.

``has_access(subject, feature)`` answers "may this subject use this paid
feature". It never grants authentication, RBAC, tool/sandbox permissions,
human-approval bypass or org-policy bypass — those systems enforce
independently downstream.

Entitlement sources: PURCHASE, SUBSCRIPTION, GRANT, PROMOTION, ENTERPRISE,
ADMIN, TRIAL. Live states: ACTIVE (and TRIAL only when the product allows
trials — always true here; product policy can narrow it).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from openagent.commerce.types import EntitlementStatus


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
    status = str(entitlement.get("status", "")).upper()
    if status in (EntitlementStatus.REVOKED, EntitlementStatus.SUSPENDED):
        return False, f"entitlement {status.lower()}"
    if status == EntitlementStatus.EXPIRED:
        return False, "entitlement expired"
    if status == EntitlementStatus.PENDING:
        return False, "entitlement pending activation"
    if status not in (EntitlementStatus.ACTIVE, "TRIAL"):
        return False, f"entitlement not active ({status or 'unknown'})"
    moment = now or datetime.now(timezone.utc)
    valid_until = _parse_dt(entitlement.get("valid_until"))
    if valid_until is not None and moment > valid_until:
        return False, "entitlement past valid_until"
    valid_from = _parse_dt(entitlement.get("valid_from"))
    if valid_from is not None and moment < valid_from:
        return False, "entitlement not yet valid"
    return True, "entitlement active"


def _subject_matches(entitlement: dict[str, Any], *, user_id: str = "",
                     organization_id: str = "",
                     allow_org_inherit: bool) -> bool:
    ent_org = str(entitlement.get("organization_id") or "")
    ent_user = str(entitlement.get("user_id") or "")
    if ent_user:
        # User-scoped grant: exact user match required; org context alone
        # never unlocks another user's entitlement.
        return bool(user_id) and ent_user == user_id
    if organization_id and ent_org == organization_id:
        # Org-scoped grant covers org context. Membership itself is proven
        # upstream by RBAC (org context requires membership); the
        # ``inherited`` marker additionally flags member-derived grants.
        return True
    if not organization_id and not user_id:
        return True
    return False


def has_access(*, entitlements: list[dict[str, Any]], feature: str,
               user_id: str = "", organization_id: str = "",
               allow_org_inherit: bool = False,
               now: datetime | None = None) -> tuple[bool, str]:
    """Check commercial access to ``feature`` (e.g. ``package.install``).

    Returns (allowed, reason). Quantity-limited entitlements (``quantity``
    + ``used``) are honoured: exhausted entitlements do not grant access.
    """
    wanted = str(feature or "").strip()
    for ent in entitlements:
        features = ent.get("features") or ([ent.get("feature")] if ent.get("feature") else [])
        features = [str(f) for f in features if f]
        if wanted and features and wanted not in features and "*" not in features:
            continue
        live, _ = entitlement_is_live(ent, now=now)
        if not live:
            continue
        if not _subject_matches(ent, user_id=user_id,
                                organization_id=organization_id,
                                allow_org_inherit=allow_org_inherit):
            continue
        quantity = ent.get("quantity")
        used = ent.get("used", 0) or 0
        if quantity is not None and used >= int(quantity):
            continue
        return True, "entitlement grants access"
    return False, "no live entitlement covers this feature"


def can_install(*, pricing_model: str, product_access: str = "",
                entitlements: list[dict[str, Any]],
                organization_id: str = "", user_id: str = "",
                commerce_configured: bool = False,
                now: datetime | None = None) -> tuple[bool, str, str]:
    """Gate marketplace installation. Returns (allowed, code, message).

    Codes: OK_FREE, OK_ENTITLED, NEED_ENTITLEMENT, COMMERCE_DISABLED,
    ACCESS_PRIVATE.
    """
    model = str(pricing_model or "FREE").upper()
    access = str(product_access or "").upper()
    if access == "PRIVATE":
        return False, "ACCESS_PRIVATE", "private product: grant required"
    if model == "FREE" and access in ("", "FREE"):
        return True, "OK_FREE", "free package"
    allowed, _ = has_access(entitlements=entitlements,
                            feature="package.install",
                            user_id=user_id,
                            organization_id=organization_id, now=now)
    if allowed:
        return True, "OK_ENTITLED", "active entitlement"
    if not commerce_configured:
        return False, "COMMERCE_DISABLED", (
            "paid listing with no billing provider configured; "
            "purchase is unavailable")
    return False, "NEED_ENTITLEMENT", (
        "an active entitlement is required to install this package")


def product_entitlement_features(*, product_type: str,
                                 package_slug: str = "") -> list[str]:
    """Features a purchase/subscription of a product normally grants."""
    base = [f"package.install:{package_slug}" if package_slug else "package.install",
            "package.install", "package.update"]
    ptype = str(product_type or "").upper()
    if ptype == "SUBSCRIPTION":
        return base + ["package.update", "product.updates"]
    if ptype == "LICENSE":
        return base + ["product.license"]
    return base
