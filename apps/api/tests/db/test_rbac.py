import pytest
import pytest_asyncio
from uuid import uuid4
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from openagent.db.models import (
    User, UserStatus,
    Organization, OrganizationStatus,
    Membership, MembershipRole, MembershipStatus,
    Permission, PermissionResource, PermissionAction, PermissionScope,
    Role, RoleType, RolePermission,
    Team, TeamMembership, TeamMembershipRole,
    OrganizationInvitation, InvitationStatus,
    ServiceAccount, ServiceAccountStatus,
)
from openagent.db.repositories import (
    UserRepository,
    OrganizationRepository,
    MembershipRepository,
    PermissionRepository,
    RoleRepository,
    TeamRepository,
    OrganizationInvitationRepository,
    ServiceAccountRepository,
)
from openagent.services.authorization import AuthorizationService


@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> Organization:
    repo = OrganizationRepository(db_session)
    org = await repo.create(
        name="Test Organization",
        slug="test-org-rbac",
        status=OrganizationStatus.ACTIVE
    )
    await db_session.commit()
    return org


@pytest_asyncio.fixture
async def user(db_session: AsyncSession) -> User:
    repo = UserRepository(db_session)
    user = await repo.create(
        email="test-rbac@example.com",
        display_name="Test User",
        status=UserStatus.ACTIVE,
        email_verified=True,
    )
    await db_session.commit()
    return user


@pytest_asyncio.fixture
async def membership(db_session: AsyncSession, user: User, org: Organization) -> Membership:
    repo = MembershipRepository(db_session)
    membership = await repo.create(
        user_id=user.id,
        organization_id=org.id,
        role=MembershipRole.MEMBER,
        status=MembershipStatus.ACTIVE,
    )
    await db_session.commit()
    return membership


@pytest_asyncio.fixture
async def permissions(db_session: AsyncSession) -> dict:
    """Create test permissions."""
    perms = {}
    for resource, action, desc in [
        ("workflow", "create", "Create workflows"),
        ("workflow", "read", "Read workflows"),
        ("workflow", "execute", "Execute workflows"),
        ("agent", "create", "Create agents"),
        ("agent", "run", "Run agents"),
        ("member", "invite", "Invite members"),
    ]:
        perm = Permission(
            name=f"{resource}:{action}",
            resource=PermissionResource(resource),
            action=PermissionAction(action),
            scope=PermissionScope.ORGANIZATION,
            description=desc,
            is_system=True,
            danger_level=2,
        )
        db_session.add(perm)
        perms[f"{resource}:{action}"] = perm
    await db_session.commit()
    return perms


@pytest_asyncio.fixture
async def role(db_session: AsyncSession, permissions: dict) -> Role:
    role = Role(
        name="test_developer",
        display_name="Test Developer",
        description="Test developer role",
        role_type=RoleType.CUSTOM,
        is_system=False,
        priority=50,
    )
    db_session.add(role)
    await db_session.flush()
    
    # Assign permissions
    for perm_name in ["workflow:create", "workflow:read", "workflow:execute", "agent:create", "agent:run"]:
        if perm_name in permissions:
            rp = RolePermission(role_id=role.id, permission_id=permissions[perm_name].id)
            db_session.add(rp)
    
    await db_session.commit()
    return role


class TestPermissionModel:
    async def test_create_permission(self, db_session: AsyncSession):
        perm = Permission(
            name="test:action",
            resource=PermissionResource.AGENT,
            action=PermissionAction.CREATE,
            scope=PermissionScope.ORGANIZATION,
            description="Test permission",
            is_system=True,
        )
        db_session.add(perm)
        await db_session.commit()
        
        assert perm.id is not None
        assert perm.name == "test:action"
        assert perm.resource == PermissionResource.AGENT
        assert perm.action == PermissionAction.CREATE
        assert perm.full_name == "agent:create"

    async def test_unique_permission_name(self, db_session: AsyncSession):
        perm1 = Permission(
            name="unique:test",
            resource=PermissionResource.AGENT,
            action=PermissionAction.CREATE,
            is_system=True,
        )
        db_session.add(perm1)
        await db_session.commit()
        
        perm2 = Permission(
            name="unique:test",
            resource=PermissionResource.WORKFLOW,
            action=PermissionAction.READ,
            is_system=True,
        )
        db_session.add(perm2)
        with pytest.raises(Exception):
            await db_session.commit()


