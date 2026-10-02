from datetime import datetime
from typing import Optional, List
from uuid import UUID
from fastapi import APIRouter, Depends, Request, HTTPException, status, Query
from pydantic import BaseModel, Field, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession

from openagent.db.session import get_db
from openagent.db.models import OrganizationInvitation, InvitationStatus, Role
from openagent.db.repositories import OrganizationInvitationRepository, RoleRepository
from openagent.schemas.base import ApiErrorResponse, PaginatedResponse
from openagent.api.dependencies import (
    get_current_org_context,
    require_permission,
)
from openagent.services.email import EmailService, create_email_provider_from_settings
from openagent.core.config import get_settings

router = APIRouter(prefix="/organizations/{organization_id}/invitations", tags=["invitations"])


# Invitation Schemas
class InvitationCreate(BaseModel):
    email: EmailStr
    role_id: UUID


class InvitationResponse(BaseModel):
    id: UUID
    organization_id: UUID
    email: str
    role_id: UUID
    role_name: str
    invited_by: UUID
    inviter_name: Optional[str]
    status: str
    expires_at: datetime
    accepted_at: Optional[datetime]
    revoked_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class InvitationListResponse(PaginatedResponse[InvitationResponse]):
    pass


class InvitationAccept(BaseModel):
    token: str


class InvitationAcceptResponse(BaseModel):
    message: str
    user_id: Optional[UUID] = None


class InvitationResend(BaseModel):
    pass


@router.get(
    "",
    response_model=InvitationListResponse,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}},
)
async def list_invitations(
    request: Request,
    organization_id: UUID,
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    auth_context = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """List all invitations for the organization."""
    await require_permission("invitation:read")(request, db)
    
    repo = OrganizationInvitationRepository(db)
    
    status_filter = None
    if status:
        try:
            status_filter = InvitationStatus(status)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": f"Invalid status: {status}", "code": "INVALID_STATUS"},
            )
    
    invitations = await repo.list_by_organization(
        organization_id,
        status=status_filter,
        limit=1000,
    )
    
    # Get role names and inviter names
    from openagent.db.models import Role, User
    from sqlalchemy import select
    
    role_ids = [inv.role_id for inv in invitations]
    inviter_ids = [inv.invited_by for inv in invitations]
    
    roles = {}
    if role_ids:
        result = await db.execute(select(Role).where(Role.id.in_(role_ids)))
        roles = {r.id: r.display_name for r in result.scalars().all()}
    
    inviters = {}
    if inviter_ids:
        result = await db.execute(select(User).where(User.id.in_(inviter_ids)))
        inviters = {u.id: u.display_name for u in result.scalars().all()}
    
    # Pagination
    start = (page - 1) * page_size
    end = start + page_size
    paginated = invitations[start:end]
    
    # Build responses
    responses = []
    for inv in paginated:
        responses.append(InvitationResponse(
            id=inv.id,
            organization_id=inv.organization_id,
            email=inv.email,
            role_id=inv.role_id,
            role_name=roles.get(inv.role_id, "Unknown"),
            invited_by=inv.invited_by,
            inviter_name=inviters.get(inv.invited_by),
            status=inv.status.value,
            expires_at=inv.expires_at,
            accepted_at=inv.accepted_at,
            revoked_at=inv.revoked_at,
            created_at=inv.created_at,
            updated_at=inv.updated_at,
        ))
    
    from openagent.db.pagination import create_pagination_meta
    meta = create_pagination_meta(page, page_size, len(invitations))
    
    return InvitationListResponse(data=responses, meta=meta)


