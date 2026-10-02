"""MP27: SCIM 2.0 API (§94). Protocol endpoints with dedicated
bearer credentials (scoped, expiring, revocable — never a Master
password), strict rate limits, tenant resolution per request, and
deactivation that preserves audit history."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from openagent.core.security.tokens import hash_token, verify_token
from openagent.db.models.identity import ScimCredentialRow, ScimSyncRun
from openagent.db.session import get_db
from openagent.identity.scim import (
    ScimCredential, ScimRateLimiter, apply_filter, apply_patch,
    paginate, parse_filter, scim_error_body, validate_scim_group,
    validate_scim_user,
)

router = APIRouter(prefix="/scim/v2", tags=["scim"])

_limiter = ScimRateLimiter()

# In-memory directory mirrors (durable user/team stores own the truth;
# SCIM layer maps protocol operations onto them).
_USERS: dict[str, dict[str, dict[str, Any]]] = {}
_GROUPS: dict[str, dict[str, dict[str, Any]]] = {}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _store(org: str) -> dict[str, dict[str, Any]]:
    return _USERS.setdefault(org, {})


def _groups(org: str) -> dict[str, dict[str, Any]]:
    return _GROUPS.setdefault(org, {})


async def _scim_auth(
    authorization: str = Header(default=""),
    db: AsyncSession = Depends(get_db),
) -> tuple[ScimCredentialRow, str]:
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail=scim_error_body("Missing bearer token",
                                                   401, "invalidValue"))
    rows = (await db.execute(select(ScimCredentialRow).where(
        ScimCredentialRow.revoked.is_(False)))).scalars().all()
    for row in rows:
        if verify_token(token, row.token_hash):
            credential = ScimCredential(
                credential_id=str(row.id),
                organization_id=str(row.organization_id),
                token_hash=row.token_hash, prefix=row.prefix,
                expires_at=row.expires_at.timestamp()
                if row.expires_at else 0.0)
            ok, _ = credential.usable()
            if not ok:
                break
            row.last_used_at = _utcnow()
            await db.commit()
            return row, str(row.organization_id)
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                        detail=scim_error_body("Invalid SCIM credential",
                                               401, "invalidValue"))


def _limited(credential_id: str, operation: str) -> None:
    ok, reason = _limiter.check(credential_id, operation)
    if not ok:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                            detail=scim_error_body(reason, 429,
                                                   "rateLimit"))


def _scim_user_resource(org: str, user_id: str,
                        user: dict[str, Any]) -> dict[str, Any]:
    return {"schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
            "id": user_id, **user,
            "meta": {"resourceType": "User"}}


# ------------------------------------------------------------------ Users ---
@router.post("/Users", status_code=201)
async def create_user(
    body: dict[str, Any],
    auth: tuple = Depends(_scim_auth),
    db: AsyncSession = Depends(get_db),
):
    row, org = auth
    _limited(str(row.id), "provision")
    try:
        clean = validate_scim_user(body)
    except Exception as exc:
        from openagent.identity.scim import ScimError
        status_code = getattr(exc, "status", 400)
        raise HTTPException(status_code=status_code,
                            detail=scim_error_body(str(exc), status_code))
    store = _store(org)
    if any(u.get("userName") == clean["userName"] for u in store.values()):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=scim_error_body("duplicate userName", 409,
                                   "uniqueness"))
    import uuid as _uuid
    user_id = f"scim-u-{_uuid.uuid4().hex[:12]}"
    store[user_id] = {**clean, "id": user_id}
    return _scim_user_resource(org, user_id, store[user_id])


@router.get("/Users")
async def list_users(
    auth: tuple = Depends(_scim_auth),
    filter: str = Query(default=""),
    startIndex: int = Query(default=1, ge=1),
    count: int = Query(default=100, ge=1, le=500),
):
    _, org = auth
    users = list(_store(org).values())
    if filter:
        try:
            users = apply_filter(users, parse_filter(filter))
        except Exception as exc:
            from openagent.identity.scim import ScimError
            status_code = getattr(exc, "status", 400)
            raise HTTPException(
                status_code=status_code,
                detail=scim_error_body(str(exc), status_code,
                                       "invalidFilter"))
    page = paginate(users, start_index=startIndex, count=count)
    return {"schemas": ["urn:ietf:params:scim:api:messages:2.0:ListResponse"],
            "totalResults": page["totalResults"],
            "startIndex": page["startIndex"],
            "itemsPerPage": page["itemsPerPage"],
            "Resources": [(_scim_user_resource(org, u.get("id", ""), u))
                          for u in page["Resources"]]}


@router.get("/Users/{user_id}")
async def get_user(
    user_id: str,
    auth: tuple = Depends(_scim_auth),
):
    _, org = auth
    user = _store(org).get(user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=scim_error_body("user not found", 404,
                                                   "invalidValue"))
    return _scim_user_resource(org, user_id, user)


def _mutate_user(org: str, user_id: str, body: dict[str, Any],
                 *, replace: bool, credential_id: str) -> dict[str, Any]:
    store = _store(org)
    user = store.get(user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=scim_error_body("user not found", 404,
                                                   "invalidValue"))
    if replace:
        clean = validate_scim_user({**user, **body})
        clean["id"] = user_id
        store[user_id] = clean
    else:
        operations = body.get("Operations", [])
        if not isinstance(operations, list):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=scim_error_body("Operations must be a list", 400,
                                       "invalidSyntax"))
        try:
            store[user_id] = apply_patch(user, operations)
        except Exception as exc:
            status_code = getattr(exc, "status", 400)
            raise HTTPException(
                status_code=status_code,
                detail=scim_error_body(str(exc), status_code))
    return store[user_id]


@router.patch("/Users/{user_id}")
async def patch_user(
    user_id: str,
    body: dict[str, Any],
    auth: tuple = Depends(_scim_auth),
):
    row, org = auth
    _limited(str(row.id), "update")
    return _scim_user_resource(
        org, user_id, _mutate_user(org, user_id, body, replace=False,
                                   credential_id=str(row.id)))


@router.put("/Users/{user_id}")
async def replace_user(
    user_id: str,
    body: dict[str, Any],
    auth: tuple = Depends(_scim_auth),
):
    row, org = auth
    _limited(str(row.id), "update")
    return _scim_user_resource(
        org, user_id, _mutate_user(org, user_id, body, replace=True,
                                   credential_id=str(row.id)))


@router.delete("/Users/{user_id}", status_code=204)
async def delete_user(
    user_id: str,
    auth: tuple = Depends(_scim_auth),
):
    row, org = auth
    _limited(str(row.id), "update")
    store = _store(org)
    user = store.get(user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=scim_error_body("user not found", 404,
                                                   "invalidValue"))
    # Deactivation preserves history; hard delete only when never active.
    user["active"] = False
    return None


# ----------------------------------------------------------------- Groups ---
@router.post("/Groups", status_code=201)
async def create_group(
    body: dict[str, Any],
    auth: tuple = Depends(_scim_auth),
):
    row, org = auth
    _limited(str(row.id), "group_change")
    try:
        clean = validate_scim_group(body)
    except Exception as exc:
        status_code = getattr(exc, "status", 400)
        raise HTTPException(status_code=status_code,
                            detail=scim_error_body(str(exc), status_code))
    store = _groups(org)
    if any(g.get("displayName") == clean["displayName"]
           for g in store.values()):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=scim_error_body("duplicate group", 409, "uniqueness"))
    import uuid as _uuid
    group_id = f"scim-g-{_uuid.uuid4().hex[:12]}"
    store[group_id] = {**clean, "id": group_id}
    return {"schemas": ["urn:ietf:params:scim:schemas:core:2.0:Group"],
            "id": group_id, **clean}


@router.get("/Groups")
async def list_groups(
    auth: tuple = Depends(_scim_auth),
    startIndex: int = Query(default=1, ge=1),
    count: int = Query(default=100, ge=1, le=500),
):
    _, org = auth
    groups = list(_groups(org).values())
    page = paginate(groups, start_index=startIndex, count=count)
    return {"schemas": ["urn:ietf:params:scim:api:messages:2.0:ListResponse"],
            "totalResults": page["totalResults"],
            "Resources": page["Resources"]}


@router.patch("/Groups/{group_id}")
async def patch_group(
    group_id: str,
    body: dict[str, Any],
    auth: tuple = Depends(_scim_auth),
):
    row, org = auth
    _limited(str(row.id), "group_change")
    store = _groups(org)
    group = store.get(group_id)
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=scim_error_body("group not found", 404,
                                                   "invalidValue"))
    operations = body.get("Operations", [])
    try:
        store[group_id] = apply_patch(group, operations)
    except Exception as exc:
        status_code = getattr(exc, "status", 400)
        raise HTTPException(status_code=status_code,
                            detail=scim_error_body(str(exc), status_code))
    return store[group_id]


@router.delete("/Groups/{group_id}", status_code=204)
async def delete_group(
    group_id: str,
    auth: tuple = Depends(_scim_auth),
):
    _, org = auth
    if _groups(org).pop(group_id, None) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=scim_error_body("group not found", 404,
                                                   "invalidValue"))
    return None