class TestRoleModel:
    async def test_create_role(self, db_session: AsyncSession):
        role = Role(
            name="custom_role",
            display_name="Custom Role",
            description="A custom role",
            role_type=RoleType.CUSTOM,
            is_system=False,
            priority=10,
        )
        db_session.add(role)
        await db_session.commit()
        
        assert role.id is not None
        assert role.name == "custom_role"
        assert role.role_type == RoleType.CUSTOM

    async def test_role_permission_assignment(self, db_session: AsyncSession, permissions: dict):
        role = Role(
            name="test_role",
            display_name="Test Role",
            role_type=RoleType.CUSTOM,
        )
        db_session.add(role)
        await db_session.flush()
        
        rp = RolePermission(role_id=role.id, permission_id=permissions["workflow:create"].id)
        db_session.add(rp)
        await db_session.commit()
        
        # Verify relationship
        result = await db_session.execute(
            select(RolePermission).where(RolePermission.role_id == role.id)
        )
        role_perms = list(result.scalars().all())
        assert len(role_perms) == 1
        assert role_perms[0].permission_id == permissions["workflow:create"].id


class TestAuthorizationService:
    async def test_get_user_context(self, db_session: AsyncSession, user: User, org: Organization, membership: Membership, role: Role):
        # Assign role to membership
        membership.role_id = role.id
        await db_session.commit()
        
        authz = AuthorizationService(db_session)
        context = await authz.get_user_context(user.id, org.id)
        
        assert context is not None
        assert context.user_id == user.id
        assert context.organization_id == org.id
        assert context.membership is not None
        assert context.role is not None
        assert "workflow:create" in context.permissions
        assert "workflow:read" in context.permissions

    async def test_check_permission(self, db_session: AsyncSession, user: User, org: Organization, membership: Membership, role: Role):
        membership.role_id = role.id
        await db_session.commit()
        
        authz = AuthorizationService(db_session)
        context = await authz.get_user_context(user.id, org.id)
        
        assert authz.check_permission(context, "workflow:create") is True
        assert authz.check_permission(context, "workflow:read") is True
        assert authz.check_permission(context, "member:invite") is False

    async def test_require_permission_raises(self, db_session: AsyncSession, user: User, org: Organization, membership: Membership, role: Role):
        membership.role_id = role.id
        await db_session.commit()
        
        authz = AuthorizationService(db_session)
        context = await authz.get_user_context(user.id, org.id)
        
        with pytest.raises(Exception) as exc:
            authz.require_permission(context, "member:invite")
        assert exc.value.code == "FORBIDDEN"

    async def test_platform_owner_has_all_permissions(self, db_session: AsyncSession, user: User, org: Organization):
        # Make user a platform owner
        from openagent.db.models import PlatformOwner, PlatformOwnerStatus
        platform_owner = PlatformOwner(
            user_id=user.id,
            status=PlatformOwnerStatus.ACTIVE,
        )
        db_session.add(platform_owner)
        
        membership.organization_id = org.id
        membership.status = MembershipStatus.ACTIVE
        await db_session.commit()
        
        authz = AuthorizationService(db_session)
        context = await authz.get_user_context(user.id, org.id)
        
        assert context.is_platform_owner is True
        assert authz.check_permission(context, "platform:manage_users") is True
        assert authz.check_permission(context, "any:permission") is True

    async def test_cross_tenant_isolation(self, db_session: AsyncSession, user: User, org: Organization, membership: Membership, role: Role):
        # Create second organization
        org2 = Organization(
            name="Org 2",
            slug="org-2",
            status=OrganizationStatus.ACTIVE,
        )
        db_session.add(org2)
        await db_session.flush()
        
        membership2 = Membership(
            user_id=user.id,
            organization_id=org2.id,
            status=MembershipStatus.ACTIVE,
        )
        db_session.add(membership2)
        await db_session.commit()
        
        authz = AuthorizationService(db_session)
        context1 = await authz.get_user_context(user.id, org.id)
        context2 = await authz.get_user_context(user.id, org2.id)
        
        # Check resource access isolation
        assert authz.check_resource_access(context1, org.id) is True
        assert authz.check_resource_access(context1, org2.id) is False
        assert authz.check_resource_access(context2, org2.id) is True
        assert authz.check_resource_access(context2, org.id) is False


class TestTeamModel:
    async def test_create_team(self, db_session: AsyncSession, org: Organization, user: User):
        team = Team(
            organization_id=org.id,
            name="Engineering",
            slug="engineering",
            description="Engineering team",
            created_by=user.id,
        )
        db_session.add(team)
        await db_session.commit()
        
        assert team.id is not None
        assert team.organization_id == org.id
        assert team.slug == "engineering"

    async def test_team_membership(self, db_session: AsyncSession, org: Organization, user: User):
        team = Team(
            organization_id=org.id,
            name="Engineering",
            slug="engineering",
            created_by=user.id,
        )
        db_session.add(team)
        await db_session.flush()
        
        membership = TeamMembership(
            team_id=team.id,
            user_id=user.id,
            role=TeamMembershipRole.LEAD,
        )
        db_session.add(membership)
        await db_session.commit()
        
        assert membership.id is not None
        assert membership.role == TeamMembershipRole.LEAD


