from datetime import datetime
from typing import Optional, List
from uuid import UUID
from fastapi import APIRouter, Depends, Request, HTTPException, status, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from openagent.db.session import get_db
from openagent.db.models import ServiceAccount, ServiceAccountStatus
from openagent.db.repositories import ServiceAccountRepository, PermissionRepository
from openagent.schemas.base import ApiErrorResponse, PaginatedResponse
from openagent.api.dependencies import (
    get_current_org_context,
    require_permission,
)
from openagent.core.security.tokens import create_token_pair

router = APIRouter(prefix="/organizations/{organization_id}/service-accounts", tags=["service-accounts"])


# Service Account Schemas
class ServiceAccountBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: Optional[str] = None
    expires_at: Optional[datetime] = None


class ServiceAccountCreate(ServiceAccountBase):
    permissions: List[UUID] = []


class ServiceAccountUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    status: Optional[str] = Field(default=None, pattern="^(active|inactive|revoked)$")
    expires_at: Optional[datetime] = None


class ServiceAccountResponse(ServiceAccountBase):
    id: UUID
    organization_id: UUID
    key_prefix: str
    status: str
    last_used_at: Optional[datetime]
    created_by: Optional[UUID]
    metadata: dict
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ServiceAccountCreateResponse(ServiceAccountResponse):
    key: str  # Only returned on creation


class ServiceAccountListResponse(PaginatedResponse[ServiceAccountResponse]):
    pass


class ServiceAccountPermissionUpdate(BaseModel):
    permission_ids: List[UUID]


class ServiceAccountKeyRotateResponse(BaseModel):
    key: str
    key_prefix: str


@router.get(
    "",
    response_model=ServiceAccountListResponse,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}},
)
async def list_service_accounts(
    request: Request,
    organization_id: UUID,
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    auth_context = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """List all service accounts for the organization."""
    await require_permission("service_account:read")(request, db)
    
    repo = ServiceAccountRepository(db)
    
    status_filter = None
    if status:
        try:
            status_filter = ServiceAccountStatus(status)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": f"Invalid status: {status}", "code": "INVALID_STATUS"},
            )
    
    accounts = await repo.list_by_organization(
        organization_id,
        status=status_filter,
        limit=1000,
    )
    
    # Pagination
    start = (page - 1) * page_size
    end = start + page_size
    paginated = accounts[start:end]
    
    from openagent.db.pagination import create_pagination_meta
    meta = create_pagination_meta(page, page_size, len(accounts))
    
    return ServiceAccountListResponse(data=paginated, meta=meta)


@router.post(
    "",
    response_model=ServiceAccountCreateResponse,
    status_code=status.HTTP_201_CREATED,
    responses={400: {"model": ApiErrorResponse}, 401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}},
)
async def create_service_account(
    request: Request,
    organization_id: UUID,
    data: ServiceAccountCreate,
    auth_context = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Create a new service account."""
    await require_permission("service_account:create")(request, db)
    
    # Verify all permissions exist
    perm_repo = PermissionRepository(db)
    for perm_id in data.permissions:
        perm = await perm_repo.get_by_id(perm_id)
        if not perm:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": f"Permission {perm_id} not found", "code": "PERMISSION_NOT_FOUND"},
            )
    
    repo = ServiceAccountRepository(db)
    account, raw_key = await repo.create_service_account(
        organization_id=organization_id,
        name=data.name,
        description=data.description,
        created_by=auth_context.user_id,
        permissions=data.permissions,
        expires_at=data.expires_at,
    )
    
    await db.commit()
    
    response = ServiceAccountCreateResponse(
        id=account.id,
        organization_id=account.organization_id,
        name=account.name,
        description=account.description,
        key_prefix=account.key_prefix,
        status=account.status.value,
        expires_at=account.expires_at,
        created_by=account.created_by,
        metadata=account.metadata,
        created_at=account.created_at,
        updated_at=account.updated_at,
        deleted_at=account.deleted_at,
        key=raw_key,  # Only returned once!
    )
    
    return response


@router.get(
    "/{account_id}",
    response_model=ServiceAccountResponse,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def get_service_account(
    request: Request,
    organization_id: UUID,
    account_id: UUID,
    auth_context = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Get a service account by ID."""
    await require_permission("service_account:read")(request, db)
    
    repo = ServiceAccountRepository(db)
    account = await repo.get_by_id(account_id)
    
    if not account or account.organization_id != organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Service account not found", "code": "SERVICE_ACCOUNT_NOT_FOUND"},
        )
    
    return account


