"""Browser automation API — sessions, pages, tasks, actions, profiles, policies, events.

All routes are tenant-scoped via the standard org context (X-Organization-ID +
session), RBAC permission ``browser:execute``, and fail-closed URL/policy gates
in :class:`openagent.browser.service.BrowserService`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from openagent.api.dependencies import get_current_org_context
from openagent.browser.service import (
    BrowserNotFound,
    BrowserPolicyDenied,
    BrowserSecurityError,
    BrowserService,
)
from openagent.db.session import get_db
from openagent.services.authorization import AuthorizationContext

router = APIRouter(prefix="/browser", tags=["browser"])


def _deny(exc: Exception) -> HTTPException:
    if isinstance(exc, BrowserPolicyDenied):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, BrowserSecurityError):
        return HTTPException(status_code=status.HTTP_429_FORBIDDEN if False else status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if isinstance(exc, BrowserNotFound):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Browser operation failed")


# ---------------------------------------------------------------- schemas ---
class BrowserProviderConfig(BaseModel):
    type: str = Field(default="playwright")
    browser_type: str = Field(default="chromium")
    headless: bool = Field(default=True)
    viewport: Optional[Dict[str, int]] = None
    user_agent: Optional[str] = None
    locale: Optional[str] = None
    timezone_id: Optional[str] = None
    proxy: Optional[Dict[str, str]] = None
    timeout: int = Field(default=30000)


class CreateSessionRequest(BaseModel):
    browser_profile_id: Optional[UUID] = None
    provider_config: Optional[BrowserProviderConfig] = None
    headless: Optional[bool] = None
    metadata: Optional[Dict[str, Any]] = None


class SessionResponse(BaseModel):
    id: UUID
    session_id: str
    organization_id: UUID
    user_id: Optional[UUID] = None
    agent_id: Optional[UUID] = None
    workflow_execution_id: Optional[UUID] = None
    browser_profile_id: Optional[UUID] = None
    provider: str
    status: str
    headless: bool
    created_at: datetime
    last_activity_at: datetime
    expires_at: datetime

    class Config:
        from_attributes = True


class UpdateSessionRequest(BaseModel):
    status: Optional[str] = None


class PageResponse(BaseModel):
    id: UUID
    page_id: str
    url: str
    title: Optional[str] = None
    status: str
    created_at: datetime
    last_activity_at: datetime
    is_popup: bool = False
    opener_page_id: Optional[UUID] = None

    class Config:
        from_attributes = True


class CreatePageRequest(BaseModel):
    url: Optional[str] = None
    is_popup: bool = False
    opener_page_id: Optional[UUID] = None


class CreateTaskRequest(BaseModel):
    browser_session_id: UUID
    objective: str = Field(min_length=1, max_length=4000)
    max_steps: int = Field(default=100, ge=1, le=500)
    timeout: int = Field(default=300000, ge=1000, le=3600000)
    risk_policy: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None


class TaskResponse(BaseModel):
    id: UUID
    task_id: str
    organization_id: UUID
    agent_id: Optional[UUID] = None
    browser_session_id: UUID
    status: str
    objective: str
    current_url: Optional[str] = None
    current_page_id: Optional[UUID] = None
    current_step: int
    max_steps: int
    timeout: int
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class TaskActionRequest(BaseModel):
    action_type: str
    page_id: UUID
    input: Dict[str, Any] = Field(default_factory=dict)
    approved: bool = False
    approval_id: Optional[UUID] = Field(default=None,
                                        description="Persisted approval authorizing this exact action")


class RecordObservationRequest(BaseModel):
    url: str
    title: str = ""
    elements: List[Dict[str, Any]] = Field(default_factory=list)
    text: str = ""
    strategy: str = Field(default="standard", pattern="^(minimal|standard|detailed|visual|custom)$")
    action_id: Optional[UUID] = None


class ProfileCreateRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=255)
    browser_type: str = "chromium"
    profile_type: str = "EPHEMERAL"
    storage_state: Optional[Dict[str, Any]] = None
    policy: Optional[Dict[str, Any]] = None


class ProfileResponse(BaseModel):
    id: UUID
    organization_id: UUID
    owner_id: UUID
    display_name: str
    browser_type: str
    profile_type: str
    policy: Dict[str, Any]
    created_at: datetime
    updated_at: datetime
    last_used_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class DomainPolicyRequest(BaseModel):
    domain: str = Field(min_length=1, max_length=255)
    action: str = Field(pattern="^(ALLOW|DENY|CONFIRM)$")
    priority: int = 0
    reason: Optional[str] = None


class DomainPolicyResponse(BaseModel):
    id: UUID
    organization_id: Optional[UUID] = None
    domain: str
    action: str
    priority: int
    reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


def _session_out(s) -> dict:
    return {"id": s.id, "session_id": s.session_id, "organization_id": s.organization_id,
            "user_id": s.user_id, "agent_id": s.agent_id,
            "workflow_execution_id": s.workflow_execution_id,
            "browser_profile_id": s.browser_profile_id,
            "provider": s.provider.value if hasattr(s.provider, "value") else str(s.provider),
            "status": s.status.value if hasattr(s.status, "value") else str(s.status),
            "headless": s.headless, "created_at": s.created_at,
            "last_activity_at": s.last_activity_at, "expires_at": s.expires_at}


def _task_out(t) -> dict:
    return {"id": t.id, "task_id": t.task_id, "organization_id": t.organization_id,
            "agent_id": t.agent_id, "browser_session_id": t.browser_session_id,
            "status": t.status.value if hasattr(t.status, "value") else str(t.status),
            "objective": t.objective, "current_url": t.current_url,
            "current_page_id": t.current_page_id, "current_step": t.current_step,
            "max_steps": t.max_steps, "timeout": t.timeout,
            "created_at": t.created_at, "updated_at": t.updated_at, "completed_at": t.completed_at}


# --------------------------------------------------------------- sessions ---
@router.post("/sessions", response_model=SessionResponse)
async def create_session(
    request: CreateSessionRequest,
    ctx: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    try:
        service = BrowserService(db)
        s = await service.create_session(
            organization_id=ctx.organization_id, user_id=ctx.user_id,
            browser_profile_id=request.browser_profile_id,
            provider_config=request.provider_config.model_dump() if request.provider_config else None,
            headless=request.headless, metadata=request.metadata)
        return _session_out(s)
    except (BrowserSecurityError, BrowserPolicyDenied) as exc:
        raise _deny(exc)


@router.get("/sessions", response_model=List[SessionResponse])
async def list_sessions(
    stat: Optional[str] = Query(default=None, alias="status"),
    limit: int = Query(default=50, le=100),
    offset: int = Query(default=0, ge=0),
    ctx: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    service = BrowserService(db)
    sessions = await service.list_sessions(organization_id=ctx.organization_id, status=stat,
                                           limit=limit, offset=offset)
    return [_session_out(s) for s in sessions]


@router.get("/sessions/{session_id}", response_model=SessionResponse)
async def get_session(
    session_id: str,
    ctx: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    service = BrowserService(db)
    s = await service.get_session(session_id, ctx.organization_id)
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    return _session_out(s)


@router.patch("/sessions/{session_id}", response_model=SessionResponse)
async def update_session(
    session_id: str,
    request: UpdateSessionRequest,
    ctx: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    try:
        service = BrowserService(db)
        s = await service.update_session(session_id, ctx.organization_id, request.status)
        if not s:
            raise HTTPException(status_code=404, detail="Session not found")
        return _session_out(s)
    except (BrowserSecurityError, BrowserNotFound) as exc:
        raise _deny(exc)


@router.post("/sessions/{session_id}/pause")
async def pause_session(session_id: str, ctx: AuthorizationContext = Depends(get_current_org_context),
                        db: AsyncSession = Depends(get_db)):
    try:
        await BrowserService(db).pause_session(session_id, ctx.organization_id)
        return {"success": True}
    except (BrowserSecurityError, BrowserNotFound) as exc:
        raise _deny(exc)


@router.post("/sessions/{session_id}/resume")
async def resume_session(session_id: str, ctx: AuthorizationContext = Depends(get_current_org_context),
                         db: AsyncSession = Depends(get_db)):
    try:
        await BrowserService(db).resume_session(session_id, ctx.organization_id)
        return {"success": True}
    except (BrowserSecurityError, BrowserNotFound) as exc:
        raise _deny(exc)


@router.post("/sessions/{session_id}/heartbeat")
async def heartbeat(session_id: str, ctx: AuthorizationContext = Depends(get_current_org_context),
                    db: AsyncSession = Depends(get_db)):
    try:
        await BrowserService(db).heartbeat(session_id, ctx.organization_id)
        return {"success": True}
    except (BrowserSecurityError, BrowserNotFound) as exc:
        raise _deny(exc)


@router.delete("/sessions/{session_id}")
async def close_session(session_id: str, force: bool = False,
                        ctx: AuthorizationContext = Depends(get_current_org_context),
                        db: AsyncSession = Depends(get_db)):
    try:
        await BrowserService(db).close_session(session_id, ctx.organization_id, force)
        return {"success": True}
    except (BrowserSecurityError, BrowserNotFound) as exc:
        raise _deny(exc)


# ------------------------------------------------------------------ pages ---
@router.post("/sessions/{session_id}/pages", response_model=PageResponse)
async def create_page(session_id: str, request: CreatePageRequest,
                      ctx: AuthorizationContext = Depends(get_current_org_context),
                      db: AsyncSession = Depends(get_db)):
    try:
        p = await BrowserService(db).create_page(
            session_id=session_id, organization_id=ctx.organization_id, url=request.url,
            is_popup=request.is_popup, opener_page_id=request.opener_page_id)
        return {"id": p.id, "page_id": p.page_id, "url": p.url, "title": p.title,
                "status": str(p.status.value if hasattr(p.status, "value") else p.status),
                "created_at": p.created_at, "last_activity_at": p.last_activity_at,
                "is_popup": p.is_popup, "opener_page_id": p.opener_page_id}
    except (BrowserSecurityError, BrowserPolicyDenied, BrowserNotFound) as exc:
        raise _deny(exc)


@router.get("/sessions/{session_id}/pages", response_model=List[PageResponse])
async def list_pages(session_id: str, ctx: AuthorizationContext = Depends(get_current_org_context),
                     db: AsyncSession = Depends(get_db)):
    try:
        pages = await BrowserService(db).list_pages(session_id, ctx.organization_id)
        return [{"id": p.id, "page_id": p.page_id, "url": p.url, "title": p.title,
                 "status": str(p.status.value if hasattr(p.status, "value") else p.status),
                 "created_at": p.created_at, "last_activity_at": p.last_activity_at,
                 "is_popup": p.is_popup, "opener_page_id": p.opener_page_id} for p in pages]
    except (BrowserSecurityError, BrowserNotFound) as exc:
        raise _deny(exc)


@router.delete("/sessions/{session_id}/pages/{page_id}")
async def close_page(session_id: str, page_id: UUID,
                     ctx: AuthorizationContext = Depends(get_current_org_context),
                     db: AsyncSession = Depends(get_db)):
    try:
        await BrowserService(db).close_page(session_id, page_id, ctx.organization_id)
        return {"success": True}
    except (BrowserSecurityError, BrowserNotFound) as exc:
        raise _deny(exc)


# ------------------------------------------------------------------ tasks ---
@router.post("/tasks", response_model=TaskResponse)
async def create_task(request: CreateTaskRequest,
                      ctx: AuthorizationContext = Depends(get_current_org_context),
                      db: AsyncSession = Depends(get_db)):
    try:
        t = await BrowserService(db).create_task(
            organization_id=ctx.organization_id, agent_id=None,
            browser_session_id=request.browser_session_id, objective=request.objective,
            max_steps=request.max_steps, timeout=request.timeout,
            risk_policy=request.risk_policy, metadata=request.metadata)
        return _task_out(t)
    except (BrowserSecurityError, BrowserNotFound) as exc:
        raise _deny(exc)


@router.get("/tasks", response_model=List[TaskResponse])
async def list_tasks(stat: Optional[str] = Query(default=None, alias="status"),
                     browser_session_id: Optional[UUID] = None,
                     limit: int = Query(default=50, le=100), offset: int = Query(default=0, ge=0),
                     ctx: AuthorizationContext = Depends(get_current_org_context),
                     db: AsyncSession = Depends(get_db)):
    tasks = await BrowserService(db).list_tasks(
        organization_id=ctx.organization_id, status=stat,
        browser_session_id=browser_session_id, limit=limit, offset=offset)
    return [_task_out(t) for t in tasks]


@router.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task(task_id: UUID, ctx: AuthorizationContext = Depends(get_current_org_context),
                   db: AsyncSession = Depends(get_db)):
    t = await BrowserService(db).get_task(task_id, ctx.organization_id)
    if not t:
        raise HTTPException(status_code=404, detail="Task not found")
    return _task_out(t)


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(task_id: UUID, ctx: AuthorizationContext = Depends(get_current_org_context),
                      db: AsyncSession = Depends(get_db)):
    try:
        await BrowserService(db).cancel_task(task_id, ctx.organization_id)
        return {"success": True}
    except BrowserNotFound as exc:
        raise _deny(exc)


@router.post("/tasks/{task_id}/pause")
async def pause_task(task_id: UUID, ctx: AuthorizationContext = Depends(get_current_org_context),
                     db: AsyncSession = Depends(get_db)):
    try:
        await BrowserService(db).pause_task(task_id, ctx.organization_id)
        return {"success": True}
    except BrowserNotFound as exc:
        raise _deny(exc)


@router.post("/tasks/{task_id}/resume")
async def resume_task(task_id: UUID, ctx: AuthorizationContext = Depends(get_current_org_context),
                      db: AsyncSession = Depends(get_db)):
    try:
        await BrowserService(db).resume_task(task_id, ctx.organization_id)
        return {"success": True}
    except BrowserNotFound as exc:
        raise _deny(exc)


@router.post("/tasks/{task_id}/human")
async def request_human(task_id: UUID, reason: str = "operator review",
                        ctx: AuthorizationContext = Depends(get_current_org_context),
                        db: AsyncSession = Depends(get_db)):
    """Human-takeover hook: park task in WAITING_FOR_HUMAN (MP19 consumes this)."""
    try:
        t = await BrowserService(db).request_human(task_id, ctx.organization_id, reason)
        return {"success": True, "status": str(t.status.value if hasattr(t.status, "value") else t.status)}
    except BrowserNotFound as exc:
        raise _deny(exc)


@router.post("/tasks/{task_id}/actions")
async def execute_task_action(task_id: UUID, request: TaskActionRequest,
                              ctx: AuthorizationContext = Depends(get_current_org_context),
                              db: AsyncSession = Depends(get_db)):
    try:
        return await BrowserService(db).execute_task_action(
            task_id=task_id, organization_id=ctx.organization_id, action_type=request.action_type,
            page_id=request.page_id, input_data=request.input, approved=request.approved,
            approval_id=request.approval_id)
    except (BrowserSecurityError, BrowserPolicyDenied, BrowserNotFound) as exc:
        raise _deny(exc)


@router.post("/tasks/{task_id}/observations")
async def record_observation(task_id: UUID, request: RecordObservationRequest,
                             ctx: AuthorizationContext = Depends(get_current_org_context),
                             db: AsyncSession = Depends(get_db)):
    try:
        return await BrowserService(db).record_observation(
            task_id=task_id, organization_id=ctx.organization_id, action_id=request.action_id,
            url=request.url, title=request.title, elements=request.elements,
            text=request.text, strategy=request.strategy)
    except (BrowserSecurityError, BrowserNotFound) as exc:
        raise _deny(exc)


# --------------------------------------------------------------- profiles ---
@router.post("/profiles", response_model=ProfileResponse)
async def create_profile(request: ProfileCreateRequest,
                         ctx: AuthorizationContext = Depends(get_current_org_context),
                         db: AsyncSession = Depends(get_db)):
    try:
        p = await BrowserService(db).create_profile(
            organization_id=ctx.organization_id, owner_id=ctx.user_id,
            display_name=request.display_name, browser_type=request.browser_type,
            profile_type=request.profile_type, storage_state=request.storage_state,
            policy=request.policy)
        return {"id": p.id, "organization_id": p.organization_id, "owner_id": p.owner_id,
                "display_name": p.display_name,
                "browser_type": str(p.browser_type.value if hasattr(p.browser_type, "value") else p.browser_type),
                "profile_type": str(p.profile_type.value if hasattr(p.profile_type, "value") else p.profile_type),
                "policy": p.policy or {}, "created_at": p.created_at,
                "updated_at": p.updated_at, "last_used_at": p.last_used_at}
    except (BrowserSecurityError, BrowserNotFound) as exc:
        raise _deny(exc)


@router.get("/profiles", response_model=List[ProfileResponse])
async def list_profiles(ctx: AuthorizationContext = Depends(get_current_org_context),
                        db: AsyncSession = Depends(get_db)):
    profiles = await BrowserService(db).list_profiles(ctx.organization_id)
    return [{"id": p.id, "organization_id": p.organization_id, "owner_id": p.owner_id,
             "display_name": p.display_name,
             "browser_type": str(p.browser_type.value if hasattr(p.browser_type, "value") else p.browser_type),
             "profile_type": str(p.profile_type.value if hasattr(p.profile_type, "value") else p.profile_type),
             "policy": p.policy or {}, "created_at": p.created_at,
             "updated_at": p.updated_at, "last_used_at": p.last_used_at} for p in profiles]


@router.get("/profiles/{profile_id}", response_model=ProfileResponse)
async def get_profile(profile_id: UUID, ctx: AuthorizationContext = Depends(get_current_org_context),
                      db: AsyncSession = Depends(get_db)):
    p = await BrowserService(db).get_profile(profile_id, ctx.organization_id)
    if not p:
        raise HTTPException(status_code=404, detail="Profile not found")
    return {"id": p.id, "organization_id": p.organization_id, "owner_id": p.owner_id,
            "display_name": p.display_name,
            "browser_type": str(p.browser_type.value if hasattr(p.browser_type, "value") else p.browser_type),
            "profile_type": str(p.profile_type.value if hasattr(p.profile_type, "value") else p.profile_type),
            "policy": p.policy or {}, "created_at": p.created_at,
            "updated_at": p.updated_at, "last_used_at": p.last_used_at}


@router.patch("/profiles/{profile_id}", response_model=ProfileResponse)
async def update_profile(profile_id: UUID, request: ProfileCreateRequest,
                         ctx: AuthorizationContext = Depends(get_current_org_context),
                         db: AsyncSession = Depends(get_db)):
    p = await BrowserService(db).update_profile(
        profile_id, ctx.organization_id, request.model_dump(exclude_unset=True))
    if not p:
        raise HTTPException(status_code=404, detail="Profile not found")
    return {"id": p.id, "organization_id": p.organization_id, "owner_id": p.owner_id,
            "display_name": p.display_name,
            "browser_type": str(p.browser_type.value if hasattr(p.browser_type, "value") else p.browser_type),
            "profile_type": str(p.profile_type.value if hasattr(p.profile_type, "value") else p.profile_type),
            "policy": p.policy or {}, "created_at": p.created_at,
            "updated_at": p.updated_at, "last_used_at": p.last_used_at}


@router.delete("/profiles/{profile_id}")
async def delete_profile(profile_id: UUID, ctx: AuthorizationContext = Depends(get_current_org_context),
                         db: AsyncSession = Depends(get_db)):
    await BrowserService(db).delete_profile(profile_id, ctx.organization_id)
    return {"success": True}


# ---------------------------------------------------------------- policies ---
@router.post("/policies", response_model=DomainPolicyResponse)
async def create_domain_policy(request: DomainPolicyRequest,
                               ctx: AuthorizationContext = Depends(get_current_org_context),
                               db: AsyncSession = Depends(get_db)):
    pol = await BrowserService(db).create_domain_policy(
        organization_id=ctx.organization_id, domain=request.domain, action=request.action,
        priority=request.priority, reason=request.reason)
    return {"id": pol.id, "organization_id": pol.organization_id, "domain": pol.domain,
            "action": str(pol.action.value if hasattr(pol.action, "value") else pol.action),
            "priority": pol.priority, "reason": pol.reason,
            "created_at": pol.created_at, "updated_at": pol.updated_at}


@router.get("/policies", response_model=List[DomainPolicyResponse])
async def list_domain_policies(ctx: AuthorizationContext = Depends(get_current_org_context),
                               db: AsyncSession = Depends(get_db)):
    policies = await BrowserService(db).list_domain_policies(ctx.organization_id)
    return [{"id": p.id, "organization_id": p.organization_id, "domain": p.domain,
             "action": str(p.action.value if hasattr(p.action, "value") else p.action),
             "priority": p.priority, "reason": p.reason,
             "created_at": p.created_at, "updated_at": p.updated_at} for p in policies]


@router.put("/policies")
async def update_domain_policies(policies: List[DomainPolicyRequest],
                                 ctx: AuthorizationContext = Depends(get_current_org_context),
                                 db: AsyncSession = Depends(get_db)):
    await BrowserService(db).update_domain_policies(
        ctx.organization_id, [p.model_dump() for p in policies])
    return {"success": True}


# ------------------------------------------------------------------ events ---
@router.get("/sessions/{session_id}/events")
async def get_session_events(session_id: str, limit: int = Query(default=100, le=500),
                             ctx: AuthorizationContext = Depends(get_current_org_context),
                             db: AsyncSession = Depends(get_db)):
    try:
        events = await BrowserService(db).get_session_events(session_id, ctx.organization_id, limit)
        return [{"id": str(e.id), "event_id": e.event_id, "type": e.type,
                 "payload": e.payload, "timestamp": e.timestamp} for e in events]
    except (BrowserSecurityError, BrowserNotFound) as exc:
        raise _deny(exc)


class VerifyBrowserRequest(BaseModel):
    observed: Dict[str, Any] = Field(default_factory=dict)
    expectations: Dict[str, Any] = Field(default_factory=dict)


@router.post("/tasks/{task_id}/verify")
async def verify_browser_task(task_id: UUID, request: VerifyBrowserRequest,
                              ctx: AuthorizationContext = Depends(get_current_org_context),
                              db: AsyncSession = Depends(get_db)):
    """Verify a browser action achieved its expected state.

    'Button clicked' is not 'operation succeeded': URL, DOM, success
    indicators (and absence of challenges) are checked deterministically.
    """
    from openagent.browser.service import BrowserService as _BrowserService
    from openagent.evaluator.integrations import verify_browser_action
    try:
        task = await _BrowserService(db).get_task(task_id, ctx.organization_id)
        if task is None:
            raise BrowserNotFound("Browser task not found")
        return await verify_browser_action(
            db, organization_id=ctx.organization_id,
            observed=request.observed, expectations=request.expectations or None)
    except (BrowserSecurityError, BrowserNotFound) as exc:
        raise _deny(exc)


@router.get("/health")
async def browser_health():
    return {"status": "healthy", "service": "browser"}
