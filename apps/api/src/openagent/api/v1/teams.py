from datetime import datetime
from typing import Optional, List
from uuid import UUID
from fastapi import APIRouter, Depends, Request, HTTPException, status, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from openagent.db.session import get_db
from openagent.db.models import Team, TeamMembership, TeamMembershipRole, User
from openagent.db.repositories import TeamRepository, TeamMembershipRepository, RoleRepository
from openagent.schemas.base import ApiErrorResponse, PaginationParams, PaginatedResponse
from openagent.api.dependencies import (
    get_current_org_context,
    require_permission,
)

router = APIRouter(prefix="/organizations/{organization_id}/teams", tags=["teams"])


# Team Schemas
class TeamBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=100, pattern="^[a-z0-9-]+$")
    description: Optional[str] = None
    avatar_url: Optional[str] = None
    default_role_id: Optional[UUID] = None


class TeamCreate(TeamBase):
    pass


class TeamUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    avatar_url: Optional[str] = None
    default_role_id: Optional[UUID] = None


class TeamMemberResponse(BaseModel):
    user_id: UUID
    email: str
    display_name: Optional[str]
    avatar_url: Optional[str]
    role: str
    joined_at: datetime

    class Config:
        from_attributes = True


class TeamResponse(TeamBase):
    id: UUID
    organization_id: UUID
    created_by: UUID
    metadata: dict
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None
    member_count: int = 0

    class Config:
        from_attributes = True


class TeamListResponse(PaginatedResponse[TeamResponse]):
    pass


class TeamMemberAdd(BaseModel):
    user_id: UUID
    role: str = Field(default="member", pattern="^(lead|member)$")


class TeamMemberUpdate(BaseModel):
    role: str = Field(pattern="^(lead|member)$")


