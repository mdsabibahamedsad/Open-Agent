from typing import Optional, List, Set
from uuid import UUID
from dataclasses import dataclass
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from openagent.db.models import (
    User,
    Organization,
    Membership,
    MembershipStatus,
    Role,
    RolePermission,
    Permission,
    Team,
    TeamMembership,
    ServiceAccount,
    ServiceAccountStatus,
    ServiceAccountPermission,
)
from openagent.db.repositories import (
    RoleRepository,
    PermissionRepository,
    TeamRepository,
    ServiceAccountRepository,
)
from openagent.core.config import get_settings

logger = structlog.get_logger("openagent.authz")


@dataclass
class AuthorizationContext:
    """Context for authorization decisions."""
    user_id: UUID
    organization_id: UUID
    membership: Membership
    role: Optional[Role]
    permissions: Set[str]
    teams: List[Team]
    is_platform_owner: bool = False
    is_service_account: bool = False
    service_account_id: Optional[UUID] = None


class AuthorizationError(Exception):
    """Authorization error."""
    def __init__(self, message: str, code: str = "FORBIDDEN", required_permission: Optional[str] = None):
        self.message = message
        self.code = code
        self.required_permission = required_permission
        super().__init__(message)


class AuthorizationService:
    """Centralized authorization service for RBAC."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.role_repo = RoleRepository(db)
        self.permission_repo = PermissionRepository(db)
        self.team_repo = TeamRepository(db)
        self.service_account_repo = ServiceAccountRepository(db)
        self.settings = get_settings()
    
    async def get_user_context(
        self,
        user_id: UUID,
        organization_id: UUID
    ) -> Optional[AuthorizationContext]:
        """Get authorization context for a user in an organization."""
        # Get membership
        result = await self.db.execute(
            select(Membership).where(
                Membership.user_id == user_id,
                Membership.organization_id == organization_id
            )
        )
        membership = result.scalar_one_or_none()
        
        if not membership or membership.status != MembershipStatus.ACTIVE:
            return None
        
        # Check if platform owner
        from openagent.db.models import PlatformOwner, PlatformOwnerStatus
        platform_owner_result = await self.db.execute(
            select(PlatformOwner).where(
                PlatformOwner.user_id == user_id,
                PlatformOwner.status == PlatformOwnerStatus.ACTIVE
            )
        )
        is_platform_owner = platform_owner_result.scalar_one_or_none() is not None
        
        # Get role and permissions
        role = None
        permissions = set()
        
        if membership.role_id:
            role = await self.role_repo.get_with_permissions(membership.role_id)
            if role:
                permissions = {rp.permission.name for rp in role.role_permissions}
        
        # Fallback to legacy role if no role assigned
        if not permissions:
            permissions = self._get_legacy_permissions(membership.legacy_role)
        
        # Platform owners have all permissions
        if is_platform_owner:
            all_perms_result = await self.db.execute(select(Permission.name))
            permissions = {row[0] for row in all_perms_result.all()}
        
        # Get user's teams
        teams_result = await self.db.execute(
            select(Team)
            .join(TeamMembership, TeamMembership.team_id == Team.id)
            .where(
                TeamMembership.user_id == user_id,
                Team.organization_id == organization_id
            )
        )
        teams = list(teams_result.scalars().all())
        
        # Add team-based permissions (if team has default role)
        for team in teams:
            if team.default_role_id:
                team_role = await self.role_repo.get_with_permissions(team.default_role_id)
                if team_role:
                    for rp in team_role.role_permissions:
                        permissions.add(rp.permission.name)
        
        return AuthorizationContext(
            user_id=user_id,
            organization_id=organization_id,
            membership=membership,
            role=role,
            permissions=permissions,
            teams=teams,
            is_platform_owner=is_platform_owner,
        )
    
    async def get_service_account_context(
        self,
        service_account_id: UUID,
        organization_id: UUID
    ) -> Optional[AuthorizationContext]:
        """Get authorization context for a service account."""
        account = await self.service_account_repo.get_with_permissions(service_account_id)
        
        if not account or account.organization_id != organization_id:
            return None
        
        if account.status != ServiceAccountStatus.ACTIVE:
            return None
        
        if account.expires_at and account.expires_at < datetime.utcnow():
            return None
        
        permissions = {p.name for p in account.permissions}
        
        return AuthorizationContext(
            user_id=account.created_by or UUID(int=0),  # fallback
            organization_id=organization_id,
            membership=None,
            role=None,
            permissions=permissions,
            teams=[],
            is_service_account=True,
            service_account_id=service_account_id,
        )
    
    def _get_legacy_permissions(self, legacy_role: str) -> Set[str]:
        """Get permissions for legacy membership roles."""
        role_permissions = {
            "owner": [
                "organization:read", "organization:update", "organization:delete",
                "member:read", "member:invite", "member:update", "member:remove",
                "role:read", "role:create", "role:update", "role:delete",
                "team:read", "team:create", "team:update", "team:delete", "team:manage_members",
                "agent:read", "agent:create", "agent:update", "agent:delete", "agent:run",
                "workflow:read", "workflow:create", "workflow:update", "workflow:delete", "workflow:execute",
                "execution:read", "execution:cancel", "execution:retry",
                "tool:read", "tool:create", "tool:update", "tool:delete", "tool:use",
                "integration:read", "integration:create", "integration:update", "integration:delete",
                "connector:read", "connector:create", "connector:update", "connector:delete",
                "connector:execute", "connector:admin",
                "credential:read", "credential:create", "credential:update", "credential:delete",
                "credential:rotate",
                "api_key:read", "api_key:create", "api_key:revoke",
                "audit_log:read",
                "invitation:read", "invitation:create", "invitation:revoke",
                "service_account:read", "service_account:create", "service_account:update", "service_account:delete",
                "memory:read", "memory:create", "memory:update", "memory:delete",
                "conversation:read", "conversation:create", "conversation:update", "conversation:delete",
                "approval:read", "approval:create", "approval:approve", "approval:cancel",
                "approval:escalate", "approval:admin",
                "evaluation:read", "evaluation:create", "evaluation:decide",
                "evaluation:admin",
                "webhook:read", "webhook:create", "webhook:update", "webhook:delete",
                "mcp_server:read", "mcp_server:create", "mcp_server:update", "mcp_server:delete",
            ],
            "admin": [
                "organization:read", "organization:update",
                "member:read", "member:invite", "member:update", "member:remove",
                "role:read",
                "team:read", "team:create", "team:update", "team:delete", "team:manage_members",
                "agent:read", "agent:create", "agent:update", "agent:delete", "agent:run",
                "workflow:read", "workflow:create", "workflow:update", "workflow:delete", "workflow:execute",
                "execution:read", "execution:cancel", "execution:retry",
                "tool:read", "tool:create", "tool:update", "tool:delete", "tool:use",
                "integration:read", "integration:create", "integration:update", "integration:delete",
                "connector:read", "connector:create", "connector:update", "connector:delete",
                "connector:execute", "connector:admin",
                "credential:read", "credential:create", "credential:update", "credential:delete",
                "credential:rotate",
                "api_key:read", "api_key:create", "api_key:revoke",
                "audit_log:read",
                "invitation:read", "invitation:create", "invitation:revoke",
                "service_account:read", "service_account:create", "service_account:update", "service_account:delete",
                "memory:read", "memory:create", "memory:update", "memory:delete",
                "conversation:read", "conversation:create", "conversation:update", "conversation:delete",
                "approval:read", "approval:create", "approval:approve", "approval:cancel",
                "approval:escalate", "approval:admin",
                "evaluation:read", "evaluation:create", "evaluation:decide",
                "evaluation:admin",
                "webhook:read", "webhook:create", "webhook:update", "webhook:delete",
                "mcp_server:read", "mcp_server:create", "mcp_server:update", "mcp_server:delete",
            ],
            "developer": [
                "organization:read",
                "member:read",
                "role:read",
                "team:read",
                "agent:read", "agent:create", "agent:update", "agent:run",
                "workflow:read", "workflow:create", "workflow:update", "workflow:execute",
                "execution:read", "execution:retry",
                "tool:read", "tool:create", "tool:update", "tool:use",
                "integration:read", "integration:create", "integration:update",
                "connector:read", "connector:create", "connector:update",
                "connector:execute",
                "credential:read",
                "api_key:read", "api_key:create",
                "memory:read", "memory:create", "memory:update",
                "conversation:read", "conversation:create", "conversation:update",
                "approval:read", "approval:create",
                "evaluation:read", "evaluation:create", "evaluation:decide",
                "webhook:read", "webhook:create", "webhook:update",
                "mcp_server:read", "mcp_server:create", "mcp_server:update",
            ],
            "operator": [
                "organization:read",
                "member:read",
                "role:read",
                "team:read",
                "agent:read", "agent:run",
                "workflow:read", "workflow:execute",
                "execution:read", "execution:cancel", "execution:retry",
                "tool:read", "tool:use",
                "integration:read",
                "connector:read", "connector:execute",
                "credential:read",
                "api_key:read",
                "memory:read",
                "conversation:read",
                "approval:read", "approval:create", "approval:approve",
                "evaluation:read", "evaluation:create",
                "webhook:read",
                "mcp_server:read",
            ],
            "member": [
                "organization:read",
                "member:read",
                "role:read",
                "team:read",
                "agent:read", "agent:run",
                "workflow:read", "workflow:execute",
                "execution:read",
                "tool:read", "tool:use",
                "integration:read",
                "connector:read",
                "memory:read",
                "conversation:read", "conversation:create",
                "approval:read", "approval:create",
            ],
            "viewer": [
                "organization:read",
                "member:read",
                "role:read",
                "team:read",
                "agent:read",
                "workflow:read",
                "execution:read",
                "tool:read",
                "integration:read",
                "connector:read",
                "memory:read",
                "conversation:read",
            ],
        }
        return set(role_permissions.get(legacy_role, []))
    
    def check_permission(self, context: AuthorizationContext, permission: str) -> bool:
        """Check if context has a specific permission."""
        if context.is_platform_owner:
            return True
        return permission in context.permissions
    
    def check_any_permission(self, context: AuthorizationContext, permissions: List[str]) -> bool:
        """Check if context has any of the specified permissions."""
        if context.is_platform_owner:
            return True
        return any(p in context.permissions for p in permissions)
    
    def check_all_permissions(self, context: AuthorizationContext, permissions: List[str]) -> bool:
        """Check if context has all of the specified permissions."""
        if context.is_platform_owner:
            return True
        return all(p in context.permissions for p in permissions)
    
    def require_permission(self, context: AuthorizationContext, permission: str) -> None:
        """Require a permission, raise if not present."""
        if not self.check_permission(context, permission):
            raise AuthorizationError(
                f"Permission denied: {permission}",
                code="FORBIDDEN",
                required_permission=permission
            )
    
    def require_any_permission(self, context: AuthorizationContext, permissions: List[str]) -> None:
        """Require at least one permission, raise if none present."""
        if not self.check_any_permission(context, permissions):
            raise AuthorizationError(
                f"Permission denied: requires one of {permissions}",
                code="FORBIDDEN",
                required_permission=permissions[0] if permissions else None
            )
    
    def require_all_permissions(self, context: AuthorizationContext, permissions: List[str]) -> None:
        """Require all permissions, raise if any missing."""
        if not self.check_all_permissions(context, permissions):
            raise AuthorizationError(
                f"Permission denied: requires all of {permissions}",
                code="FORBIDDEN",
                required_permission=permissions[0] if permissions else None
            )
    
    def check_resource_access(
        self,
        context: AuthorizationContext,
        resource_organization_id: UUID,
        resource_owner_id: Optional[UUID] = None
    ) -> bool:
        """Check if context can access a resource in the given organization."""
        # Platform owners can access everything
        if context.is_platform_owner:
            return True
        
        # Must be in the same organization
        if context.organization_id != resource_organization_id:
            return False
        
        return True
    
    def require_resource_access(
        self,
        context: AuthorizationContext,
        resource_organization_id: UUID,
        resource_owner_id: Optional[UUID] = None
    ) -> None:
        """Require access to a resource in an organization."""
        if not self.check_resource_access(context, resource_organization_id, resource_owner_id):
            raise AuthorizationError(
                "Access denied to resource",
                code="FORBIDDEN"
            )


from datetime import datetime