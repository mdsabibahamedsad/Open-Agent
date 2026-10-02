"""MP27: SCIM 2.0 provisioning (§16-20). Users, groups, memberships
with SCIM filtering/pagination, tenant-scoped bearer credentials with
expiry/rotation/revocation, and strict rate limits against sync storms.
Deactivation disables access; audit history is preserved.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Optional

SCIM_USER_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:User"
SCIM_GROUP_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:Group"

SCIM_OPERATIONS = ("POST", "GET", "PATCH", "PUT", "DELETE")

# Strict per-credential buckets (§20).
SCIM_RATE_LIMITS = {
    "provision": (100, 60),    # 100 provisions / minute
    "update": (300, 60),
    "group_change": (200, 60),
    "bulk": (10, 60),
}


class ScimError(Exception):
    def __init__(self, message: str, status: int = 400,
                 scim_type: str = "invalidValue") -> None:
        super().__init__(message)
        self.status = status
        self.scim_type = scim_type


def scim_error_body(detail: str, status: int,
                    scim_type: str = "invalidValue") -> dict[str, Any]:
    return {"schemas": ["urn:ietf:params:scim:api:messages:2.0:Error"],
            "detail": detail, "status": str(status),
            "scimType": scim_type}


# ------------------------------------------------------------- filtering ---
_FILTER_RE = re.compile(
    r'^\s*(\w+)\s+(eq|ne|co|sw|ew|pr)\s*(?:"([^"]*)"|(\S+))?\s*$',
    re.IGNORECASE)


def parse_filter(filter_str: str) -> dict[str, Any]:
    """SCIM filter subset (eq/ne/co/sw/ew/pr on userName, emails,
    active, displayName). Anything else is rejected, not guessed."""
    if not filter_str or not filter_str.strip():
        raise ScimError("empty filter", 400, "invalidFilter")
    match = _FILTER_RE.match(filter_str)
    if not match:
        raise ScimError(f"unsupported filter {filter_str!r}", 400,
                        "invalidFilter")
    attr, op, quoted, bare = match.groups()
    attr = attr.lower()
    if attr not in ("username", "emails", "active", "displayname",
                    "externalid"):
        raise ScimError(f"unfilterable attribute {attr}", 400,
                        "invalidFilter")
    value: Any = quoted if quoted is not None else bare
    if op.lower() == "pr" and value not in (None, ""):
        raise ScimError("pr takes no value", 400, "invalidFilter")
    if attr == "active" and value is not None:
        value = str(value).lower() in ("true", "1")
    return {"attribute": attr, "op": op.lower(), "value": value}


def apply_filter(users: list[dict[str, Any]],
                 parsed: dict[str, Any]) -> list[dict[str, Any]]:
    attr, op, value = parsed["attribute"], parsed["op"], parsed["value"]

    def field_of(user: dict[str, Any]) -> Any:
        if attr == "username":
            return user.get("userName", "")
        if attr == "emails":
            emails = user.get("emails", [])
            return " ".join(e.get("value", "") for e in emails
                            if isinstance(e, dict))
        if attr == "active":
            return bool(user.get("active", True))
        if attr == "displayname":
            return user.get("displayName", "")
        return user.get("externalId", "")

    out = []
    for user in users:
        current = field_of(user)
        if op == "pr":
            if current not in (None, "", [], {}):
                out.append(user)
        elif op == "eq" and current == value:
            out.append(user)
        elif op == "ne" and current != value:
            out.append(user)
        elif op == "co" and value in str(current):
            out.append(user)
        elif op == "sw" and str(current).startswith(str(value or "")):
            out.append(user)
        elif op == "ew" and str(current).endswith(str(value or "")):
            out.append(user)
    return out


def paginate(items: list[Any], *, start_index: int = 1,
             count: int = 100) -> dict[str, Any]:
    start_index = max(1, start_index)
    count = min(max(1, count), 500)  # never dump a directory at once
    page = items[start_index - 1:start_index - 1 + count]
    return {"totalResults": len(items), "startIndex": start_index,
            "itemsPerPage": len(page), "Resources": page}


# ------------------------------------------------------------ PATCH ops ---
# SCIM attribute names are case-insensitive; canonical casing is used
# for storage so clients see stable attribute names.
_CANONICAL_ATTRS = {"username": "userName", "displayname": "displayName",
                    "emails": "emails", "active": "active",
                    "externalid": "externalId", "groups": "groups",
                    "name": "name"}


def _canonical(path: str) -> str:
    return _CANONICAL_ATTRS.get(path.lower(), path)


def apply_patch(target: dict[str, Any],
                operations: list[dict[str, Any]]) -> dict[str, Any]:
    """SCIM PATCH (add/replace/remove). Paths are a closed vocabulary —
    arbitrary attributes can never become permissions (§18)."""
    allowed_paths = set(_CANONICAL_ATTRS)
    result = dict(target)
    for operation in operations:
        op = str(operation.get("op", "")).lower()
        path = str(operation.get("path", "") or "").lower()
        value = operation.get("value")
        if op not in ("add", "replace", "remove"):
            raise ScimError(f"unsupported PATCH op {op}", 400,
                            "invalidSyntax")
        if path and path not in allowed_paths:
            raise ScimError(f"unpatchable path {path}", 400,
                            "invalidPath")
        if op == "remove":
            if path:
                result.pop(_canonical(path), None)
            continue
        if not path:
            if not isinstance(value, dict):
                raise ScimError("path-less PATCH needs an object", 400,
                                "invalidSyntax")
            for key, item in value.items():
                if key.lower() not in allowed_paths:
                    raise ScimError(f"unpatchable path {key}", 400,
                                    "invalidPath")
                result[_canonical(key.lower())] = item
            continue
        result[_canonical(path)] = value
    return result


# ------------------------------------------------------- validation ---
def validate_scim_user(body: dict[str, Any]) -> dict[str, Any]:
    username = str(body.get("userName", "")).strip()
    if not username:
        raise ScimError("userName is required", 400)
    emails = body.get("emails", [])
    if emails and not isinstance(emails, list):
        raise ScimError("emails must be a list", 400)
    # Privilege-bearing attributes are NEVER accepted from SCIM payloads.
    for forbidden in ("roles", "entitlements", "permissions",
                      "is_admin", "platform_owner", "groups_admin"):
        if forbidden in body:
            raise ScimError(
                f"{forbidden} cannot be set via SCIM", 403,
                "forbidden")
    return {"userName": username, "emails": emails,
            "displayName": str(body.get("displayName", "")),
            "externalId": str(body.get("externalId", "")),
            "active": bool(body.get("active", True))}


def validate_scim_group(body: dict[str, Any]) -> dict[str, Any]:
    name = str(body.get("displayName", "")).strip()
    if not name:
        raise ScimError("displayName is required", 400)
    members = body.get("members", [])
    if not isinstance(members, list):
        raise ScimError("members must be a list", 400)
    for member in members:
        if not isinstance(member, dict) or "value" not in member:
            raise ScimError("member needs a value", 400)
    return {"displayName": name, "members": members,
            "externalId": str(body.get("externalId", ""))}


# ------------------------------------------------------- rate limits ---
class ScimRateLimiter:
    """Token-bucket per credential per operation class."""

    def __init__(self) -> None:
        self._buckets: dict[str, tuple[float, float]] = {}

    def check(self, credential_id: str, operation: str,
              now: Optional[float] = None) -> tuple[bool, str]:
        moment = now if now is not None else time.time()
        limit, window = SCIM_RATE_LIMITS.get(operation, (100, 60))
        rate = limit / window
        key = f"{credential_id}:{operation}"
        tokens, updated = self._buckets.get(key, (float(limit), moment))
        tokens = min(float(limit), tokens + (moment - updated) * rate)
        if tokens < 1.0:
            self._buckets[key] = (tokens, moment)
            return False, "SCIM rate limit exceeded (sync storm guard)"
        self._buckets[key] = (tokens - 1.0, moment)
        return True, "ok"


# ------------------------------------------------------- credentials ---
@dataclass
class ScimCredential:
    credential_id: str
    organization_id: str
    token_hash: str
    prefix: str = ""
    expires_at: float = 0.0
    revoked: bool = False
    created_at: float = field(default_factory=time.time)

    def usable(self, now: Optional[float] = None) -> tuple[bool, str]:
        moment = now if now is not None else time.time()
        if self.revoked:
            return False, "SCIM credential revoked"
        if self.expires_at and moment >= self.expires_at:
            return False, "SCIM credential expired"
        return True, "ok"