@router.get(
    "",
    response_model=TeamListResponse,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}},
)
async def list_teams(
    request: Request,
    organization_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    auth_context = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """List all teams in the organization."""
    await require_permission("team:read")(request, db)
    
    repo = TeamRepository(db)
    teams = await repo.list_by_organization(organization_id, limit=1000)  # Get all for pagination
    
    # Get member counts
    from openagent.db.models import TeamMembership
    from sqlalchemy import func
    
    team_ids = [t.id for t in teams]
    member_counts = {}
    if team_ids:
        result = await db.execute(
            select(TeamMembership.team_id, func.count(TeamMembership.id))
            .where(TeamMembership.team_id.in_(team_ids))
            .group_by(TeamMembership.team_id)
        )
        member_counts = {row[0]: row[1] for row in result.all()}
    
    # Pagination
    start = (page - 1) * page_size
    end = start + page_size
    paginated = teams[start:end]
    
    # Add member counts
    for team in paginated:
        team.member_count = member_counts.get(team.id, 0)
    
    from openagent.db.pagination import create_pagination_meta
    meta = create_pagination_meta(page, page_size, len(teams))
    
    return TeamListResponse(data=paginated, meta=meta)


@router.post(
    "",
    response_model=TeamResponse,
    status_code=status.HTTP_201_CREATED,
    responses={400: {"model": ApiErrorResponse}, 401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 409: {"model": ApiErrorResponse}},
)
async def create_team(
    request: Request,
    organization_id: UUID,
    data: TeamCreate,
    auth_context = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Create a new team."""
    await require_permission("team:create")(request, db)
    
    repo = TeamRepository(db)
    
    # Check if slug already exists
    existing = await repo.get_by_slug(organization_id, data.slug)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "Team with this slug already exists", "code": "TEAM_SLUG_EXISTS"},
        )
    
    # Check if name already exists
    from sqlalchemy import select
    from openagent.db.models import Team
    existing_name = await db.execute(
        select(Team).where(Team.organization_id == organization_id, Team.name == data.name)
    )
    if existing_name.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "Team with this name already exists", "code": "TEAM_NAME_EXISTS"},
        )
    
    # Verify default_role_id if provided
    if data.default_role_id:
        role_repo = RoleRepository(db)
        role = await role_repo.get_by_id(data.default_role_id)
        if not role or (role.organization_id and role.organization_id != organization_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "Invalid default role", "code": "INVALID_DEFAULT_ROLE"},
            )
    
    team = await repo.create(
        organization_id=organization_id,
        name=data.name,
        slug=data.slug,
        description=data.description,
        avatar_url=data.avatar_url,
        default_role_id=data.default_role_id,
        created_by=auth_context.user_id,
    )
    
    await db.commit()
    await db.refresh(team)
    
    team.member_count = 0
    return team


@router.get(
    "/{team_id}",
    response_model=TeamResponse,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def get_team(
    request: Request,
    organization_id: UUID,
    team_id: UUID,
    auth_context = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Get a team by ID."""
    await require_permission("team:read")(request, db)
    
    repo = TeamRepository(db)
    team = await repo.get_with_memberships(team_id)
    
    if not team or team.organization_id != organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Team not found", "code": "TEAM_NOT_FOUND"},
        )
    
    team.member_count = len(team.memberships)
    return team


@router.patch(
    "/{team_id}",
    response_model=TeamResponse,
    responses={400: {"model": ApiErrorResponse}, 401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def update_team(
    request: Request,
    organization_id: UUID,
    team_id: UUID,
    data: TeamUpdate,
    auth_context = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Update a team."""
    await require_permission("team:update")(request, db)
    
    repo = TeamRepository(db)
    team = await repo.get_by_id(team_id)
    
    if not team or team.organization_id != organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Team not found", "code": "TEAM_NOT_FOUND"},
        )
    
    # Verify default_role_id if provided
    if data.default_role_id is not None:
        if data.default_role_id:
            role_repo = RoleRepository(db)
            role = await role_repo.get_by_id(data.default_role_id)
            if not role or (role.organization_id and role.organization_id != organization_id):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={"error": "Invalid default role", "code": "INVALID_DEFAULT_ROLE"},
                )
    
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(team, field, value)
    
    await db.commit()
    await db.refresh(team)
    
    team.member_count = len(team.memberships) if team.memberships else 0
    return team


@router.delete(
    "/{team_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def delete_team(
    request: Request,
    organization_id: UUID,
    team_id: UUID,
    auth_context = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Delete a team."""
    await require_permission("team:delete")(request, db)
    
    repo = TeamRepository(db)
    team = await repo.get_by_id(team_id)
    
    if not team or team.organization_id != organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Team not found", "code": "TEAM_NOT_FOUND"},
        )
    
    await repo.soft_delete(team_id)
    await db.commit()


# Team Membership Endpoints
@router.get(
    "/{team_id}/members",
    response_model=List[TeamMemberResponse],
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def list_team_members(
    request: Request,
    organization_id: UUID,
    team_id: UUID,
    auth_context = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """List all members of a team."""
    await require_permission("team:read")(request, db)
    
    repo = TeamRepository(db)
    team = await repo.get_with_memberships(team_id)
    
    if not team or team.organization_id != organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Team not found", "code": "TEAM_NOT_FOUND"},
        )
    
    members = []
    for membership in team.memberships:
        members.append(TeamMemberResponse(
            user_id=membership.user.id,
            email=membership.user.email,
            display_name=membership.user.display_name,
            avatar_url=membership.user.avatar_url,
            role=membership.role.value,
            joined_at=membership.created_at,
        ))
    
    return members


@router.post(
    "/{team_id}/members",
    response_model=TeamMemberResponse,
    status_code=status.HTTP_201_CREATED,
    responses={400: {"model": ApiErrorResponse}, 401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}, 409: {"model": ApiErrorResponse}},
)
async def add_team_member(
    request: Request,
    organization_id: UUID,
    team_id: UUID,
    data: TeamMemberAdd,
    auth_context = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Add a member to a team."""
    await require_permission("team:manage_members")(request, db)
    
    repo = TeamRepository(db)
    team = await repo.get_by_id(team_id)
    
    if not team or team.organization_id != organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Team not found", "code": "TEAM_NOT_FOUND"},
        )
    
    # Check if user exists and is a member of the organization
    from openagent.db.models import Membership, MembershipStatus
    membership = await db.execute(
        select(Membership).where(
            Membership.user_id == data.user_id,
            Membership.organization_id == organization_id,
            Membership.status == MembershipStatus.ACTIVE
        )
    )
    if not membership.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "User is not an active member of this organization", "code": "USER_NOT_MEMBER"},
        )
    
    # Check if already a member
    if await repo.is_member(team_id, data.user_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "User is already a member of this team", "code": "ALREADY_MEMBER"},
        )
    
    membership = await repo.add_member(team_id, data.user_id, data.role)
    await db.commit()
    
    # Get user details for response
    result = await db.execute(
        select(User).where(User.id == data.user_id)
    )
    user = result.scalar_one()
    
    return TeamMemberResponse(
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
        avatar_url=user.avatar_url,
        role=membership.role.value,
        joined_at=membership.created_at,
    )


@router.delete(
    "/{team_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def remove_team_member(
    request: Request,
    organization_id: UUID,
    team_id: UUID,
    user_id: UUID,
    auth_context = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Remove a member from a team."""
    await require_permission("team:manage_members")(request, db)
    
    repo = TeamRepository(db)
    team = await repo.get_by_id(team_id)
    
    if not team or team.organization_id != organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Team not found", "code": "TEAM_NOT_FOUND"},
        )
    
    removed = await repo.remove_member(team_id, user_id)
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "User is not a member of this team", "code": "NOT_MEMBER"},
        )
    
    await db.commit()


@router.patch(
    "/{team_id}/members/{user_id}",
    response_model=TeamMemberResponse,
    responses={400: {"model": ApiErrorResponse}, 401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def update_team_member_role(
    request: Request,
    organization_id: UUID,
    team_id: UUID,
    user_id: UUID,
    data: TeamMemberUpdate,
    auth_context = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Update a team member's role."""
    await require_permission("team:manage_members")(request, db)
    
    repo = TeamRepository(db)
    team = await repo.get_by_id(team_id)
    
    if not team or team.organization_id != organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Team not found", "code": "TEAM_NOT_FOUND"},
        )
    
    membership = await repo.update_member_role(team_id, user_id, TeamMembershipRole(data.role))
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "User is not a member of this team", "code": "NOT_MEMBER"},
        )
    
    await db.commit()
    
    # Get user details for response
    result = await db.execute(
        select(User).where(User.id == user_id)
    )
    user = result.scalar_one()
    
    return TeamMemberResponse(
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
        avatar_url=user.avatar_url,
        role=membership.role.value,
        joined_at=membership.created_at,
    )