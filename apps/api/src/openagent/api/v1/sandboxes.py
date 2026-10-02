"""Sandbox + secure execution API.

Tenant-scoped via the standard org context. Raw secrets are never accepted
or returned: credentials travel as ``credential_ref`` handles only, and
container paths are never exposed (storage refs instead).
"""

from __future__ import annotations

import shlex
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from openagent.api.dependencies import get_current_org_context
from openagent.db.session import get_db
from openagent.sandbox.config import production_security_check
from openagent.sandbox.profiles import profile_to_dict
from openagent.sandbox.service import (
    SandboxManager,
    SandboxNotFound,
    SandboxPolicyDenied,
    SandboxSecurityError,
)
from openagent.services.authorization import AuthorizationContext

router = APIRouter(prefix="/sandboxes", tags=["sandboxes"])
profiles_router = APIRouter(prefix="/sandbox-profiles", tags=["sandbox-profiles"])
exec_router = APIRouter(prefix="/sandbox-executions", tags=["sandbox-executions"])


def _deny(exc: Exception) -> HTTPException:
    if isinstance(exc, SandboxPolicyDenied):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, SandboxSecurityError):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if isinstance(exc, SandboxNotFound):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                         detail="Sandbox operation failed")


def _mgr(db: AsyncSession) -> SandboxManager:
    return SandboxManager(db)


def _sb_out(sb) -> dict:
    return {"id": sb.id, "sandbox_id": sb.sandbox_id,
            "organization_id": sb.organization_id,
            "owner_id": sb.owner_id, "task_id": sb.task_id,
            "workspace_id": sb.workspace_id,
            "provider": str(sb.provider.value if hasattr(sb.provider, "value") else sb.provider),
            "profile": sb.profile,
            "status": str(sb.status.value if hasattr(sb.status, "value") else sb.status),
            "image": sb.image, "pinned": bool(sb.image_digest),
            "started_at": sb.started_at, "expires_at": sb.expires_at,
            "destroyed_at": sb.destroyed_at,
            "resource_config": sb.resource_config}


def _ex_out(ex) -> dict:
    st = str(ex.status.value if hasattr(ex.status, "value") else ex.status)
    if st == "WAITING":
        st = "WAITING_FOR_APPROVAL"
    return {"id": ex.id, "execution_id": ex.execution_id,
            "organization_id": ex.organization_id, "sandbox_id": ex.sandbox_id,
            "task_id": ex.task_id, "command": ex.command, "workdir": ex.workdir,
            "profile": ex.profile, "status": st, "exit_code": ex.exit_code,
            "duration_ms": ex.duration_ms, "timed_out": ex.timed_out,
            "oom_killed": ex.oom_killed, "peak_memory_mb": ex.peak_memory_mb,
            "risk_level": ex.risk_level, "risk_reasons": ex.risk_reasons,
            "policy_decision": ex.policy_decision,
            "stdout_tail": ex.stdout_tail, "stdout_ref": ex.stdout_ref,
            "stderr_ref": ex.stderr_ref, "artifacts": ex.artifacts,
            "started_at": ex.started_at, "completed_at": ex.completed_at}


# ---------------------------------------------------------------- schemas ---
class CreateSandboxRequest(BaseModel):
    profile: str = Field(default="TEST", max_length=50)
    task_id: Optional[UUID] = None
    workspace_host_path: Optional[str] = Field(default=None, max_length=1024)
    workspace_mode: str = Field(default="WORKSPACE_RW", pattern="^(WORKSPACE_RW|WORKSPACE_RO)$")
    image: Optional[str] = Field(default=None, max_length=500)
    image_digest: Optional[str] = Field(default=None, max_length=255)
    ttl_seconds: int = Field(default=3600, ge=60, le=28800)
    labels: Optional[Dict[str, str]] = None