class TestOrganizationInvitation:
    async def test_create_invitation(self, db_session: AsyncSession, org: Organization, user: User, role: Role):
        repo = OrganizationInvitationRepository(db_session)
        
        invitation, token = await repo.create_invitation(
            organization_id=org.id,
            email="invitee@example.com",
            role_id=role.id,
            invited_by=user.id,
        )
        await db_session.commit()
        
        assert invitation.id is not None
        assert invitation.email == "invitee@example.com"
        assert invitation.role_id == role.id
        assert invitation.status == InvitationStatus.PENDING
        assert token is not None

    async def test_invitation_accept(self, db_session: AsyncSession, org: Organization, user: User, role: Role):
        repo = OrganizationInvitationRepository(db_session)
        
        invitation, token = await repo.create_invitation(
            organization_id=org.id,
            email="newuser@example.com",
            role_id=role.id,
            invited_by=user.id,
        )
        await db_session.commit()
        
        # Accept invitation
        accepted = await repo.accept(invitation)
        await db_session.commit()
        
        assert accepted.status == InvitationStatus.ACCEPTED
        assert accepted.accepted_at is not None


class TestServiceAccount:
    async def test_create_service_account(self, db_session: AsyncSession, org: Organization, user: User, permissions: dict):
        repo = ServiceAccountRepository(db_session)
        
        account, raw_key = await repo.create_service_account(
            organization_id=org.id,
            name="Test Service Account",
            description="Test service account",
            created_by=user.id,
            permissions=[permissions["workflow:read"].id, permissions["agent:run"].id],
        )
        await db_session.commit()
        
        assert account.id is not None
        assert account.name == "Test Service Account"
        assert account.key_prefix.startswith("sa_")
        assert raw_key is not None
        assert len(raw_key) > 0

    async def test_service_account_permissions(self, db_session: AsyncSession, org: Organization, user: User, permissions: dict):
        repo = ServiceAccountRepository(db_session)
        
        account, _ = await repo.create_service_account(
            organization_id=org.id,
            name="Test SA",
            created_by=user.id,
            permissions=[permissions["workflow:read"].id, permissions["agent:run"].id],
        )
        await db_session.commit()
        
        # Get permissions
        perms = await repo.get_permissions(account.id)
        assert permissions["workflow:read"].id in perms
        assert permissions["agent:run"].id in perms
        assert permissions["workflow:create"].id not in perms


class TestRepositoryQueries:
    async def test_permission_repository(self, db_session: AsyncSession, permissions: dict):
        repo = PermissionRepository(db_session)
        
        # Get by name
        perm = await repo.get_by_name("workflow:create")
        assert perm is not None
        assert perm.name == "workflow:create"
        
        # List by resource
        perms = await repo.list_by_resource(PermissionResource.WORKFLOW)
        assert len(perms) >= 3  # create, read, execute
        
        # List by scope
        perms = await repo.list_by_scope("organization")
        assert len(perms) > 0

    async def test_role_repository(self, db_session: AsyncSession, role: Role):
        repo = RoleRepository(db_session)
        
        # Get with permissions
        role_with_perms = await repo.get_with_permissions(role.id)
        assert role_with_perms is not None
        assert len(role_with_perms.role_permissions) > 0
        
        # Get permissions
        perms = await repo.get_permissions(role.id)
        assert len(perms) > 0

    async def test_team_repository(self, db_session: AsyncSession, org: Organization, user: User):
        repo = TeamRepository(db_session)
        
        team = await repo.create(
            organization_id=org.id,
            name="Test Team",
            slug="test-team",
            created_by=user.id,
        )
        await db_session.commit()
        
        # Get by slug
        found = await repo.get_by_slug(org.id, "test-team")
        assert found is not None
        assert found.id == team.id
        
        # List by organization
        teams = await repo.list_by_organization(org.id)
        assert len(teams) >= 1

    async def test_invitation_repository(self, db_session: AsyncSession, org: Organization, user: User, role: Role):
        repo = OrganizationInvitationRepository(db_session)
        
        invitation, token = await repo.create_invitation(
            organization_id=org.id,
            email="test@example.com",
            role_id=role.id,
            invited_by=user.id,
        )
        await db_session.commit()
        
        # Get by token hash
        from openagent.core.security.tokens import hash_token
        found = await repo.get_by_token_hash(hash_token(token))
        assert found is not None
        assert found.id == invitation.id
        
        # List by organization
        invitations = await repo.list_by_organization(org.id)
        assert len(invitations) >= 1

    async def test_service_account_repository(self, db_session: AsyncSession, org: Organization, user: User, permissions: dict):
        repo = ServiceAccountRepository(db_session)
        
        account, raw_key = await repo.create_service_account(
            organization_id=org.id,
            name="Test SA",
            created_by=user.id,
            permissions=[permissions["workflow:read"].id],
        )
        await db_session.commit()
        
        # Get by key prefix
        found = await repo.get_by_key_prefix(account.key_prefix)
        assert found is not None
        assert found.id == account.id
        
        # Get by key hash
        from openagent.core.security.tokens import hash_token
        found = await repo.get_by_key_hash(hash_token(raw_key))
        assert found is not None
        assert found.id == account.id