@router.patch(
    "/{account_id}",
    response_model=ServiceAccountResponse,
    responses={400: {"model": ApiErrorResponse}, 401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def update_service_account(
    request: Request,
    organization_id: UUID,
    account_id: UUID,
    data: ServiceAccountUpdate,
    auth_context = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Update a service account."""
    await require_permission("service_account:update")(request, db)
    
    repo = ServiceAccountRepository(db)
    account = await repo.get_by_id(account_id)
    
    if not account or account.organization_id != organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Service account not found", "code": "SERVICE_ACCOUNT_NOT_FOUND"},
        )
    
    update_data = data.model_dump(exclude_unset=True)
    
    if "status" in update_data:
        try:
            update_data["status"] = ServiceAccountStatus(update_data["status"])
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": f"Invalid status: {update_data['status']}", "code": "INVALID_STATUS"},
            )
    
    for field, value in update_data.items():
        setattr(account, field, value)
    
    await db.commit()
    await db.refresh(account)
    
    return account


@router.delete(
    "/{account_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def delete_service_account(
    request: Request,
    organization_id: UUID,
    account_id: UUID,
    auth_context = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Delete (revoke) a service account."""
    await require_permission("service_account:delete")(request, db)
    
    repo = ServiceAccountRepository(db)
    account = await repo.get_by_id(account_id)
    
    if not account or account.organization_id != organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Service account not found", "code": "SERVICE_ACCOUNT_NOT_FOUND"},
        )
    
    await repo.revoke(account_id)
    await db.commit()


@router.post(
    "/{account_id}/rotate-key",
    response_model=ServiceAccountKeyRotateResponse,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def rotate_service_account_key(
    request: Request,
    organization_id: UUID,
    account_id: UUID,
    auth_context = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Rotate the service account's API key."""
    await require_permission("service_account:update")(request, db)
    
    repo = ServiceAccountRepository(db)
    account = await repo.get_by_id(account_id)
    
    if not account or account.organization_id != organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Service account not found", "code": "SERVICE_ACCOUNT_NOT_FOUND"},
        )
    
    account, new_key = await repo.rotate_key(account_id)
    await db.commit()
    
    return ServiceAccountKeyRotateResponse(
        key=new_key,
        key_prefix=account.key_prefix,
    )


@router.get(
    "/{account_id}/permissions",
    response_model=List[dict],
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def get_service_account_permissions(
    request: Request,
    organization_id: UUID,
    account_id: UUID,
    auth_context = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Get all permissions for a service account."""
    await require_permission("service_account:read")(request, db)
    
    repo = ServiceAccountRepository(db)
    account = await repo.get_with_permissions(account_id)
    
    if not account or account.organization_id != organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Service account not found", "code": "SERVICE_ACCOUNT_NOT_FOUND"},
        )
    
    return [
        {
            "permission_id": p.id,
            "name": p.name,
            "resource": p.resource.value,
            "action": p.action.value,
            "scope": p.scope.value,
        }
        for p in account.permissions
    ]


@router.put(
    "/{account_id}/permissions",
    response_model=List[dict],
    responses={400: {"model": ApiErrorResponse}, 401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def set_service_account_permissions(
    request: Request,
    organization_id: UUID,
    account_id: UUID,
    data: ServiceAccountPermissionUpdate,
    auth_context = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Set permissions for a service account (replaces all existing permissions)."""
    await require_permission("service_account:update")(request, db)
    
    repo = ServiceAccountRepository(db)
    account = await repo.get_by_id(account_id)
    
    if not account or account.organization_id != organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Service account not found", "code": "SERVICE_ACCOUNT_NOT_FOUND"},
        )
    
    # Verify all permissions exist
    perm_repo = PermissionRepository(db)
    for perm_id in data.permission_ids:
        perm = await perm_repo.get_by_id(perm_id)
        if not perm:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": f"Permission {perm_id} not found", "code": "PERMISSION_NOT_FOUND"},
            )
    
    await repo.set_permissions(account_id, data.permission_ids)
    await db.commit()
    
    account = await repo.get_with_permissions(account_id)
    return [
        {
            "permission_id": p.id,
            "name": p.name,
            "resource": p.resource.value,
            "action": p.action.value,
            "scope": p.scope.value,
        }
        for p in account.permissions
    ]


@router.post(
    "/expire",
    response_model=dict,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}},
)
async def expire_old_service_accounts(
    request: Request,
    organization_id: UUID,
    auth_context = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Manually expire old service accounts."""
    await require_permission("service_account:update")(request, db)
    
    repo = ServiceAccountRepository(db)
    count = await repo.expire_old_accounts()
    await db.commit()
    
    return {"message": f"Expired {count} service accounts", "expired_count": count}