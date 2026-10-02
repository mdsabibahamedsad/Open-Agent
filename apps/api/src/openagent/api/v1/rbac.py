from datetime import datetime
from typing import Optional, List
from uuid import UUID
from fastapi import APIRouter, Depends, Request, HTTPException, status, Query
from pydantic import BaseModel, Field, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession

from openagent.db.session import get_db
from openagent.db.models import Permission, Role, RoleType, RolePermission
from openagent.db.repositories import PermissionRepository, RoleRepository
from openagent.schemas.base import ApiErrorResponse, PaginationParams, PaginatedResponse
from openagent.api.dependencies import (
    get_current_org_context,
    require_permission,
    require_organization_role,
)
from openagent.services.authorization import AuthorizationService

router = APIRouter(prefix="/organizations/{organization_id}/rbac", tags=["rbac"])


# Permission Schemas
class PermissionResponse(BaseModel):
    id: UUID
    name: str
    resource: str
    action: str
    scope: str
    description: Optional[str]
    is_system: bool
    danger_level: int
    metadata: dict
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class PermissionListResponse(PaginatedResponse[PermissionResponse]):
    pass


# Role Schemas
class RolePermissionResponse(BaseModel):
    permission_id: UUID
    permission_name: str
    resource: str
    action: str
    scope: str


class RoleBase(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    display_name: str = Field(min_length=1, max_length=255)
    description: Optional[str] = None
    role_type: str = Field(default="custom", pattern="^(system|custom)$")


class RoleCreate(RoleBase):
    pass


class RoleUpdate(BaseModel):
    display_name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    is_system: Optional[bool] = None
    priority: Optional[int] = None


class RoleResponse(RoleBase):
    id: UUID
    organization_id: Optional[UUID]
    is_system: bool
    priority: int
    metadata: dict
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class RoleWithPermissions(RoleResponse):
    permissions: List[RolePermissionResponse] = []


class RoleListResponse(PaginatedResponse[RoleResponse]):
    pass


class RolePermissionsUpdate(BaseModel):
    permission_ids: List[UUID]


# Permission Endpoints
@router.get(
    "/permissions",
    response_model=PermissionListResponse,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}},
)
async def list_permissions(
    request: Request,
    organization_id: UUID,
    resource: Optional[str] = Query(None),
    scope: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    auth_context = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """List all permissions."""
    await require_permission("role:read")(request, db)
    
    repo = PermissionRepository(db)
    
    if resource:
        from openagent.db.models import PermissionResource
        try:
            perm_resource = PermissionResource(resource)
            permissions = await repo.list_by_resource(perm_resource)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": f"Invalid resource: {resource}", "code": "INVALID_RESOURCE"},
            )
    elif scope:
        permissions = await repo.list_by_scope(scope)
    else:
        all_perms_result = await db.execute(
            select(Permission).order_by(Permission.resource, Permission.action)
        )
        permissions = list(all_perms_result.scalars().all())
    
    # Pagination
    start = (page - 1) * page_size
    end = start + page_size
    paginated = permissions[start:end]
    
    from openagent.db.pagination import create_pagination_meta
    meta = create_pagination_meta(page, page_size, len(permissions))
    
    return PermissionListResponse(data=paginated, meta=meta)


