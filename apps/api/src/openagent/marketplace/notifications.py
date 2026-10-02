"""MP23: marketplace notifications — fan-out with user preferences.

Notifications are rows (queryable, permission-scoped), not an external
push system. Fan-out resolves recipients from follows/installs/prefs and
writes rows in batches. Preference keys are notification-type names;
missing keys default to opted-in except PAYOUT_EVENT (opt-in only when a
publisher profile exists — enforced by callers, not stored secrets).
"""

from __future__ import annotations

from typing import Any

DEFAULT_PREFS: dict[str, bool] = {
    "LISTING_APPROVED": True,
    "LISTING_REJECTED": True,
    "REVIEW_RECEIVED": True,
    "SECURITY_ISSUE": True,
    "PACKAGE_REVOKED": True,
    "UPDATE_PUBLISHED": True,
    "PAYOUT_EVENT": False,
    "INSTALLED_UPDATE": True,
    "SECURITY_ADVISORY": True,
    "REVOKED_PACKAGE": True,
    "FOLLOWED_RELEASE": True,
    "REVIEW_RESPONSE": True,
    "MODERATION_DECISION": True,
}


def prefs_for(stored: dict[str, Any] | None) -> dict[str, bool]:
    merged = dict(DEFAULT_PREFS)
    for key, value in (stored or {}).items():
        if key in merged and isinstance(value, bool):
            merged[key] = value
    return merged


def wants(stored: dict[str, Any] | None, notif_type: str) -> bool:
    return prefs_for(stored).get(str(notif_type), True)


def build_notification(
    *,
    user_id: str,
    notif_type: str,
    title: str,
    body: str = "",
    organization_id: str | None = None,
    listing_id: str | None = None,
    publisher_id: str | None = None,
) -> dict[str, Any]:
    if not user_id:
        raise ValueError("user_id required")
    return {
        "user_id": user_id,
        "organization_id": organization_id,
        "type": notif_type,
        "title": title[:255],
        "body": (body or "")[:2000],
        "listing_id": listing_id,
        "publisher_id": publisher_id,
        "read": False,
    }


def fanout_targets(
    *,
    follower_user_ids: list[str],
    installer_user_ids: list[str],
    kinds: dict[str, list[str]],
) -> dict[str, list[str]]:
    """Map notification kinds to recipient lists (callers query these)."""
    return {
        "FOLLOWED_RELEASE": list(dict.fromkeys(follower_user_ids)),
        "INSTALLED_UPDATE": list(dict.fromkeys(installer_user_ids)),
        "SECURITY_ADVISORY": list(dict.fromkeys(
            follower_user_ids + installer_user_ids)),
        "REVOKED_PACKAGE": list(dict.fromkeys(installer_user_ids)),
        **{k: list(dict.fromkeys(v)) for k, v in kinds.items()},
    }
