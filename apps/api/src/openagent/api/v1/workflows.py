from datetime import datetime
from typing import Optional, List, Dict, Any
from uuid import UUID
from fastapi import APIRouter, Depends, Request, HTTPException, status, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from openagent.db.session import get_db
from openagent.db.models import (
    AuditLog,
    Workflow,
    WorkflowStatus,
    WorkflowVersion,
    WorkflowExecution,
)
from openagent.db.repositories import (
    WorkflowRepository,
    WorkflowVersionRepository,
)
from openagent.schemas.base import ApiErrorResponse, PaginatedResponse
from openagent.api.dependencies import (
    get_current_org_context,
    require_permission,
)
from openagent.services.workflow_definition import (
    build_envelope,
    empty_definition,
    migrate_definition,
    parse_envelope,
    slugify,
    validate_definition,
)

router = APIRouter(prefix="/organizations/{organization_id}/workflows", tags=["workflows"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class WorkflowCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: Optional[str] = Field(default=None, min_length=1, max_length=100, pattern="^[a-z0-9-]+$")
    description: Optional[str] = None
    tags: List[str] = Field(default_factory=list, max_length=20)
    definition: Optional[Dict[str, Any]] = None


class WorkflowUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    tags: Optional[List[str]] = Field(default=None, max_length=20)
    status: Optional[str] = Field(default=None, pattern="^(draft|active|archived|deprecated)$")
    definition: Optional[Dict[str, Any]] = None
    # Optimistic concurrency: when provided, the update is rejected with 409
    # if the row changed since the caller read it.
    expected_updated_at: Optional[datetime] = None


class RestoreRequest(BaseModel):
    version: str = Field(min_length=1, max_length=50)


class ImportRequest(BaseModel):
    # Export envelope or raw definition (see parse_envelope).
    payload: Dict[str, Any]
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    slug: Optional[str] = Field(default=None, min_length=1, max_length=100, pattern="^[a-z0-9-]+$")
    description: Optional[str] = None


class WorkflowVersionResponse(BaseModel):
    id: UUID
    workflow_id: UUID
    version: str
    definition: Dict[str, Any]
    status: str
    created_by: Optional[UUID] = None
    created_at: datetime

    class Config:
        from_attributes = True


class LastExecutionResponse(BaseModel):
    id: UUID
    status: str
    trigger_type: str
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class WorkflowResponse(BaseModel):
    id: UUID
    organization_id: UUID
    name: str
    slug: str
    description: Optional[str] = None
    tags: List[str] = []
    status: str
    metadata: Dict[str, Any] = {}
    version_count: int = 0
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class WorkflowDetailResponse(WorkflowResponse):
    latest_version: Optional[WorkflowVersionResponse] = None
    last_execution: Optional[LastExecutionResponse] = None


class WorkflowListResponse(PaginatedResponse[WorkflowResponse]):
    pass


class VersionListResponse(PaginatedResponse[WorkflowVersionResponse]):
    pass


class ExecutionResponse(BaseModel):
    id: UUID
    organization_id: UUID
    workflow_id: UUID
    workflow_version_id: Optional[UUID] = None
    status: str
    trigger_type: str
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ExecutionListResponse(PaginatedResponse[ExecutionResponse]):
    pass


class ValidateRequest(BaseModel):
    definition: Dict[str, Any]


class ValidateResponse(BaseModel):
    valid: bool
    errors: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_workflow_or_404(db: AsyncSession, organization_id: UUID, workflow_id: UUID) -> Workflow:
    result = await db.execute(
        select(Workflow).where(
            Workflow.id == workflow_id,
            Workflow.organization_id == organization_id,
            Workflow.deleted_at.is_(None),
        )
    )
    workflow = result.scalar_one_or_none()
    if not workflow:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Workflow not found", "code": "WORKFLOW_NOT_FOUND"},
        )
    return workflow


async def _latest_version(db: AsyncSession, workflow_id: UUID) -> Optional[WorkflowVersion]:
    result = await db.execute(
        select(WorkflowVersion)
        .where(WorkflowVersion.workflow_id == workflow_id)
        .order_by(WorkflowVersion.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _version_count(db: AsyncSession, workflow_id: UUID) -> int:
    result = await db.execute(
        select(func.count(WorkflowVersion.id)).where(WorkflowVersion.workflow_id == workflow_id)
    )
    return result.scalar_one()


async def _last_execution(db: AsyncSession, workflow_id: UUID) -> Optional[WorkflowExecution]:
    result = await db.execute(
        select(WorkflowExecution)
        .where(WorkflowExecution.workflow_id == workflow_id)
        .order_by(WorkflowExecution.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


def _tags_of(workflow: Workflow) -> List[str]:
    tags = (workflow.metadata or {}).get("tags", [])
    return [t for t in tags if isinstance(t, str)][:20]


def _to_response(workflow: Workflow, version_count: int = 0) -> WorkflowResponse:
    return WorkflowResponse(
        id=workflow.id,
        organization_id=workflow.organization_id,
        name=workflow.name,
        slug=workflow.slug,
        description=workflow.description,
        tags=_tags_of(workflow),
        status=workflow.status.value if isinstance(workflow.status, WorkflowStatus) else str(workflow.status),
        metadata=workflow.metadata or {},
        version_count=version_count,
        created_at=workflow.created_at,
        updated_at=workflow.updated_at,
    )


async def _record_audit(
    db: AsyncSession,
    request: Request,
    organization_id: UUID,
    actor_user_id: Optional[UUID],
    action: str,
    workflow: Workflow,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """Best-effort audit trail. Never stores definitions or secrets."""
    try:
        db.add(AuditLog(
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            action=action,
            resource_type="workflow",
            resource_id=workflow.id,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("User-Agent"),
            metadata={
                "workflow_name": workflow.name,
                "slug": workflow.slug,
                **(extra or {}),
            },
        ))
        await db.flush()
    except Exception:
        # Audit must never break the primary operation.
        pass


async def _to_detail(db: AsyncSession, workflow: Workflow) -> WorkflowDetailResponse:
    base = _to_response(workflow, await _version_count(db, workflow.id))
    latest = await _latest_version(db, workflow.id)
    last = await _last_execution(db, workflow.id)
    return WorkflowDetailResponse(
        **base.model_dump(),
        latest_version=WorkflowVersionResponse.model_validate(latest) if latest else None,
        last_execution=LastExecutionResponse(
            id=last.id,
            status=last.status.value if hasattr(last.status, "value") else str(last.status),
            trigger_type=last.trigger_type.value if hasattr(last.trigger_type, "value") else str(last.trigger_type),
            started_at=last.started_at,
            completed_at=last.completed_at,
        ) if last else None,
    )


async def _create_version(
    db: AsyncSession,
    workflow: Workflow,
    definition: Dict[str, Any],
    created_by: Optional[UUID],
    version_status: str = "draft",
) -> WorkflowVersion:
    count = await _version_count(db, workflow.id)
    version = WorkflowVersion(
        workflow_id=workflow.id,
        version=f"v{count + 1}",
        definition=definition,
        status=version_status,
        created_by=created_by,
    )
    db.add(version)
    await db.flush()
    await db.refresh(version)
    return version


# ---------------------------------------------------------------------------
# Validate (no persistence)
# ---------------------------------------------------------------------------

@router.post(
    "/validate",
    response_model=ValidateResponse,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}},
)
async def validate_workflow_definition(
    request: Request,
    organization_id: UUID,
    data: ValidateRequest,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Validate a workflow definition without persisting anything.

    Used by the visual builder for live validation and dry-run checks.
    """
    await require_permission("workflow:update")(request, db)
    result = validate_definition(data.definition)
    return ValidateResponse(**result.to_dict())


# ---------------------------------------------------------------------------
# List / create
# ---------------------------------------------------------------------------

@router.get(
    "",
    response_model=WorkflowListResponse,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}},
)
async def list_workflows(
    request: Request,
    organization_id: UUID,
    search: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status", pattern="^(draft|active|archived|deprecated)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """List workflows in the organization."""
    await require_permission("workflow:read")(request, db)

    query = select(Workflow).where(
        Workflow.organization_id == organization_id,
        Workflow.deleted_at.is_(None),
    )
    count_query = select(func.count(Workflow.id)).where(
        Workflow.organization_id == organization_id,
        Workflow.deleted_at.is_(None),
    )
    if status_filter:
        query = query.where(Workflow.status == WorkflowStatus(status_filter))
        count_query = count_query.where(Workflow.status == WorkflowStatus(status_filter))
    if search:
        like = f"%{search}%"
        query = query.where(or_(Workflow.name.ilike(like), Workflow.slug.ilike(like)))
        count_query = count_query.where(or_(Workflow.name.ilike(like), Workflow.slug.ilike(like)))

    total = (await db.execute(count_query)).scalar_one()
    query = query.order_by(Workflow.updated_at.desc()).limit(page_size).offset((page - 1) * page_size)
    workflows = list((await db.execute(query)).scalars().all())

    items = []
    for w in workflows:
        items.append(_to_response(w, await _version_count(db, w.id)))

    from openagent.db.pagination import create_pagination_meta
    return WorkflowListResponse(data=items, meta=create_pagination_meta(page, page_size, total))


@router.post(
    "",
    response_model=WorkflowDetailResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"model": ApiErrorResponse},
        401: {"model": ApiErrorResponse},
        403: {"model": ApiErrorResponse},
        409: {"model": ApiErrorResponse},
    },
)
async def create_workflow(
    request: Request,
    organization_id: UUID,
    data: WorkflowCreate,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Create a workflow (always starts as a draft) with an initial v1 version.

    Invalid definitions are accepted for drafts; publish is gated on validity.
    """
    await require_permission("workflow:create")(request, db)

    slug = data.slug or slugify(data.name)
    existing = await db.execute(
        select(Workflow).where(
            Workflow.organization_id == organization_id,
            Workflow.slug == slug,
            Workflow.deleted_at.is_(None),
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": f"A workflow with slug '{slug}' already exists", "code": "WORKFLOW_SLUG_EXISTS"},
        )

    repo = WorkflowRepository(db)
    workflow = await repo.create(
        organization_id=organization_id,
        name=data.name,
        slug=slug,
        description=data.description,
        status=WorkflowStatus.DRAFT,
        metadata={"tags": [t[:50] for t in (data.tags or [])]},
    )
    await _create_version(db, workflow, data.definition or empty_definition(), auth_context.user_id)
    await _record_audit(db, request, organization_id, auth_context.user_id,
                        "workflow.created", workflow, {"version": "v1"})
    await db.commit()
    await db.refresh(workflow)
    return await _to_detail(db, workflow)


# ---------------------------------------------------------------------------
# Detail / update / delete
# ---------------------------------------------------------------------------

@router.get(
    "/{workflow_id}",
    response_model=WorkflowDetailResponse,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def get_workflow(
    request: Request,
    organization_id: UUID,
    workflow_id: UUID,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Get a workflow with its latest version and last execution."""
    await require_permission("workflow:read")(request, db)
    workflow = await _get_workflow_or_404(db, organization_id, workflow_id)
    return await _to_detail(db, workflow)


@router.patch(
    "/{workflow_id}",
    response_model=WorkflowDetailResponse,
    responses={
        400: {"model": ApiErrorResponse},
        401: {"model": ApiErrorResponse},
        403: {"model": ApiErrorResponse},
        404: {"model": ApiErrorResponse},
    },
)
async def update_workflow(
    request: Request,
    organization_id: UUID,
    workflow_id: UUID,
    data: WorkflowUpdate,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Update a workflow.

    A changed definition creates a new draft version (vN+1) without
    disturbing the published version. Status transitions are guarded:
    use /publish and /unpublish for draft<->active.
    """
    await require_permission("workflow:update")(request, db)
    workflow = await _get_workflow_or_404(db, organization_id, workflow_id)

    if data.expected_updated_at is not None and workflow.updated_at != data.expected_updated_at:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "This workflow changed since you opened it. Reload and reapply your edits.",
                "code": "STALE_UPDATE",
                "current_updated_at": workflow.updated_at.isoformat() if workflow.updated_at else None,
            },
        )

    if data.name is not None:
        workflow.name = data.name
    if data.description is not None:
        workflow.description = data.description
    if data.tags is not None:
        workflow.metadata = {**(workflow.metadata or {}), "tags": [t[:50] for t in data.tags]}

    if data.status is not None:
        target = WorkflowStatus(data.status)
        current = workflow.status
        allowed = {
            (WorkflowStatus.DRAFT, WorkflowStatus.ARCHIVED),
            (WorkflowStatus.ACTIVE, WorkflowStatus.ARCHIVED),
            (WorkflowStatus.ARCHIVED, WorkflowStatus.DRAFT),
            (WorkflowStatus.DEPRECATED, WorkflowStatus.DRAFT),
            (WorkflowStatus.ACTIVE, WorkflowStatus.DEPRECATED),
        }
        if target != current and (current, target) not in allowed:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": f"Cannot transition workflow from {current.value} to {target.value}. Use /publish or /unpublish.",
                    "code": "INVALID_STATUS_TRANSITION",
                },
            )
        workflow.status = target

    if data.definition is not None:
        version = await _create_version(db, workflow, data.definition, auth_context.user_id)
        await _record_audit(db, request, organization_id, auth_context.user_id,
                            "workflow.version_created", workflow, {"version": version.version})

    await db.commit()
    await db.refresh(workflow)
    return await _to_detail(db, workflow)


@router.delete(
    "/{workflow_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def delete_workflow(
    request: Request,
    organization_id: UUID,
    workflow_id: UUID,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete a workflow. Running executions are left untouched."""
    await require_permission("workflow:delete")(request, db)
    workflow = await _get_workflow_or_404(db, organization_id, workflow_id)
    await _record_audit(db, request, organization_id, auth_context.user_id,
                        "workflow.deleted", workflow)
    repo = WorkflowRepository(db)
    await repo.soft_delete_with_org(workflow_id, organization_id)
    await db.commit()


@router.post(
    "/{workflow_id}/duplicate",
    response_model=WorkflowDetailResponse,
    status_code=status.HTTP_201_CREATED,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def duplicate_workflow(
    request: Request,
    organization_id: UUID,
    workflow_id: UUID,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Duplicate a workflow (latest definition becomes v1 of the copy)."""
    await require_permission("workflow:create")(request, db)
    source = await _get_workflow_or_404(db, organization_id, workflow_id)
    latest = await _latest_version(db, source.id)

    base_slug = f"{source.slug}-copy"
    slug = base_slug
    suffix = 2
    while True:
        existing = await db.execute(
            select(Workflow).where(
                Workflow.organization_id == organization_id,
                Workflow.slug == slug,
                Workflow.deleted_at.is_(None),
            )
        )
        if not existing.scalar_one_or_none():
            break
        slug = f"{base_slug}-{suffix}"
        suffix += 1

    repo = WorkflowRepository(db)
    copy = await repo.create(
        organization_id=organization_id,
        name=f"{source.name} (copy)",
        slug=slug,
        description=source.description,
        status=WorkflowStatus.DRAFT,
        metadata=dict(source.metadata or {}),
    )
    definition = dict(latest.definition) if latest else empty_definition()
    version = await _create_version(db, copy, definition, auth_context.user_id)
    await _record_audit(db, request, organization_id, auth_context.user_id,
                        "workflow.created", copy,
                        {"version": version.version, "duplicated_from": str(source.id)})
    await db.commit()
    await db.refresh(copy)
    return await _to_detail(db, copy)


# ---------------------------------------------------------------------------
# Publish lifecycle
# ---------------------------------------------------------------------------

@router.post(
    "/{workflow_id}/publish",
    response_model=WorkflowDetailResponse,
    responses={
        400: {"model": ApiErrorResponse},
        401: {"model": ApiErrorResponse},
        403: {"model": ApiErrorResponse},
        404: {"model": ApiErrorResponse},
        422: {"model": ApiErrorResponse},
    },
)
async def publish_workflow(
    request: Request,
    organization_id: UUID,
    workflow_id: UUID,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Publish the latest version. Blocked unless the definition validates."""
    await require_permission("workflow:update")(request, db)
    workflow = await _get_workflow_or_404(db, organization_id, workflow_id)

    if workflow.status == WorkflowStatus.ACTIVE:
        return await _to_detail(db, workflow)

    latest = await _latest_version(db, workflow.id)
    if not latest:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "Workflow has no versions to publish", "code": "NO_VERSIONS"},
        )
    result = validate_definition(latest.definition or {})
    if not result.valid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "Workflow definition is invalid and cannot be published",
                "code": "INVALID_DEFINITION",
                "details": [
                    {"code": e.code, "message": e.message, "field": e.node_id or e.field}
                    for e in result.errors
                ],
            },
        )
    latest.status = "published"
    workflow.status = WorkflowStatus.ACTIVE
    await _record_audit(db, request, organization_id, auth_context.user_id,
                        "workflow.published", workflow, {"version": latest.version})
    await db.commit()
    await db.refresh(workflow)
    return await _to_detail(db, workflow)


@router.post(
    "/{workflow_id}/unpublish",
    response_model=WorkflowDetailResponse,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def unpublish_workflow(
    request: Request,
    organization_id: UUID,
    workflow_id: UUID,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Return an active workflow to draft (stops it being runnable)."""
    await require_permission("workflow:update")(request, db)
    workflow = await _get_workflow_or_404(db, organization_id, workflow_id)
    if workflow.status == WorkflowStatus.ACTIVE:
        workflow.status = WorkflowStatus.DRAFT
        await db.commit()
        await db.refresh(workflow)
    return await _to_detail(db, workflow)


# ---------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------

@router.get(
    "/{workflow_id}/versions",
    response_model=VersionListResponse,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def list_versions(
    request: Request,
    organization_id: UUID,
    workflow_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """List versions (newest first). Versions are immutable snapshots."""
    await require_permission("workflow:read")(request, db)
    await _get_workflow_or_404(db, organization_id, workflow_id)

    total = await _version_count(db, workflow_id)
    result = await db.execute(
        select(WorkflowVersion)
        .where(WorkflowVersion.workflow_id == workflow_id)
        .order_by(WorkflowVersion.created_at.desc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    items = [WorkflowVersionResponse.model_validate(v) for v in result.scalars().all()]

    from openagent.db.pagination import create_pagination_meta
    return VersionListResponse(data=items, meta=create_pagination_meta(page, page_size, total))


@router.get(
    "/{workflow_id}/versions/{version}",
    response_model=WorkflowVersionResponse,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def get_version(
    request: Request,
    organization_id: UUID,
    workflow_id: UUID,
    version: str,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Get a single immutable version snapshot (e.g. v3)."""
    await require_permission("workflow:read")(request, db)
    await _get_workflow_or_404(db, organization_id, workflow_id)
    repo = WorkflowVersionRepository(db)
    row = await repo.get_by_workflow_and_version(workflow_id, version)
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Version not found", "code": "VERSION_NOT_FOUND"},
        )
    return WorkflowVersionResponse.model_validate(row)


# ---------------------------------------------------------------------------
# Restore / import / export
# ---------------------------------------------------------------------------

@router.post(
    "/{workflow_id}/restore",
    response_model=WorkflowDetailResponse,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def restore_version(
    request: Request,
    organization_id: UUID,
    workflow_id: UUID,
    data: RestoreRequest,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Restore a version snapshot as a new draft version.

    Restoration never mutates history: it copies the snapshot into a fresh
    version so the audit trail stays intact.
    """
    await require_permission("workflow:update")(request, db)
    workflow = await _get_workflow_or_404(db, organization_id, workflow_id)
    repo = WorkflowVersionRepository(db)
    snapshot = await repo.get_by_workflow_and_version(workflow_id, data.version)
    if not snapshot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Version not found", "code": "VERSION_NOT_FOUND"},
        )
    version = await _create_version(db, workflow, dict(snapshot.definition or {}), auth_context.user_id)
    await _record_audit(db, request, organization_id, auth_context.user_id,
                        "workflow.restored", workflow,
                        {"version": version.version, "restored_from": snapshot.version})
    await db.commit()
    await db.refresh(workflow)
    return await _to_detail(db, workflow)


@router.post(
    "/import",
    response_model=WorkflowDetailResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"model": ApiErrorResponse},
        401: {"model": ApiErrorResponse},
        403: {"model": ApiErrorResponse},
        409: {"model": ApiErrorResponse},
    },
)
async def import_workflow(
    request: Request,
    organization_id: UUID,
    data: ImportRequest,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Import a workflow from an export envelope or a raw definition.

    The payload is treated as untrusted: structure-checked, schema-gated,
    and stored as a draft. Use /validate or publish for full rule checks.
    """
    await require_permission("workflow:create")(request, db)

    parsed, parse_error = parse_envelope(data.payload)
    if parse_error or not parsed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": parse_error or "Invalid import payload", "code": "INVALID_IMPORT"},
        )
    meta = parsed["meta"] or {}
    name = data.name or meta.get("name") or "Imported workflow"
    if not isinstance(name, str) or not name.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "Import requires a workflow name", "code": "INVALID_IMPORT"},
        )
    slug = data.slug or (meta.get("slug") if isinstance(meta.get("slug"), str) else None) or slugify(name)
    existing = await db.execute(
        select(Workflow).where(
            Workflow.organization_id == organization_id,
            Workflow.slug == slug,
            Workflow.deleted_at.is_(None),
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": f"A workflow with slug '{slug}' already exists", "code": "WORKFLOW_SLUG_EXISTS"},
        )
    description = data.description
    if description is None and isinstance(meta.get("description"), str):
        description = meta["description"]
    tags = meta.get("tags") if isinstance(meta.get("tags"), list) else []

    repo = WorkflowRepository(db)
    workflow = await repo.create(
        organization_id=organization_id,
        name=name.strip()[:255],
        slug=slug,
        description=description,
        status=WorkflowStatus.DRAFT,
        metadata={"tags": [t[:50] for t in tags if isinstance(t, str)][:20], "imported": True},
    )
    version = await _create_version(db, workflow, parsed["definition"], auth_context.user_id)
    await _record_audit(db, request, organization_id, auth_context.user_id,
                        "workflow.imported", workflow, {"version": version.version})
    await db.commit()
    await db.refresh(workflow)
    return await _to_detail(db, workflow)


@router.get(
    "/{workflow_id}/export",
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def export_workflow(
    request: Request,
    organization_id: UUID,
    workflow_id: UUID,
    version: Optional[str] = Query(None, description="Version snapshot to export (default: latest)"),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Export a portable envelope. Safe by construction: definitions hold
    only credential_id / {{...}} references (SECRET_VALUE blocks publish)."""
    await require_permission("workflow:read")(request, db)
    workflow = await _get_workflow_or_404(db, organization_id, workflow_id)
    if version:
        repo = WorkflowVersionRepository(db)
        snapshot = await repo.get_by_workflow_and_version(workflow_id, version)
        if not snapshot:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "Version not found", "code": "VERSION_NOT_FOUND"},
            )
        definition = snapshot.definition or {}
    else:
        latest = await _latest_version(db, workflow.id)
        definition = (latest.definition or {}) if latest else empty_definition()
    await _record_audit(db, request, organization_id, auth_context.user_id,
                        "workflow.exported", workflow, {"version": version or "latest"})
    await db.commit()
    return build_envelope(workflow.name, workflow.slug, workflow.description,
                          _tags_of(workflow), definition)


# ---------------------------------------------------------------------------
# Executions (read-only authoring context — engine ships later)
# ---------------------------------------------------------------------------

@router.get(
    "/{workflow_id}/executions",
    response_model=ExecutionListResponse,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def list_executions(
    request: Request,
    organization_id: UUID,
    workflow_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """List executions for authoring context (status, timing, errors)."""
    await require_permission("execution:read")(request, db)
    await _get_workflow_or_404(db, organization_id, workflow_id)

    total_result = await db.execute(
        select(func.count(WorkflowExecution.id)).where(WorkflowExecution.workflow_id == workflow_id)
    )
    total = total_result.scalar_one()
    result = await db.execute(
        select(WorkflowExecution)
        .where(WorkflowExecution.workflow_id == workflow_id)
        .order_by(WorkflowExecution.created_at.desc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    items = []
    for e in result.scalars().all():
        items.append(
            ExecutionResponse(
                id=e.id,
                organization_id=e.organization_id,
                workflow_id=e.workflow_id,
                workflow_version_id=e.workflow_version_id,
                status=e.status.value if hasattr(e.status, "value") else str(e.status),
                trigger_type=e.trigger_type.value if hasattr(e.trigger_type, "value") else str(e.trigger_type),
                started_at=e.started_at,
                completed_at=e.completed_at,
                error_code=e.error_code,
                error_message=e.error_message,
                created_at=e.created_at,
            )
        )

    from openagent.db.pagination import create_pagination_meta
    return ExecutionListResponse(data=items, meta=create_pagination_meta(page, page_size, total))


@router.post(
    "/{workflow_id}/execute",
    responses={
        401: {"model": ApiErrorResponse},
        403: {"model": ApiErrorResponse},
        404: {"model": ApiErrorResponse},
        501: {"model": ApiErrorResponse},
    },
)
async def execute_workflow(
    request: Request,
    organization_id: UUID,
    workflow_id: UUID,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Placeholder: real execution ships with the execution engine.

    The builder calls this honestly and surfaces the 501 to the user
    instead of faking a run.
    """
    await require_permission("workflow:execute")(request, db)
    await _get_workflow_or_404(db, organization_id, workflow_id)
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail={
            "error": "Workflow execution is not implemented yet. Authoring, validation, and versioning are available; the execution engine ships in a later phase.",
            "code": "EXECUTION_ENGINE_NOT_IMPLEMENTED",
        },
    )