@router.get(
    "/permissions/{permission_id}",
    response_model=PermissionResponse,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def get_permission(
    request: Request,
    organization_id: UUID,
    permission_id: UUID,
    auth_context = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Get a specific permission."""
    await require_permission("role:read")(request, db)
    
    repo = PermissionRepository(db)
    permission = await repo.get_by_id(permission_id)
    
    if not permission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Permission not found", "code": "PERMISSION_NOT_FOUND"},
        )
    
    return permission


# Role Endpoints
@router.get(
    "/roles",
    response_model=RoleListResponse,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}},
)
async def list_roles(
    request: Request,
    organization_id: UUID,
    include_system: bool = Query(True),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    auth_context = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """List all roles for the organization."""
    await require_permission("role:read")(request, db)
    
    repo = RoleRepository(db)
    roles = await repo.list_by_organization(organization_id, include_system)
    
    # Pagination
    start = (page - 1) * page_size
    end = start + page_size
    paginated = roles[start:end]
    
    from openagent.db.pagination import create_pagination_meta
    meta = create_pagination_meta(page, page_size, len(roles))
    
    return RoleListResponse(data=paginated, meta=meta)


@router.post(
    "/roles",
    response_model=RoleResponse,
    status_code=status.HTTP_201_CREATED,
    responses={400: {"model": ApiErrorResponse}, 401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 409: {"model": ApiErrorResponse}},
)
async def create_role(
    request: Request,
    organization_id: UUID,
    data: RoleCreate,
    auth_context = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Create a new custom role."""
    await require_permission("role:create")(request, db)
    
    repo = RoleRepository(db)
    
    # Check if role name already exists in organization
    existing = await repo.get_by_name(organization_id, data.name)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "Role with this name already exists", "code": "ROLE_EXISTS"},
        )
    
    role = await repo.create(
        organization_id=organization_id,
        name=data.name,
        display_name=data.display_name,
        description=data.description,
        role_type=RoleType.CUSTOM,
        is_system=False,
    )
    
    await db.commit()
    return role


@router.get(
    "/roles/{role_id}",
    response_model=RoleWithPermissions,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def get_role(
    request: Request,
    organization_id: UUID,
    role_id: UUID,
    auth_context = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Get a role with its permissions."""
    await require_permission("role:read")(request, db)
    
    repo = RoleRepository(db)
    role = await repo.get_with_permissions(role_id)
    
    if not role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Role not found", "code": "ROLE_NOT_FOUND"},
        )
    
    # Verify role belongs to organization (unless system role)
    if role.organization_id and role.organization_id != organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Role not found", "code": "ROLE_NOT_FOUND"},
        )
    
    permissions = await repo.get_permissions(role_id)
    permission_responses = [
        RolePermissionResponse(
            permission_id=p.id,
            permission_name=p.name,
            resource=p.resource.value,
            action=p.action.value,
            scope=p.scope.value,
        )
        for p in permissions
    ]
    
    return RoleWithPermissions(
        id=role.id,
        organization_id=role.organization_id,
        name=role.name,
        display_name=role.display_name,
        description=role.description,
        role_type=role.role_type.value,
        is_system=role.is_system,
        priority=role.priority,
        metadata=role.metadata,
        created_at=role.created_at,
        updated_at=role.updated_at,
        deleted_at=role.deleted_at,
        permissions=permission_responses,
    )


@router.patch(
    "/roles/{role_id}",
    response_model=RoleResponse,
    responses={400: {"model": ApiErrorResponse}, 401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def update_role(
    request: Request,
    organization_id: UUID,
    role_id: UUID,
    data: RoleUpdate,
    auth_context = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Update a role."""
    await require_permission("role:update")(request, db)
    
    repo = RoleRepository(db)
    role = await repo.get_by_id(role_id)
    
    if not role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Role not found", "code": "ROLE_NOT_FOUND"},
        )
    
    if role.organization_id != organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Role not found", "code": "ROLE_NOT_FOUND"},
        )
    
    # Prevent modification of system roles
    if role.is_system:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "Cannot modify system roles", "code": "SYSTEM_ROLE_IMMUTABLE"},
        )
    
    # Update fields
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(role, field, value)
    
    await db.commit()
    await db.refresh(role)
    
    return role


