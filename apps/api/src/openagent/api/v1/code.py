"""Code workspace + coding task API.

Workspaces are server-side checkouts; host paths are never returned.
Every mutating operation flows through CodeService policy gates.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from openagent.api.dependencies import get_current_org_context
from openagent.code.service import CodeNotFound, CodePolicyDenied, CodeSecurityError, CodeService
from openagent.db.session import get_db
from openagent.services.authorization import AuthorizationContext

router = APIRouter(prefix="/code", tags=["code"])


def _deny(exc: Exception) -> HTTPException:
    if isinstance(exc, CodePolicyDenied):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, CodeSecurityError):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if isinstance(exc, CodeNotFound):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                         detail="Code operation failed")


# ------------------------------------------------------------------ schemas ---
class CreateWorkspaceRequest(BaseModel):
    repository_id: UUID
    task_id: Optional[UUID] = None
    branch: Optional[str] = Field(default=None, max_length=255)


class WorkspaceResponse(BaseModel):
    id: UUID
    workspace_id: str
    organization_id: UUID
    repository_id: UUID
    branch: str
    base_revision: Optional[str] = None
    current_revision: Optional[str] = None
    status: str
    dirty: Optional[bool] = None


def _ws_out(w, dirty: Optional[bool] = None) -> dict:
    return {"id": w.id, "workspace_id": w.workspace_id,
            "organization_id": w.organization_id, "repository_id": w.repository_id,
            "branch": w.branch, "base_revision": w.base_revision,
            "current_revision": w.current_revision,
            "status": str(w.status.value if hasattr(w.status, "value") else w.status),
            "dirty": dirty}


class CreateTaskRequest(BaseModel):
    repository_id: UUID
    objective: str = Field(min_length=1, max_length=4000)
    branch: Optional[str] = Field(default=None, max_length=255)
    max_steps: int = Field(default=50, ge=1, le=200)
    max_duration_seconds: int = Field(default=3600, ge=60, le=28800)
    risk_level: str = Field(default="MEDIUM", pattern="^(LOW|MEDIUM|HIGH|CRITICAL)$")
    budgets: Optional[Dict[str, Any]] = None


class TaskResponse(BaseModel):
    id: UUID
    task_id: str
    organization_id: UUID
    repository_id: UUID
    workspace_id: Optional[UUID] = None
    objective: str
    branch: Optional[str] = None
    status: str
    risk_level: str
    current_step: int
    max_steps: int


def _task_out(t) -> dict:
    return {"id": t.id, "task_id": t.task_id, "organization_id": t.organization_id,
            "repository_id": t.repository_id, "workspace_id": t.workspace_id,
            "objective": t.objective, "branch": t.branch,
            "status": str(t.status.value if hasattr(t.status, "value") else t.status),
            "risk_level": str(t.risk_level.value if hasattr(t.risk_level, "value")
                              else t.risk_level),
            "current_step": t.current_step, "max_steps": t.max_steps}


class PatchRequest(BaseModel):
    diff: str = Field(min_length=1, max_length=500_000)
    approved: bool = False
    approval_id: Optional[UUID] = Field(default=None,
                                        description="Persisted approval for this exact diff")


class CommitRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


class PushRequest(BaseModel):
    approved: bool = False
    approval_id: Optional[UUID] = Field(default=None,
                                        description="Persisted approval for this exact push")
    force: bool = False


class PRRequest(BaseModel):
    task_id: UUID
    title: str = Field(min_length=1, max_length=500)
    summary: str = Field(default="", max_length=5000)
    reviewers: Optional[List[str]] = None
    open: bool = False  # open on the forge; never merges


class SearchRequest(BaseModel):
    workspace_id: UUID
    query: str = Field(min_length=1, max_length=500)
    regex: bool = False
    mode: str = Field(default="text", pattern="^(text|regex|symbol|references|semantic)$")
    symbol: Optional[str] = None
    top_k: int = Field(default=20, ge=1, le=100)


class ReviewRequest(BaseModel):
    task_id: Optional[UUID] = None
    filename: Optional[str] = None
    content: Optional[str] = None


class ExecuteRequest(BaseModel):
    workspace_id: Optional[UUID] = None
    task_id: Optional[UUID] = None
    profile: str = Field(default="TEST",
                         pattern="^(TEST|LINT|TYPECHECK|BUILD|PACKAGE|MIGRATION|CUSTOM)$")
    command: str = Field(min_length=1, max_length=2000)


# --------------------------------------------------------------- workspaces ---
@router.post("/workspaces", response_model=WorkspaceResponse)
async def create_workspace(
    request: CreateWorkspaceRequest,
    ctx: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    try:
        ws = await CodeService(db).create_workspace(
            organization_id=ctx.organization_id, repository_id=request.repository_id,
            task_id=request.task_id, branch=request.branch, actor=ctx.user_id)
        return _ws_out(ws)
    except (CodeSecurityError, CodePolicyDenied, CodeNotFound) as exc:
        raise _deny(exc)


@router.get("/workspaces", response_model=List[WorkspaceResponse])
async def list_workspaces(
    stat: Optional[str] = Query(default=None, alias="status"),
    ctx: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    wss = await CodeService(db).list_workspaces(ctx.organization_id, status=stat)
    return [_ws_out(w) for w in wss]


@router.get("/workspaces/{ws_id}", response_model=WorkspaceResponse)
async def get_workspace(
    ws_id: UUID,
    ctx: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    try:
        ws = await CodeService(db).get_workspace(ws_id, ctx.organization_id)
        st = await CodeService(db).workspace_status(ws_id, ctx.organization_id)
        return _ws_out(ws, dirty=st["dirty"])
    except (CodeSecurityError, CodeNotFound) as exc:
        raise _deny(exc)


@router.get("/workspaces/{ws_id}/status")
async def workspace_status(
    ws_id: UUID,
    ctx: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    try:
        st = await CodeService(db).workspace_status(ws_id, ctx.organization_id)
        st.pop("changes", None)
        return {**st, "change_count": len(st.get("changes", []))}
    except (CodeSecurityError, CodeNotFound) as exc:
        raise _deny(exc)


@router.delete("/workspaces/{ws_id}")
async def delete_workspace(
    ws_id: UUID,
    force: bool = False,
    ctx: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    try:
        await CodeService(db).delete_workspace(ws_id, ctx.organization_id,
                                               force=force, actor=ctx.user_id)
        return {"success": True}
    except (CodeSecurityError, CodePolicyDenied, CodeNotFound) as exc:
        raise _deny(exc)


@router.post("/workspaces/{ws_id}/branches")
async def create_branch(
    ws_id: UUID,
    body: Dict[str, str],
    ctx: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await CodeService(db).create_branch(ws_id, ctx.organization_id,
                                                   body.get("name", ""))
    except (CodeSecurityError, CodePolicyDenied, CodeNotFound) as exc:
        raise _deny(exc)


@router.get("/workspaces/{ws_id}/files")
async def list_files(
    ws_id: UUID,
    prefix: str = "",
    ctx: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    try:
        return {"files": await CodeService(db).list_files(ws_id, ctx.organization_id,
                                                          prefix=prefix)}
    except (CodeSecurityError, CodeNotFound) as exc:
        raise _deny(exc)


@router.get("/workspaces/{ws_id}/files/read")
async def read_file(
    ws_id: UUID,
    path: str,
    start: Optional[int] = None,
    end: Optional[int] = None,
    ctx: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    try:
        svc = CodeService(db)
        if start and end:
            return await svc.read_range(ws_id, ctx.organization_id, path, start, end)
        return await svc.read_file(ws_id, ctx.organization_id, path)
    except (CodeSecurityError, CodePolicyDenied, CodeNotFound) as exc:
        raise _deny(exc)


# -------------------------------------------------------------------- tasks ---
@router.post("/tasks", response_model=TaskResponse)
async def create_task(
    request: CreateTaskRequest,
    ctx: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    try:
        t = await CodeService(db).create_task(
            organization_id=ctx.organization_id, repository_id=request.repository_id,
            objective=request.objective, user_id=ctx.user_id,
            branch=request.branch, max_steps=request.max_steps,
            max_duration_seconds=request.max_duration_seconds,
            risk_level=request.risk_level, budgets=request.budgets)
        return _task_out(t)
    except (CodeSecurityError, CodePolicyDenied, CodeNotFound) as exc:
        raise _deny(exc)


@router.get("/tasks", response_model=List[TaskResponse])
async def list_tasks(
    stat: Optional[str] = Query(default=None, alias="status"),
    repository_id: Optional[UUID] = None,
    limit: int = Query(default=50, le=100),
    ctx: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    tasks = await CodeService(db).list_tasks(ctx.organization_id, status=stat,
                                             repository_id=repository_id,
                                             limit=limit)
    return [_task_out(t) for t in tasks]


@router.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: UUID,
    ctx: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    try:
        return _task_out(await CodeService(db).get_task(task_id, ctx.organization_id))
    except CodeNotFound as exc:
        raise _deny(exc)


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(task_id: UUID,
                      ctx: AuthorizationContext = Depends(get_current_org_context),
                      db: AsyncSession = Depends(get_db)):
    try:
        await CodeService(db).cancel_task(task_id, ctx.organization_id)
        return {"success": True}
    except (CodeSecurityError, CodePolicyDenied, CodeNotFound) as exc:
        raise _deny(exc)


@router.post("/tasks/{task_id}/pause")
async def pause_task(task_id: UUID,
                     ctx: AuthorizationContext = Depends(get_current_org_context),
                     db: AsyncSession = Depends(get_db)):
    try:
        await CodeService(db).pause_task(task_id, ctx.organization_id)
        return {"success": True}
    except (CodeSecurityError, CodeNotFound) as exc:
        raise _deny(exc)


@router.post("/tasks/{task_id}/resume")
async def resume_task(task_id: UUID,
                      ctx: AuthorizationContext = Depends(get_current_org_context),
                      db: AsyncSession = Depends(get_db)):
    try:
        await CodeService(db).resume_task(task_id, ctx.organization_id)
        return {"success": True}
    except (CodeSecurityError, CodeNotFound) as exc:
        raise _deny(exc)


@router.get("/tasks/{task_id}/diff")
async def task_diff(task_id: UUID,
                    ctx: AuthorizationContext = Depends(get_current_org_context),
                    db: AsyncSession = Depends(get_db)):
    try:
        return await CodeService(db).task_diff(task_id, ctx.organization_id)
    except (CodeSecurityError, CodeNotFound) as exc:
        raise _deny(exc)


@router.get("/tasks/{task_id}/events")
async def task_events(task_id: UUID, limit: int = Query(default=100, le=500),
                      ctx: AuthorizationContext = Depends(get_current_org_context),
                      db: AsyncSession = Depends(get_db)):
    try:
        events = await CodeService(db).task_events(task_id, ctx.organization_id, limit)
        return [{"id": str(e.id), "event_id": e.event_id, "type": e.type,
                 "payload": e.payload, "timestamp": e.timestamp} for e in events]
    except (CodeSecurityError, CodeNotFound) as exc:
        raise _deny(exc)


@router.get("/tasks/{task_id}/artifacts")
async def task_artifacts(task_id: UUID,
                         ctx: AuthorizationContext = Depends(get_current_org_context),
                         db: AsyncSession = Depends(get_db)):
    try:
        return await CodeService(db).task_artifacts(task_id, ctx.organization_id)
    except (CodeSecurityError, CodeNotFound) as exc:
        raise _deny(exc)


@router.post("/tasks/{task_id}/patch")
async def apply_task_patch(task_id: UUID, request: PatchRequest,
                           ctx: AuthorizationContext = Depends(get_current_org_context),
                           db: AsyncSession = Depends(get_db)):
    try:
        return await CodeService(db).apply_patch(
            task_id, ctx.organization_id, diff_text=request.diff,
            approved=request.approved, approval_id=request.approval_id)
    except (CodeSecurityError, CodePolicyDenied, CodeNotFound) as exc:
        raise _deny(exc)


@router.post("/tasks/{task_id}/commit")
async def commit_task(task_id: UUID, request: CommitRequest,
                      ctx: AuthorizationContext = Depends(get_current_org_context),
                      db: AsyncSession = Depends(get_db)):
    try:
        return await CodeService(db).commit(task_id, ctx.organization_id,
                                            request.message)
    except (CodeSecurityError, CodePolicyDenied, CodeNotFound) as exc:
        raise _deny(exc)


@router.post("/tasks/{task_id}/push")
async def push_task(task_id: UUID, request: PushRequest,
                    ctx: AuthorizationContext = Depends(get_current_org_context),
                    db: AsyncSession = Depends(get_db)):
    try:
        return await CodeService(db).push(task_id, ctx.organization_id,
                                          approved=request.approved,
                                          approval_id=request.approval_id,
                                          force=request.force)
    except (CodeSecurityError, CodePolicyDenied, CodeNotFound) as exc:
        raise _deny(exc)


@router.get("/tasks/{task_id}/plan")
async def task_plan(task_id: UUID,
                    ctx: AuthorizationContext = Depends(get_current_org_context),
                    db: AsyncSession = Depends(get_db)):
    try:
        svc = CodeService(db)
        task = await svc.get_task(task_id, ctx.organization_id)
        return svc.build_plan(task.objective,
                              risk_level=str(task.risk_level),
                              max_steps=task.max_steps)
    except CodeNotFound as exc:
        raise _deny(exc)


@router.post("/tasks/{task_id}/tests/plan")
async def plan_task_tests(task_id: UUID,
                          ctx: AuthorizationContext = Depends(get_current_org_context),
                          db: AsyncSession = Depends(get_db)):
    try:
        return await CodeService(db).plan_tests(task_id, ctx.organization_id)
    except (CodeSecurityError, CodePolicyDenied, CodeNotFound) as exc:
        raise _deny(exc)


# ------------------------------------------------------------- search/review ---
@router.post("/search")
async def search_code(request: SearchRequest,
                      ctx: AuthorizationContext = Depends(get_current_org_context),
                      db: AsyncSession = Depends(get_db)):
    try:
        svc = CodeService(db)
        if request.mode == "regex":
            return await svc.search_regex(request.workspace_id, ctx.organization_id,
                                          request.query)
        if request.mode == "symbol":
            return await svc.find_symbol(request.workspace_id, ctx.organization_id,
                                         request.symbol or request.query)
        if request.mode == "references":
            return await svc.find_references(request.workspace_id, ctx.organization_id,
                                             request.symbol or request.query)
        if request.mode == "semantic":
            return await svc.semantic_search(request.workspace_id, ctx.organization_id,
                                             request.query, top_k=request.top_k)
        return await svc.search_text(request.workspace_id, ctx.organization_id,
                                     request.query)
    except (CodeSecurityError, CodePolicyDenied, CodeNotFound) as exc:
        raise _deny(exc)


@router.post("/review")
async def review_code(request: ReviewRequest,
                      ctx: AuthorizationContext = Depends(get_current_org_context),
                      db: AsyncSession = Depends(get_db)):
    try:
        svc = CodeService(db)
        if request.task_id:
            return await svc.review_task(request.task_id, ctx.organization_id)
        if request.filename and request.content is not None:
            return await svc.review_text(ctx.organization_id, request.filename,
                                         request.content)
        raise HTTPException(status_code=400, detail="task_id or filename+content required")
    except (CodeSecurityError, CodePolicyDenied, CodeNotFound) as exc:
        raise _deny(exc)


@router.post("/execute")
async def execute_command(request: ExecuteRequest,
                          ctx: AuthorizationContext = Depends(get_current_org_context),
                          db: AsyncSession = Depends(get_db)):
    try:
        svc = CodeService(db)
        if request.profile == "TEST":
            return await svc.run_tests(request.task_id, ctx.organization_id,
                                       request.workspace_id, request.command)
        return await svc.run_command(request.task_id, ctx.organization_id,
                                     request.workspace_id, request.profile,
                                     request.command)
    except (CodeSecurityError, CodePolicyDenied, CodeNotFound) as exc:
        raise _deny(exc)


@router.post("/pr")
async def prepare_pr(request: PRRequest,
                     ctx: AuthorizationContext = Depends(get_current_org_context),
                     db: AsyncSession = Depends(get_db)):
    try:
        return await CodeService(db).prepare_pr(
            request.task_id, ctx.organization_id, request.title,
            summary=request.summary, open_remote=request.open)
    except (CodeSecurityError, CodePolicyDenied, CodeNotFound) as exc:
        raise _deny(exc)


class VerifyTaskRequest(BaseModel):
    include_secret_scan: bool = True


@router.post("/tasks/{task_id}/verify")
async def verify_task(task_id: UUID, request: VerifyTaskRequest,
                      ctx: AuthorizationContext = Depends(get_current_org_context),
                      db: AsyncSession = Depends(get_db)):
    """Verify a coding task: persisted test results + secret scan + diff.

    A code agent cannot declare success from its own response; this endpoint
    evaluates observable evidence only.
    """
    from sqlalchemy import select
    from openagent.code.security import scan_text_for_secrets
    from openagent.db.models.code import CodeTestResult
    from openagent.evaluator.integrations import verify_code_change
    try:
        svc = CodeService(db)
        task = await svc.get_task(task_id, ctx.organization_id)
        rows = (await db.execute(select(CodeTestResult).where(
            CodeTestResult.task_id == task.id))).scalars().all()
        passed = sum(1 for r in rows if str(r.status).lower() == "passed")
        failed = sum(1 for r in rows if str(r.status).lower() not in ("passed", "skipped"))
        findings: list = []
        diff_files: list[str] = []
        if task.workspace_id:
            try:
                diff = await svc.get_diff(task.workspace_id, ctx.organization_id,
                                          kind="working")
                text = diff.get("diff", "")
                for raw in text.splitlines():
                    if raw.startswith("+++ "):
                        path = raw[4:].strip()
                        if path.startswith("b/"):
                            path = path[2:]
                        if path != "/dev/null":
                            diff_files.append(path)
                if request.include_secret_scan:
                    findings = [{"kind": f.kind, "file": f.filename}
                                for f in scan_text_for_secrets(text, "working-diff")]
            except (CodeSecurityError, CodePolicyDenied, CodeNotFound):
                pass
        return await verify_code_change(
            db, organization_id=ctx.organization_id,
            test_summary={"passed": passed, "failed": failed} if rows else None,
            secret_findings=findings, diff_files=diff_files)
    except (CodeSecurityError, CodePolicyDenied, CodeNotFound) as exc:
        raise _deny(exc)


@router.get("/health")
async def code_health():
    return {"status": "healthy", "service": "code"}