@router.post(
    "",
    response_model=InvitationResponse,
    status_code=status.HTTP_201_CREATED,
    responses={400: {"model": ApiErrorResponse}, 401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 409: {"model": ApiErrorResponse}},
)
async def create_invitation(
    request: Request,
    organization_id: UUID,
    data: InvitationCreate,
    auth_context = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Create a new organization invitation."""
    await require_permission("invitation:create")(request, db)
    
    # Check if role exists and belongs to organization
    role_repo = RoleRepository(db)
    role = await role_repo.get_by_id(data.role_id)
    if not role or (role.organization_id and role.organization_id != organization_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "Invalid role for this organization", "code": "INVALID_ROLE"},
        )
    
    repo = OrganizationInvitationRepository(db)
    
    # Check if there's already a pending invitation for this email
    existing = await repo.get_pending_by_email(organization_id, data.email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "Pending invitation already exists for this email", "code": "INVITATION_EXISTS"},
        )
    
    # Create invitation
    invitation, token = await repo.create_invitation(
        organization_id=organization_id,
        email=data.email,
        role_id=data.role_id,
        invited_by=auth_context.user_id,
    )
    
    await db.commit()
    
    # Send invitation email
    from openagent.services.email import EmailService, create_email_provider_from_settings
    email_service = EmailService(create_email_provider_from_settings())
    settings = get_settings()
    
    # Build acceptance URL
    accept_url = f"{settings.FRONTEND_VERIFY_EMAIL_URL}/accept?token={token}"
    
    await email_service.send_email(
        to=data.email,
        subject=f"Invitation to join {organization_id}",
        html_content=f"""
        <p>You've been invited to join the organization.</p>
        <p><a href="{accept_url}">Accept Invitation</a></p>
        <p>This invitation expires in 7 days.</p>
        """,
    )
    
    # Get role name for response
    role = await role_repo.get_by_id(data.role_id)
    
    await db.refresh(invitation)
    return InvitationResponse(
        id=invitation.id,
        organization_id=invitation.organization_id,
        email=invitation.email,
        role_id=invitation.role_id,
        role_name=role.display_name if role else "Unknown",
        invited_by=invitation.invited_by,
        inviter_name=None,
        status=invitation.status.value,
        expires_at=invitation.expires_at,
        accepted_at=invitation.accepted_at,
        revoked_at=invitation.revoked_at,
        created_at=invitation.created_at,
        updated_at=invitation.updated_at,
    )


@router.post(
    "/accept",
    response_model=InvitationAcceptResponse,
    responses={400: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def accept_invitation(
    request: Request,
    data: InvitationAccept,
    db: AsyncSession = Depends(get_db),
):
    """Accept an organization invitation."""
    from openagent.core.security.tokens import verify_token, hash_token
    
    token_hash = hash_token(data.token)
    repo = OrganizationInvitationRepository(db)
    invitation = await repo.get_by_token_hash(token_hash)
    
    if not invitation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Invalid invitation token", "code": "INVALID_TOKEN"},
        )
    
    if invitation.status != InvitationStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": f"Invitation is {invitation.status.value}", "code": "INVALID_STATUS"},
        )
    
    if datetime.utcnow() > invitation.expires_at:
        invitation.status = InvitationStatus.EXPIRED
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "Invitation has expired", "code": "TOKEN_EXPIRED"},
        )
    
    # Check if user already exists
    from openagent.db.models import User, UserStatus
    from openagent.db.repositories import UserRepository
    
    user_repo = UserRepository(db)
    user = await user_repo.get_by_email(invitation.email)
    
    if not user:
        # Create user account (they'll need to set password on first login)
        user = await user_repo.create(
            email=invitation.email,
            status=UserStatus.ACTIVE,
            email_verified=True,
        )
        await db.flush()
    
    # Create membership
    from openagent.db.models import Membership, MembershipStatus, MembershipRole
    membership = Membership(
        user_id=user.id,
        organization_id=invitation.organization_id,
        role_id=invitation.role_id,
        legacy_role=MembershipRole.MEMBER,
        status=MembershipStatus.ACTIVE,
    )
    db.add(membership)
    
    # Accept invitation
    await repo.accept(invitation)
    await db.commit()
    
    return InvitationAcceptResponse(
        message="Invitation accepted successfully",
        user_id=user.id,
    )


@router.post(
    "/{invitation_id}/revoke",
    response_model=InvitationResponse,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def revoke_invitation(
    request: Request,
    organization_id: UUID,
    invitation_id: UUID,
    auth_context = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Revoke an invitation."""
    await require_permission("invitation:revoke")(request, db)
    
    repo = OrganizationInvitationRepository(db)
    invitation = await repo.get_by_id(invitation_id)
    
    if not invitation or invitation.organization_id != organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Invitation not found", "code": "INVITATION_NOT_FOUND"},
        )
    
    if invitation.status != InvitationStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": f"Cannot revoke {invitation.status.value} invitation", "code": "INVALID_STATUS"},
        )
    
    await repo.revoke(invitation, auth_context.user_id)
    await db.commit()
    
    role = await db.execute(select(Role).where(Role.id == invitation.role_id))
    role_obj = role.scalar_one_or_none()
    
    return InvitationResponse(
        id=invitation.id,
        organization_id=invitation.organization_id,
        email=invitation.email,
        role_id=invitation.role_id,
        role_name=role_obj.display_name if role_obj else "Unknown",
        invited_by=invitation.invited_by,
        inviter_name=None,
        status=invitation.status.value,
        expires_at=invitation.expires_at,
        accepted_at=invitation.accepted_at,
        revoked_at=invitation.revoked_at,
        created_at=invitation.created_at,
        updated_at=invitation.updated_at,
    )