@router.delete(
    "/roles/{role_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def delete_role(
    request: Request,
    organization_id: UUID,
    role_id: UUID,
    auth_context = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Delete a custom role."""
    await require_permission("role:delete")(request, db)
    
    repo = RoleRepository(db)
    role = await repo.get_by_id(role_id)
    
    if not role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Role not found", "code": "ROLE_NOT_FOUND"},
        )
    
    if role.organization_id != organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Role not found", "code": "ROLE_NOT_FOUND"},
        )
    
    # Prevent deletion of system roles
    if role.is_system:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "Cannot delete system roles", "code": "SYSTEM_ROLE_IMMUTABLE"},
        )
    
    # Check if role has members
    member_count = await repo.count_members(role_id)
    if member_count > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": f"Cannot delete role with {member_count} members", "code": "ROLE_HAS_MEMBERS"},
        )
    
    await repo.soft_delete(role_id)
    await db.commit()


@router.get(
    "/roles/{role_id}/permissions",
    response_model=List[RolePermissionResponse],
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def get_role_permissions(
    request: Request,
    organization_id: UUID,
    role_id: UUID,
    auth_context = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Get all permissions for a role."""
    await require_permission("role:read")(request, db)
    
    repo = RoleRepository(db)
    permissions = await repo.get_permissions(role_id)
    
    return [
        RolePermissionResponse(
            permission_id=p.id,
            permission_name=p.name,
            resource=p.resource.value,
            action=p.action.value,
            scope=p.scope.value,
        )
        for p in permissions
    ]


@router.put(
    "/roles/{role_id}/permissions",
    response_model=List[RolePermissionResponse],
    responses={400: {"model": ApiErrorResponse}, 401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def set_role_permissions(
    request: Request,
    organization_id: UUID,
    role_id: UUID,
    data: RolePermissionsUpdate,
    auth_context = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Set permissions for a role (replaces all existing permissions)."""
    await require_permission("role:update")(request, db)
    
    repo = RoleRepository(db)
    role = await repo.get_by_id(role_id)
    
    if not role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Role not found", "code": "ROLE_NOT_FOUND"},
        )
    
    if role.organization_id != organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Role not found", "code": "ROLE_NOT_FOUND"},
        )
    
    if role.is_system:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "Cannot modify system role permissions", "code": "SYSTEM_ROLE_IMMUTABLE"},
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
    
    await repo.set_permissions(role_id, data.permission_ids)
    await db.commit()
    
    permissions = await repo.get_permissions(role_id)
    return [
        RolePermissionResponse(
            permission_id=p.id,
            permission_name=p.name,
            resource=p.resource.value,
            action=p.action.value,
            scope=p.scope.value,
        )
        for p in permissions
    ]


@router.post(
    "/roles/{role_id}/permissions/{permission_id}",
    status_code=status.HTTP_201_CREATED,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}, 409: {"model": ApiErrorResponse}},
)
async def add_role_permission(
    request: Request,
    organization_id: UUID,
    role_id: UUID,
    permission_id: UUID,
    auth_context = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Add a permission to a role."""
    await require_permission("role:update")(request, db)
    
    repo = RoleRepository(db)
    role = await repo.get_by_id(role_id)
    
    if not role or role.organization_id != organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Role not found", "code": "ROLE_NOT_FOUND"},
        )
    
    if role.is_system:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "Cannot modify system role permissions", "code": "SYSTEM_ROLE_IMMUTABLE"},
        )
    
    # Verify permission exists
    perm_repo = PermissionRepository(db)
    perm = await perm_repo.get_by_id(permission_id)
    if not perm:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Permission not found", "code": "PERMISSION_NOT_FOUND"},
        )
    
    rp = await repo.add_permission(role_id, permission_id)
    await db.commit()
    
    return {"message": "Permission added to role"}


@router.delete(
    "/roles/{role_id}/permissions/{permission_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def remove_role_permission(
    request: Request,
    organization_id: UUID,
    role_id: UUID,
    permission_id: UUID,
    auth_context = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Remove a permission from a role."""
    await require_permission("role:update")(request, db)
    
    repo = RoleRepository(db)
    role = await repo.get_by_id(role_id)
    
    if not role or role.organization_id != organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Role not found", "code": "ROLE_NOT_FOUND"},
        )
    
    if role.is_system:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "Cannot modify system role permissions", "code": "SYSTEM_ROLE_IMMUTABLE"},
        )
    
    removed = await repo.remove_permission(role_id, permission_id)
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Permission not found on role", "code": "PERMISSION_NOT_ON_ROLE"},
        )
    
    await db.commit()