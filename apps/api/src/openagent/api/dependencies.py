from typing import Optional, List
from uuid import UUID
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from openagent.db.session import get_db
from openagent.db.models import User, Organization, Membership, MembershipStatus, Session
from openagent.services.auth import AuthenticationService
from openagent.services.authorization import (
    AuthorizationService,
    AuthorizationContext,
    AuthorizationError,
)
from openagent.core.config import get_settings


async def get_current_organization(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Organization:
    """Get current organization from request context."""
    # Check for organization ID in header (for API clients)
    org_id_header = request.headers.get("X-Organization-ID")
    if org_id_header:
        try:
            org_id = UUID(org_id_header)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "Invalid organization ID", "code": "INVALID_ORG_ID"},
            )
        
        result = await db.execute(
            select(Organization).where(Organization.id == org_id)
        )
        org = result.scalar_one_or_none()
        if not org:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "Organization not found", "code": "ORG_NOT_FOUND"},
            )
        return org
    
    # For browser clients, get from session/user context
    # This would be set after authentication
    # For now, return None - the route handler should handle this
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"error": "Organization context required", "code": "ORG_CONTEXT_REQUIRED"},
    )


async def get_auth_context(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> tuple[User, Optional[Organization], Optional[AuthorizationContext]]:
    """Get authentication context including user, organization, and auth context."""
    # Get session from cookie
    settings = get_settings()
    session_token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    
    user = None
    organization = None
    auth_context = None
    
    if session_token:
        auth_service = AuthenticationService(db)
        session = await auth_service.get_session(session_token)
        if session:
            # Get user
            result = await db.execute(
                select(User).where(User.id == session.user_id)
            )
            user = result.scalar_one_or_none()
            
            # Try to get organization from header
            org_id_header = request.headers.get("X-Organization-ID")
            if org_id_header:
                try:
                    org_id = UUID(org_id_header)
                    org_result = await db.execute(
                        select(Organization).where(Organization.id == org_id)
                    )
                    organization = org_result.scalar_one_or_none()
                    
                    if organization and user:
                        authz_service = AuthorizationService(db)
                        auth_context = await authz_service.get_user_context(user.id, organization.id)
                except ValueError:
                    pass
    
    return user, organization, auth_context


def require_permission(permission: str):
    """Dependency factory for requiring a specific permission."""
    async def _check_permission(
        request: Request,
        db: AsyncSession = Depends(get_db),
    ) -> AuthorizationContext:
        user, organization, auth_context = await get_auth_context(request, db)
        
        if not auth_context:
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail={"error": "Authentication required", "code": "UNAUTHORIZED"},
                )
            if not organization:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={"error": "Organization context required", "code": "ORG_CONTEXT_REQUIRED"},
                )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": "Access denied", "code": "FORBIDDEN"},
            )
        
        authz_service = AuthorizationService(db)
        authz_service.require_permission(auth_context, permission)
        
        return auth_context
    
    return _check_permission


def require_any_permission(permissions: List[str]):
    """Dependency factory for requiring any of the specified permissions."""
    async def _check_permission(
        request: Request,
        db: AsyncSession = Depends(get_db),
    ) -> AuthorizationContext:
        user, organization, auth_context = await get_auth_context(request, db)
        
        if not auth_context:
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail={"error": "Authentication required", "code": "UNAUTHORIZED"},
                )
            if not organization:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={"error": "Organization context required", "code": "ORG_CONTEXT_REQUIRED"},
                )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": "Access denied", "code": "FORBIDDEN"},
            )
        
        authz_service = AuthorizationService(db)
        authz_service.require_any_permission(auth_context, permissions)
        
        return auth_context
    
    return _check_permission


def require_all_permissions(permissions: List[str]):
    """Dependency factory for requiring all of the specified permissions."""
    async def _check_permission(
        request: Request,
        db: AsyncSession = Depends(get_db),
    ) -> AuthorizationContext:
        user, organization, auth_context = await get_auth_context(request, db)
        
        if not auth_context:
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail={"error": "Authentication required", "code": "UNAUTHORIZED"},
                )
            if not organization:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={"error": "Organization context required", "code": "ORG_CONTEXT_REQUIRED"},
                )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": "Access denied", "code": "FORBIDDEN"},
            )
        
        authz_service = AuthorizationService(db)
        authz_service.require_all_permissions(auth_context, permissions)
        
        return auth_context
    
    return _check_permission


async def get_current_org_context(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> AuthorizationContext:
    """Get current authorization context (requires authentication and org context)."""
    user, organization, auth_context = await get_auth_context(request, db)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "Authentication required", "code": "UNAUTHORIZED"},
        )
    
    if not organization:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "Organization context required", "code": "ORG_CONTEXT_REQUIRED"},
        )
    
    if not auth_context:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "Not a member of this organization", "code": "NOT_MEMBER"},
        )
    
    return auth_context


def require_platform_owner():
    """Dependency for requiring platform owner access."""
    async def _check_platform_owner(
        request: Request,
        db: AsyncSession = Depends(get_db),
    ) -> User:
        user, _, _ = await get_auth_context(request, db)
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"error": "Authentication required", "code": "UNAUTHORIZED"},
            )
        
        authz_service = AuthorizationService(db)
        is_owner = await authz_service.is_platform_owner(user.id)
        
        if not is_owner:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": "Platform owner access required", "code": "FORBIDDEN"},
            )
        
        return user
    
    return _check_platform_owner


def require_organization_role(roles: List[str]):
    """Dependency factory for requiring a specific organization role."""
    async def _check_role(
        request: Request,
        db: AsyncSession = Depends(get_db),
    ) -> AuthorizationContext:
        user, organization, auth_context = await get_auth_context(request, db)
        
        if not auth_context:
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail={"error": "Authentication required", "code": "UNAUTHORIZED"},
                )
            if not organization:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={"error": "Organization context required", "code": "ORG_CONTEXT_REQUIRED"},
                )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": "Not a member of this organization", "code": "NOT_MEMBER"},
            )
        
        # Check if user has one of the required roles
        if auth_context.role:
            if auth_context.role.name in roles:
                return auth_context
        
        # Check legacy role
        if auth_context.membership and auth_context.membership.legacy_role.value in roles:
            return auth_context
        
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": f"Requires one of roles: {roles}", "code": "FORBIDDEN"},
        )
    
    return _check_role