@router.post(
    "/{invitation_id}/resend",
    response_model=InvitationResponse,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def resend_invitation(
    request: Request,
    organization_id: UUID,
    invitation_id: UUID,
    auth_context = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Resend an invitation with a new token."""
    await require_permission("invitation:create")(request, db)
    
    repo = OrganizationInvitationRepository(db)
    invitation = await repo.get_by_id(invitation_id)
    
    if not invitation or invitation.organization_id != organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Invitation not found", "code": "INVITATION_NOT_FOUND"},
        )
    
    if invitation.status not in (InvitationStatus.PENDING, InvitationStatus.EXPIRED):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": f"Cannot resend {invitation.status.value} invitation", "code": "INVALID_STATUS"},
        )
    
    invitation, token = await repo.resend_invitation(invitation)
    await db.commit()
    
    # Send invitation email
    email_service = EmailService(create_email_provider_from_settings())
    settings = get_settings()
    accept_url = f"{settings.FRONTEND_VERIFY_EMAIL_URL}/accept?token={token}"
    
    await email_service.send_email(
        to=invitation.email,
        subject=f"Invitation to join organization",
        html_content=f"""
        <p>You've been invited to join the organization.</p>
        <p><a href="{accept_url}">Accept Invitation</a></p>
        <p>This invitation expires in 7 days.</p>
        """,
    )
    
    role = await db.execute(select(Role).where(Role.id == invitation.role_id))
    role_obj = role.scalar_one_or_none()
    
    return InvitationResponse(
        id=invitation.id,
        organization_id=invitation.organization_id,
        email=invitation.email,
        role_id=invitation.role_id,
        role_name=role_obj.display_name if role_obj else "Unknown",
        invited_by=invitation.invited_by,
        inviter_name=None,
        status=invitation.status.value,
        expires_at=invitation.expires_at,
        accepted_at=invitation.accepted_at,
        revoked_at=invitation.revoked_at,
        created_at=invitation.created_at,
        updated_at=invitation.updated_at,
    )


@router.post(
    "/expire",
    response_model=dict,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}},
)
async def expire_old_invitations(
    request: Request,
    organization_id: UUID,
    auth_context = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Manually expire old pending invitations."""
    await require_permission("invitation:revoke")(request, db)
    
    repo = OrganizationInvitationRepository(db)
    count = await repo.expire_old_invitations()
    await db.commit()
    
    return {"message": f"Expired {count} invitations", "expired_count": count}