class ExecuteRequest(BaseModel):
    command: Any = Field(description="argv list (preferred) or plain command string")
    workdir: str = Field(default="/workspace", max_length=1024)
    env: Optional[Dict[str, str]] = None
    credential_refs: Optional[Dict[str, str]] = None
    task_id: Optional[UUID] = None
    owner: Optional[str] = Field(default=None, max_length=255)
    timeout_seconds: Optional[int] = Field(default=None, ge=5, le=28800)
    approved: bool = False
    approval_id: Optional[UUID] = Field(default=None,
                                        description="Persisted approval authorizing this exact command")
    artifacts: Optional[List[Dict[str, str]]] = None
    target_environment: str = Field(default="sandbox", max_length=50)


class LeaseRequest(BaseModel):
    owner: str = Field(min_length=1, max_length=255)
    ttl_seconds: int = Field(default=600, ge=30, le=7200)
    task_id: Optional[UUID] = None


class UpsertProfileRequest(BaseModel):
    config: Dict[str, Any]


# --------------------------------------------------------------- sandboxes ---
@router.post("", response_model=Dict[str, Any])
async def create_sandbox(
    request: CreateSandboxRequest,
    ctx: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    try:
        sb = await _mgr(db).create_sandbox(
            organization_id=ctx.organization_id, profile=request.profile,
            owner_id=ctx.user_id, task_id=request.task_id,
            workspace_host_path=request.workspace_host_path,
            workspace_mode=request.workspace_mode, image=request.image,
            image_digest=request.image_digest, ttl_seconds=request.ttl_seconds,
            labels=request.labels)
        return _sb_out(sb)
    except (SandboxSecurityError, SandboxPolicyDenied, SandboxNotFound) as exc:
        raise _deny(exc)


@router.get("", response_model=List[Dict[str, Any]])
async def list_sandboxes(
    stat: Optional[str] = Query(default=None, alias="status"),
    ctx: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    sbs = await _mgr(db).list_sandboxes(ctx.organization_id, status=stat)
    return [_sb_out(sb) for sb in sbs]


@router.get("/security/check", response_model=Dict[str, Any])
async def security_check():
    try:
        return await production_security_check()
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail=str(exc))


@router.get("/{sandbox_id}", response_model=Dict[str, Any])
async def get_sandbox(
    sandbox_id: UUID,
    ctx: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    try:
        return _sb_out(await _mgr(db).get_sandbox(sandbox_id, ctx.organization_id))
    except (SandboxSecurityError, SandboxNotFound) as exc:
        raise _deny(exc)


@router.post("/{sandbox_id}/start", response_model=Dict[str, Any])
async def start_sandbox(
    sandbox_id: UUID,
    ctx: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    try:
        sb = await _mgr(db).start_sandbox(sandbox_id, ctx.organization_id, ctx.user_id)
        return _sb_out(sb)
    except (SandboxSecurityError, SandboxPolicyDenied, SandboxNotFound) as exc:
        raise _deny(exc)


@router.post("/{sandbox_id}/stop", response_model=Dict[str, Any])
async def stop_sandbox(
    sandbox_id: UUID,
    ctx: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    try:
        sb = await _mgr(db).stop_sandbox(sandbox_id, ctx.organization_id, ctx.user_id)
        return _sb_out(sb)
    except (SandboxSecurityError, SandboxNotFound) as exc:
        raise _deny(exc)


@router.delete("/{sandbox_id}")
async def destroy_sandbox(
    sandbox_id: UUID,
    ctx: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    try:
        await _mgr(db).destroy_sandbox(sandbox_id, ctx.organization_id, ctx.user_id)
        return {"success": True}
    except (SandboxSecurityError, SandboxNotFound) as exc:
        raise _deny(exc)


@router.post("/{sandbox_id}/execute", response_model=Dict[str, Any])
async def execute_command(
    sandbox_id: UUID,
    request: ExecuteRequest,
    ctx: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    try:
        command = request.command
        if isinstance(command, list):
            # Structured argv over the wire; re-encoded without a shell.
            command = " ".join(shlex.quote(str(a)) for a in command)
        return await _mgr(db).execute(
            sandbox_id=sandbox_id, organization_id=ctx.organization_id,
            command=str(command), workdir=request.workdir, env=request.env,
            credential_refs=request.credential_refs,
            task_id=request.task_id, actor=ctx.user_id, owner=request.owner,
            timeout_seconds=request.timeout_seconds, approved=request.approved,
            approval_id=request.approval_id,
            artifacts=request.artifacts,
            target_environment=request.target_environment)
    except (SandboxSecurityError, SandboxPolicyDenied, SandboxNotFound) as exc:
        raise _deny(exc)


@router.get("/{sandbox_id}/executions", response_model=List[Dict[str, Any]])
async def list_executions(
    sandbox_id: UUID,
    limit: int = Query(default=50, le=200),
    ctx: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    try:
        exs = await _mgr(db).list_executions(sandbox_id, ctx.organization_id, limit)
        return [_ex_out(ex) for ex in exs]
    except (SandboxSecurityError, SandboxNotFound) as exc:
        raise _deny(exc)


@router.get("/{sandbox_id}/executions/{execution_id}", response_model=Dict[str, Any])
async def get_execution(
    sandbox_id: UUID,
    execution_id: UUID,
    ctx: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    try:
        mgr = _mgr(db)
        await mgr.get_sandbox(sandbox_id, ctx.organization_id)
        return _ex_out(await mgr.get_execution(execution_id, ctx.organization_id))
    except (SandboxSecurityError, SandboxNotFound) as exc:
        raise _deny(exc)


@router.post("/{sandbox_id}/executions/{execution_id}/cancel",
             response_model=Dict[str, Any])
async def cancel_execution(
    sandbox_id: UUID,
    execution_id: UUID,
    ctx: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    try:
        mgr = _mgr(db)
        await mgr.get_sandbox(sandbox_id, ctx.organization_id)
        return await mgr.cancel_execution(execution_id, ctx.organization_id, ctx.user_id)
    except (SandboxSecurityError, SandboxNotFound) as exc:
        raise _deny(exc)


@router.get("/{sandbox_id}/events", response_model=List[Dict[str, Any]])
async def sandbox_events(
    sandbox_id: UUID,
    limit: int = Query(default=100, le=500),
    ctx: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    try:
        events = await _mgr(db).sandbox_events(sandbox_id, ctx.organization_id, limit)
        return [{"id": str(e.id), "event_id": e.event_id, "type": e.type,
                 "payload": e.payload, "created_at": e.created_at} for e in events]
    except (SandboxSecurityError, SandboxNotFound) as exc:
        raise _deny(exc)


@router.get("/{sandbox_id}/artifacts", response_model=List[Dict[str, Any]])
async def sandbox_artifacts(
    sandbox_id: UUID,
    ctx: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    try:
        arts = await _mgr(db).sandbox_artifacts(sandbox_id, ctx.organization_id)
        return [{"id": str(a.id), "name": a.name, "kind": a.kind,
                 "ref": a.storage_ref, "size_bytes": a.size_bytes,
                 "mime_type": a.mime_type, "expires_at": a.expires_at} for a in arts]
    except (SandboxSecurityError, SandboxNotFound) as exc:
        raise _deny(exc)


@router.post("/{sandbox_id}/leases", response_model=Dict[str, Any])
async def acquire_lease(
    sandbox_id: UUID,
    request: LeaseRequest,
    ctx: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    try:
        lease = await _mgr(db).acquire_lease(
            sandbox_id, ctx.organization_id, request.owner,
            ttl_seconds=request.ttl_seconds, task_id=request.task_id)
        return {"id": str(lease.id), "owner": lease.owner,
                "acquired_at": lease.acquired_at, "expires_at": lease.expires_at}
    except (SandboxSecurityError, SandboxPolicyDenied, SandboxNotFound) as exc:
        raise _deny(exc)


@router.post("/{sandbox_id}/leases/{lease_id}/heartbeat", response_model=Dict[str, Any])
async def heartbeat_lease(
    sandbox_id: UUID,
    lease_id: UUID,
    request: LeaseRequest,
    ctx: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    try:
        mgr = _mgr(db)
        await mgr.get_sandbox(sandbox_id, ctx.organization_id)
        lease = await mgr.heartbeat_lease(lease_id, ctx.organization_id, request.owner)
        return {"id": str(lease.id), "expires_at": lease.expires_at}
    except (SandboxSecurityError, SandboxNotFound) as exc:
        raise _deny(exc)


@router.post("/{sandbox_id}/leases/{lease_id}/release")
async def release_lease(
    sandbox_id: UUID,
    lease_id: UUID,
    request: LeaseRequest,
    ctx: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    try:
        mgr = _mgr(db)
        await mgr.get_sandbox(sandbox_id, ctx.organization_id)
        await mgr.release_lease(lease_id, ctx.organization_id, request.owner)
        return {"success": True}
    except (SandboxSecurityError, SandboxNotFound) as exc:
        raise _deny(exc)


# ---------------------------------------------------------------- profiles ---
@profiles_router.get("", response_model=List[Dict[str, Any]])
async def list_profiles(
    ctx: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    return await _mgr(db).list_profiles(ctx.organization_id)


@profiles_router.post("", response_model=Dict[str, Any])
async def upsert_profile(
    request: UpsertProfileRequest,
    ctx: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await _mgr(db).upsert_profile(
            ctx.organization_id, request.config, ctx.user_id)
    except (SandboxSecurityError, SandboxPolicyDenied, SandboxNotFound) as exc:
        raise _deny(exc)


@profiles_router.patch("/{name}", response_model=Dict[str, Any])
async def patch_profile(
    name: str,
    request: UpsertProfileRequest,
    ctx: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Partial update: merges the patch into the stored customization.

    ``{name}`` accepts a profile name (``TEST``) or a profile-row UUID.
    """
    try:
        mgr = _mgr(db)
        resolved_name = await _profile_key(db, ctx.organization_id, name)
        try:
            current = profile_to_dict(await mgr.resolve_profile(resolved_name,
                                                                ctx.organization_id))
        except ValueError as exc:
            raise _deny(SandboxSecurityError(str(exc)))
        merged = {**current, **request.config}
        merged["name"] = resolved_name.upper()
        return await mgr.upsert_profile(ctx.organization_id, merged, ctx.user_id)
    except (SandboxSecurityError, SandboxPolicyDenied, SandboxNotFound) as exc:
        raise _deny(exc)


@profiles_router.delete("/{name}")
async def delete_profile(
    name: str,
    ctx: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    try:
        mgr = _mgr(db)
        resolved_name = await _profile_key(db, ctx.organization_id, name)
        await mgr.delete_profile(ctx.organization_id, resolved_name, ctx.user_id)
        return {"success": True}
    except (SandboxSecurityError, SandboxNotFound) as exc:
        raise _deny(exc)


async def _profile_key(db: AsyncSession, organization_id: UUID, name: str) -> str:
    """Accept a profile name or a profile-row UUID; returns the profile name."""
    try:
        row_id = UUID(str(name))
    except ValueError:
        return name
    from sqlalchemy import select as _select
    from openagent.db.models.sandbox import SandboxProfileRow as _Row
    row = await db.scalar(_select(_Row).where(
        _Row.id == row_id, _Row.organization_id == organization_id))
    if row is None:
        raise SandboxNotFound("Profile customization not found")
    return str(row.profile_id)


# --------------------------------------------------------- direct lookup -----
@exec_router.get("/{execution_id}", response_model=Dict[str, Any])
async def get_execution_direct(
    execution_id: UUID,
    ctx: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    try:
        return _ex_out(await _mgr(db).get_execution(execution_id, ctx.organization_id))
    except (SandboxSecurityError, SandboxNotFound) as exc:
        raise _deny(exc)


@router.get("/health")
async def sandbox_health():
    return {"status": "healthy", "service": "sandbox"}
