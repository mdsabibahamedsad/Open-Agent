"""Repository connection API — connect/list/get/sync repositories.

Tenant-scoped via the standard org context. Raw provider secrets never
appear here: writes accept ``credential_ref`` handles only.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from openagent.api.dependencies import get_current_org_context
from openagent.code.service import CodeNotFound, CodePolicyDenied, CodeSecurityError, CodeService
from openagent.db.session import get_db
from openagent.services.authorization import AuthorizationContext

router = APIRouter(prefix="/repositories", tags=["repositories"])


def _deny(exc: Exception) -> HTTPException:
    if isinstance(exc, CodePolicyDenied):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, CodeSecurityError):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if isinstance(exc, CodeNotFound):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                         detail="Repository operation failed")


class CreateRepositoryRequest(BaseModel):
    provider: str = Field(default="generic",
                          pattern="^(local|generic|github|gitlab|bitbucket)$")
    name: str = Field(min_length=1, max_length=255)
    full_name: str = Field(min_length=1, max_length=500)
    clone_url: str = Field(min_length=1)
    default_branch: str = Field(default="main", max_length=255)
    visibility: str = Field(default="private", pattern="^(private|public|internal)$")
    credential_ref: Optional[str] = Field(default=None, max_length=255)
    provider_config: Optional[Dict[str, Any]] = None
    external_id: Optional[str] = None


class RepositoryResponse(BaseModel):
    id: UUID
    organization_id: UUID
    provider: str
    external_id: Optional[str] = None
    name: str
    full_name: str
    default_branch: str
    visibility: str
    status: str
    has_credential: bool = False

    class Config:
        from_attributes = True


def _repo_out(r) -> dict:
    return {"id": r.id, "organization_id": r.organization_id,
            "provider": str(r.provider.value if hasattr(r.provider, "value") else r.provider),
            "external_id": r.external_id, "name": r.name, "full_name": r.full_name,
            "default_branch": r.default_branch, "visibility": r.visibility,
            "status": str(r.status.value if hasattr(r.status, "value") else r.status),
            "has_credential": bool(r.credential_ref)}


@router.post("", response_model=RepositoryResponse)
async def create_repository(
    request: CreateRepositoryRequest,
    ctx: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    try:
        repo = await CodeService(db).create_repository(
            organization_id=ctx.organization_id, provider=request.provider,
            name=request.name, full_name=request.full_name,
            clone_url=request.clone_url, default_branch=request.default_branch,
            visibility=request.visibility, credential_ref=request.credential_ref,
            provider_config=request.provider_config,
            external_id=request.external_id, actor=ctx.user_id)
        return _repo_out(repo)
    except (CodeSecurityError, CodePolicyDenied, CodeNotFound) as exc:
        raise _deny(exc)


@router.get("", response_model=List[RepositoryResponse])
async def list_repositories(
    ctx: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    repos = await CodeService(db).list_repositories(ctx.organization_id)
    return [_repo_out(r) for r in repos]


@router.get("/{repo_id}", response_model=RepositoryResponse)
async def get_repository(
    repo_id: UUID,
    ctx: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    try:
        return _repo_out(await CodeService(db).get_repository(repo_id, ctx.organization_id))
    except (CodeSecurityError, CodeNotFound) as exc:
        raise _deny(exc)


@router.post("/{repo_id}/connect")
async def connect_repository(
    repo_id: UUID,
    ctx: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await CodeService(db).connect_repository(repo_id, ctx.organization_id)
    except (CodeSecurityError, CodePolicyDenied, CodeNotFound) as exc:
        raise _deny(exc)


@router.post("/{repo_id}/sync")
async def sync_repository(
    repo_id: UUID,
    ctx: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await CodeService(db).sync_repository(repo_id, ctx.organization_id)
    except (CodeSecurityError, CodePolicyDenied, CodeNotFound) as exc:
        raise _deny(exc)


@router.delete("/{repo_id}")
async def delete_repository(
    repo_id: UUID,
    ctx: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    try:
        await CodeService(db).delete_repository(repo_id, ctx.organization_id,
                                                actor=ctx.user_id)
        return {"success": True}
    except (CodeSecurityError, CodePolicyDenied, CodeNotFound) as exc:
        raise _deny(exc)


class RemoteListRequest(BaseModel):
    provider: str = Field(pattern="^(github|gitlab|bitbucket|generic)$")
    credential_ref: str = Field(min_length=1, max_length=255)


@router.post("/remote/list")
async def list_remote_repositories(
    request: RemoteListRequest,
    ctx: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    try:
        repos = await CodeService(db).list_remote_repositories(
            ctx.organization_id, request.provider, request.credential_ref)
        return {"repositories": repos}
    except (CodeSecurityError, CodePolicyDenied, CodeNotFound) as exc:
        raise _deny(exc)
