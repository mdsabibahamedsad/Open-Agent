"""MP22 API: packages / skills / presets / catalog / installations.

Conventions follow the existing v1 routers: org-scoped prefixes, RBAC via
``require_permission`` (AuthorizationError mapped to 403 here so denials
never surface as 500s), tenant isolation in every query, paginated lists,
and the shared error contract. Secrets are never accepted or returned:
configurations carry only references.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from openagent.api.dependencies import get_current_org_context, require_permission
from openagent.core.security.rate_limit import (
    get_client_identifier,
    rate_limit_dependency,
)
from openagent.db.models.package import (
    InstallationResource,
    PackageDependency,
    PackageFork,
    PackageInstallation,
    PackageInstallStatus,
    PackageResource,
    PackageSecurityScan,
    PackageSignature,
    PackageTrust,
    PackageValidationResult,
    PackageVersion,
    PackageVersionStatus,
    PackageVisibility,
    Preset,
    PresetVersion,
    ReusablePackage,
    ReusablePackageType,
    Skill,
    SkillVersion,
)
from openagent.db.pagination import PaginatedResponse, create_pagination_meta
from openagent.db.session import get_db
from openagent.packages import catalog as catalog_module
from openagent.packages import config_schema, installer, packaging, security as security_module
from openagent.packages import signing, telemetry, validation as validation_module
from openagent.packages.config import get_package_settings, validate_asset
from openagent.packages.graph import build_graph, to_mermaid
from openagent.packages.manifest import ManifestError, parse_manifest
from openagent.packages.types import (
    STANDARD_CATEGORIES,
    TrustLevel,
    Visibility,
    can_transition,
)
from openagent.packages.versioning import VersionError, is_valid_version
from openagent.schemas.base import ApiErrorResponse
from openagent.services.authorization import AuthorizationError

router = APIRouter(prefix="/organizations/{organization_id}/packages", tags=["packages"])
skills_router = APIRouter(prefix="/organizations/{organization_id}/skills", tags=["skills"])
presets_router = APIRouter(prefix="/organizations/{organization_id}/presets", tags=["presets"])
catalog_router = APIRouter(prefix="/organizations/{organization_id}/catalog", tags=["catalog"])
installations_router = APIRouter(
    prefix="/organizations/{organization_id}/installations", tags=["installations"]
)


async def _need(request: Request, db: AsyncSession, permission: str):
    """require_permission with AuthorizationError mapped to HTTP 403."""
    try:
        return await require_permission(permission)(request, db)
    except AuthorizationError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": str(exc), "code": "FORBIDDEN"},
        )


async def _rate_limited(request: Request, endpoint: str, limit: int, window: int) -> None:
    identifier = await get_client_identifier(request)
    await rate_limit_dependency(f"{identifier}", f"packages:{endpoint}", limit, window)


def _not_found(resource: str = "Package") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"error": f"{resource} not found", "code": "NOT_FOUND"},
    )


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class PackageCreate(BaseModel):
    slug: str = Field(min_length=1, max_length=160, pattern="^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=5000)
    package_type: str = Field(default="TEMPLATE_PACKAGE")
    visibility: str = Field(default=Visibility.ORGANIZATION.value)
    license: str = Field(default="Apache-2.0")
    categories: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    manifest: Optional[dict[str, Any]] = None


class PackageUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    visibility: Optional[str] = None
    categories: Optional[list[str]] = None
    tags: Optional[list[str]] = None
    license: Optional[str] = None


class VersionCreate(BaseModel):
    version: str = Field(min_length=1, max_length=32)
    manifest: dict[str, Any]
    changelog: str = Field(default="", max_length=10000)


class PackageResponse(BaseModel):
    id: UUID
    organization_id: Optional[UUID] = None
    slug: str
    name: str
    description: str
    package_type: str
    visibility: str
    trust: str
    official: bool
    license: str
    author_name: str
    publisher: str
    categories: list[str]
    tags: list[str]
    latest_version: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class PackageListResponse(PaginatedResponse[PackageResponse]):
    pass


class VersionResponse(BaseModel):
    id: UUID
    package_id: UUID
    version: str
    status: str
    content_hash: str
    risk: str
    changelog: str
    published_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class VersionListResponse(PaginatedResponse[VersionResponse]):
    pass


class InstallRequest(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = Field(default="", max_length=100)


class UpdatePlanRequest(BaseModel):
    to_version: str = Field(min_length=1, max_length=32)


class ForkRequest(BaseModel):
    slug: str = Field(min_length=1, max_length=160, pattern="^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
    name: str = Field(min_length=1, max_length=255)


class ImportRequest(BaseModel):
    files: dict[str, str]
    slug: Optional[str] = Field(default=None, max_length=160)
    visibility: str = Field(default=Visibility.ORGANIZATION.value)


class SkillCreate(BaseModel):
    slug: str = Field(min_length=1, max_length=160, pattern="^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=5000)
    visibility: str = Field(default=Visibility.ORGANIZATION.value)
    instructions: str = Field(default="", max_length=20000)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    required_tools: list[str] = Field(default_factory=list)
    required_connectors: list[str] = Field(default_factory=list)
    evaluation_criteria: list[str] = Field(default_factory=list)


class SkillVersionCreate(BaseModel):
    version: str = Field(min_length=1, max_length=32)
    instructions: str = Field(default="", max_length=20000)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    required_tools: list[str] = Field(default_factory=list)
    required_connectors: list[str] = Field(default_factory=list)
    model_requirements: dict[str, Any] = Field(default_factory=dict)
    memory_requirements: dict[str, Any] = Field(default_factory=dict)
    evaluation_criteria: list[str] = Field(default_factory=list)


class SkillAttachRequest(BaseModel):
    target_type: str = Field(pattern="^(agent|workflow)$")
    target_id: UUID


class PresetCreate(BaseModel):
    slug: str = Field(min_length=1, max_length=160, pattern="^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
    name: str = Field(min_length=1, max_length=255)
    kind: str = Field(pattern="^(MODEL_PRESET|AGENT_PRESET|WORKFLOW_PRESET|MEMORY_PRESET)$")
    description: str = Field(default="", max_length=5000)
    visibility: str = Field(default=Visibility.ORGANIZATION.value)
    payload: dict[str, Any] = Field(default_factory=dict)


class PresetVersionCreate(BaseModel):
    version: str = Field(min_length=1, max_length=32)
    payload: dict[str, Any]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _to_package_response(pkg) -> PackageResponse:
    return PackageResponse(
        id=pkg.id, organization_id=pkg.organization_id, slug=pkg.slug,
        name=pkg.name, description=pkg.description,
        package_type=pkg.package_type.value, visibility=pkg.visibility.value,
        trust=pkg.trust.value, official=pkg.official, license=pkg.license,
        author_name=pkg.author_name, publisher=pkg.publisher,
        categories=pkg.categories, tags=pkg.tags,
        latest_version=pkg.latest_version, created_at=pkg.created_at,
        updated_at=pkg.updated_at,
    )


def _to_version_response(version) -> VersionResponse:
    return VersionResponse(
        id=version.id, package_id=version.package_id, version=version.version,
        status=version.status.value, content_hash=version.content_hash,
        risk=version.risk, changelog=version.changelog,
        published_at=version.published_at, created_at=version.created_at,
        updated_at=version.updated_at,
    )


def _visible_to_org(model, organization_id: UUID):
    return or_(
        model.organization_id == organization_id,
        (model.organization_id.is_(None))
        & (model.visibility.in_([PackageVisibility.PUBLIC, PackageVisibility.UNLISTED])),
    )


async def _get_package(db: AsyncSession, organization_id: UUID, package_id: UUID):
    pkg = await db.get(ReusablePackage, package_id)
    if pkg is None or pkg.deleted_at is not None:
        raise _not_found()
    if pkg.organization_id is not None and pkg.organization_id != organization_id:
        raise _not_found()  # never leak cross-tenant existence
    if pkg.organization_id is None and pkg.visibility not in (
        PackageVisibility.PUBLIC, PackageVisibility.UNLISTED,
    ):
        # Global non-public entries are platform-internal.
        raise _not_found()
    return pkg


async def _get_version(db: AsyncSession, package_id: UUID, version: str):
    row = (
        await db.execute(
            select(PackageVersion).where(
                PackageVersion.package_id == package_id,
                PackageVersion.version == version,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise _not_found("Package version")
    return row


async def _create_version_rows(
    db: AsyncSession, package, manifest_dict: dict[str, Any], created_by,
    source_package_id=None, source_version: str = "",
):
    manifest = parse_manifest(manifest_dict)
    canonical = manifest.model_dump()
    content_hash = signing.content_hash(canonical)
    version_row = PackageVersion(
        package_id=package.id,
        version=manifest.package.version,
        status=PackageVersionStatus.DRAFT,
        manifest=canonical,
        content_hash=content_hash,
        risk=security_module.risk_level(security_module.scan_manifest_dict(canonical)),
        changelog=manifest.changelog,
        created_by=created_by,
        source_package_id=source_package_id,
        source_version=source_version,
    )
    db.add(version_row)
    await db.flush()
    for resource in manifest.resources:
        db.add(
            PackageResource(
                version_id=version_row.id, kind=resource.kind.upper(),
                slug=resource.slug, name=resource.name,
                payload=resource.payload,
                content_hash=signing.content_hash(
                    {"kind": resource.kind, "slug": resource.slug,
                     "payload": resource.payload}),
            )
        )
    for dep in manifest.dependencies:
        db.add(
            PackageDependency(
                version_id=version_row.id, dep_type=dep.type.lower(),
                package=dep.package, constraint=dep.version,
                optional=dep.optional, peer=dep.peer,
            )
        )
    package.latest_version = manifest.package.version
    await db.flush()
    return version_row


async def _transition_version(db: AsyncSession, version, target: str, **touch):
    source = version.status.value
    if not can_transition(source, target):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": f"Cannot transition {source} -> {target}",
                    "code": "BAD_TRANSITION"},
        )
    version.status = PackageVersionStatus(target)
    now = datetime.now(timezone.utc)
    if target == PackageVersionStatus.PUBLISHED.value:
        version.published_at = now
    if target == PackageVersionStatus.DEPRECATED.value:
        version.deprecated_at = now
    if target == PackageVersionStatus.REVOKED.value:
        version.revoked_at = now
        version.revoked_reason = str(touch.get("reason", ""))
    for key, value in touch.items():
        if key != "reason" and hasattr(version, key):
            setattr(version, key, value)
    await db.flush()
    return version


# ---------------------------------------------------------------------------
# Packages
# ---------------------------------------------------------------------------

@router.get("", response_model=PackageListResponse,
            responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}})
async def list_packages(
    request: Request, organization_id: UUID,
    search: Optional[str] = Query(None), package_type: Optional[str] = Query(None),
    trust: Optional[str] = Query(None), visibility: Optional[str] = Query(None),
    official: Optional[bool] = Query(None), category: Optional[str] = Query(None),
    tag: Optional[str] = Query(None),
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "package:read")
    query = select(ReusablePackage).where(
        ReusablePackage.deleted_at.is_(None), _visible_to_org(ReusablePackage, organization_id))
    count_q = select(func.count(ReusablePackage.id)).where(
        ReusablePackage.deleted_at.is_(None), _visible_to_org(ReusablePackage, organization_id))
    if package_type:
        query = query.where(ReusablePackage.package_type == package_type.upper())
        count_q = count_q.where(ReusablePackage.package_type == package_type.upper())
    if trust:
        query = query.where(ReusablePackage.trust == trust.upper())
        count_q = count_q.where(ReusablePackage.trust == trust.upper())
    if visibility:
        query = query.where(ReusablePackage.visibility == visibility.upper())
        count_q = count_q.where(ReusablePackage.visibility == visibility.upper())
    if official is not None:
        query = query.where(ReusablePackage.official.is_(official))
        count_q = count_q.where(ReusablePackage.official.is_(official))
    if search:
        like = f"%{search}%"
        query = query.where(or_(ReusablePackage.name.ilike(like),
                                ReusablePackage.slug.ilike(like),
                                ReusablePackage.description.ilike(like)))
        count_q = count_q.where(or_(ReusablePackage.name.ilike(like),
                                    ReusablePackage.slug.ilike(like),
                                    ReusablePackage.description.ilike(like)))
    total = (await db.execute(count_q)).scalar_one()
    rows = list((await db.execute(query.order_by(ReusablePackage.updated_at.desc())
                  .limit(page_size).offset((page - 1) * page_size))).scalars().all())
    if category:
        rows = [r for r in rows if category in (r.categories or [])]
    if tag:
        rows = [r for r in rows if tag in (r.tags or [])]
    return PackageListResponse(data=[_to_package_response(r) for r in rows],
                               meta=create_pagination_meta(page, page_size, total))


@router.post("", response_model=PackageResponse, status_code=status.HTTP_201_CREATED,
             responses={400: {"model": ApiErrorResponse}, 401: {"model": ApiErrorResponse},
                        403: {"model": ApiErrorResponse}, 409: {"model": ApiErrorResponse}})
async def create_package(
    request: Request, organization_id: UUID, data: PackageCreate,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "package:create")
    if data.visibility.upper() not in {v.value for v in Visibility}:
        raise HTTPException(status_code=400, detail={"error": "Unknown visibility",
                                                     "code": "BAD_VISIBILITY"})
    try:
        ptype = ReusablePackageType(data.package_type.upper())
    except ValueError:
        raise HTTPException(status_code=400, detail={"error": "Unknown package_type",
                                                     "code": "BAD_TYPE"})
    existing = (await db.execute(select(ReusablePackage).where(
        ReusablePackage.organization_id == organization_id,
        ReusablePackage.slug == data.slug,
        ReusablePackage.deleted_at.is_(None)))).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail={"error": "Package slug exists",
                                                     "code": "PACKAGE_EXISTS"})
    pkg = ReusablePackage(
        organization_id=organization_id, slug=data.slug, name=data.name,
        description=data.description, package_type=ptype,
        visibility=PackageVisibility(data.visibility.upper()),
        trust=PackageTrust.ORGANIZATION, official=False,
        license=data.license, author_name="", publisher="",
        categories=data.categories, tags=data.tags,
        owner_user_id=auth_context.user_id,
    )
    db.add(pkg)
    await db.flush()
    if data.manifest is not None:
        try:
            await _create_version_rows(db, pkg, data.manifest, auth_context.user_id)
        except (ManifestError, VersionError) as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc),
                                                         "code": "BAD_MANIFEST"})
    await db.commit()
    await db.refresh(pkg)
    await telemetry.audit(db, organization_id=organization_id,
                          actor_user_id=auth_context.user_id,
                          action="package.create", resource_id=pkg.id,
                          metadata={"slug": pkg.slug})
    await telemetry.emit(db, event_type="PACKAGE_CREATED", aggregate_id=pkg.id,
                         organization_id=organization_id, user_id=auth_context.user_id,
                         payload={"slug": pkg.slug})
    await db.commit()
    return _to_package_response(pkg)


@router.get("/{package_id}", response_model=PackageResponse,
            responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse},
                       404: {"model": ApiErrorResponse}})
async def get_package(
    request: Request, organization_id: UUID, package_id: UUID,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "package:read")
    return _to_package_response(await _get_package(db, organization_id, package_id))


@router.patch("/{package_id}", response_model=PackageResponse,
              responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse},
                         404: {"model": ApiErrorResponse}})
async def update_package(
    request: Request, organization_id: UUID, package_id: UUID, data: PackageUpdate,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "package:update")
    pkg = await _get_package(db, organization_id, package_id)
    if pkg.organization_id is None and not auth_context.is_platform_owner:
        raise HTTPException(status_code=403, detail={"error": "Only platform owners edit global packages",
                                                     "code": "FORBIDDEN"})
    if data.name is not None:
        pkg.name = data.name
    if data.description is not None:
        pkg.description = data.description
    if data.visibility is not None:
        if data.visibility.upper() not in {v.value for v in Visibility}:
            raise HTTPException(status_code=400, detail={"error": "Unknown visibility",
                                                         "code": "BAD_VISIBILITY"})
        pkg.visibility = PackageVisibility(data.visibility.upper())
    if data.categories is not None:
        pkg.categories = data.categories
    if data.tags is not None:
        pkg.tags = data.tags
    if data.license is not None:
        pkg.license = data.license
    await db.commit()
    await db.refresh(pkg)
    await telemetry.audit(db, organization_id=organization_id,
                          actor_user_id=auth_context.user_id,
                          action="package.update", resource_id=pkg.id)
    await db.commit()
    return _to_package_response(pkg)


@router.delete("/{package_id}", status_code=status.HTTP_204_NO_CONTENT,
               responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse},
                          404: {"model": ApiErrorResponse}})
async def delete_package(
    request: Request, organization_id: UUID, package_id: UUID,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "package:delete")
    from datetime import datetime as _dt

    pkg = await _get_package(db, organization_id, package_id)
    if pkg.organization_id is None and not auth_context.is_platform_owner:
        raise HTTPException(status_code=403, detail={"error": "Only platform owners delete global packages",
                                                     "code": "FORBIDDEN"})
    pkg.deleted_at = _dt.now(timezone.utc)
    await db.commit()
    await telemetry.audit(db, organization_id=organization_id,
                          actor_user_id=auth_context.user_id,
                          action="package.delete", resource_id=pkg.id)
    await db.commit()


@router.get("/{package_id}/versions", response_model=VersionListResponse,
            responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse},
                       404: {"model": ApiErrorResponse}})
async def list_versions(
    request: Request, organization_id: UUID, package_id: UUID,
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "package:read")
    await _get_package(db, organization_id, package_id)
    total = (await db.execute(select(func.count(PackageVersion.id)).where(
        PackageVersion.package_id == package_id))).scalar_one()
    rows = list((await db.execute(select(PackageVersion).where(
        PackageVersion.package_id == package_id).order_by(
        PackageVersion.created_at.desc()).limit(page_size).offset(
        (page - 1) * page_size))).scalars().all())
    return VersionListResponse(data=[_to_version_response(r) for r in rows],
                               meta=create_pagination_meta(page, page_size, total))


@router.post("/{package_id}/versions", response_model=VersionResponse,
             status_code=status.HTTP_201_CREATED,
             responses={400: {"model": ApiErrorResponse}, 401: {"model": ApiErrorResponse},
                        403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse},
                        409: {"model": ApiErrorResponse}})
async def create_version(
    request: Request, organization_id: UUID, package_id: UUID, data: VersionCreate,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "package:create")
    pkg = await _get_package(db, organization_id, package_id)
    if not is_valid_version(data.version):
        raise HTTPException(status_code=400, detail={"error": "Invalid version",
                                                     "code": "BAD_VERSION"})
    dup = (await db.execute(select(PackageVersion).where(
        PackageVersion.package_id == package_id,
        PackageVersion.version == data.version.lstrip("v")))).scalar_one_or_none()
    if dup is not None:
        raise HTTPException(status_code=409, detail={"error": "Version exists",
                                                     "code": "VERSION_EXISTS"})
    try:
        row = await _create_version_rows(db, pkg, data.manifest, auth_context.user_id)
    except (ManifestError, VersionError) as exc:
        raise HTTPException(status_code=400, detail={"error": str(exc),
                                                     "code": "BAD_MANIFEST"})
    if row.version != data.version.lstrip("v"):
        raise HTTPException(status_code=400, detail={
            "error": "manifest version does not match requested version",
            "code": "VERSION_MISMATCH"})
    await db.commit()
    await db.refresh(row)
    await telemetry.audit(db, organization_id=organization_id,
                          actor_user_id=auth_context.user_id,
                          action="package.version.create", resource_id=row.id,
                          metadata={"version": row.version})
    await telemetry.emit(db, event_type="PACKAGE_VERSION_CREATED", aggregate_id=pkg.id,
                         organization_id=organization_id, user_id=auth_context.user_id,
                         payload={"version": row.version})
    await db.commit()
    return _to_version_response(row)


@router.get("/{package_id}/versions/{version}",
            responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse},
                       404: {"model": ApiErrorResponse}})
async def get_version(
    request: Request, organization_id: UUID, package_id: UUID, version: str,
    include_manifest: bool = Query(True),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "package:read")
    await _get_package(db, organization_id, package_id)
    row = await _get_version(db, package_id, version)
    body = _to_version_response(row).model_dump(mode="json")
    if include_manifest:
        body["manifest"] = row.manifest
    graph = build_graph(
        [{"kind": r.kind, "slug": r.slug, "name": r.name, "payload": r.payload}
         for r in row.resources],
        [{"type": d.dep_type, "package": d.package} for d in row.dependencies],
    )
    body["graph"] = graph
    body["mermaid"] = to_mermaid(graph)
    return body


@router.post("/{package_id}/versions/{version}/validate",
             responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse},
                        404: {"model": ApiErrorResponse}, 429: {"model": ApiErrorResponse}})
async def validate_version(
    request: Request, organization_id: UUID, package_id: UUID, version: str,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "package:update")
    await _rate_limited(request, "validate", 30, 3600)
    await _get_package(db, organization_id, package_id)
    row = await _get_version(db, package_id, version)
    if row.status not in (PackageVersionStatus.DRAFT, PackageVersionStatus.VALIDATING,
                          PackageVersionStatus.VALIDATED):
        raise HTTPException(status_code=409, detail={
            "error": f"Cannot validate from status {row.status.value}",
            "code": "BAD_STATE"})
    row.status = PackageVersionStatus.VALIDATING
    await db.flush()
    report = validation_module.validate_package(dict(row.manifest or {}))
    db.add(PackageValidationResult(version_id=row.id, passed=report["passed"],
                                   findings=report["findings"], stages=report["stages"]))
    db.add(PackageSecurityScan(version_id=row.id, risk=report["risk"],
                               findings=report["stages"].get("security", []),
                               scanner_version="1"))
    row.status = (PackageVersionStatus.VALIDATED if report["passed"]
                  else PackageVersionStatus.DRAFT)
    telemetry.inc("package_validation_total")
    if not report["passed"]:
        telemetry.inc("package_validation_failed_total")
    await db.flush()
    await telemetry.audit(db, organization_id=organization_id,
                          actor_user_id=auth_context.user_id,
                          action="package.validate", resource_id=row.id,
                          metadata={"passed": report["passed"]})
    await telemetry.emit(db, event_type="PACKAGE_VALIDATED", aggregate_id=package_id,
                         organization_id=organization_id, user_id=auth_context.user_id,
                         payload={"version": row.version, "passed": report["passed"]})
    await db.commit()
    return report


@router.post("/{package_id}/versions/{version}/publish", response_model=VersionResponse,
             responses={400: {"model": ApiErrorResponse}, 401: {"model": ApiErrorResponse},
                        403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse},
                        409: {"model": ApiErrorResponse}, 429: {"model": ApiErrorResponse}})
async def publish_version(
    request: Request, organization_id: UUID, package_id: UUID, version: str,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "package:manage")
    await _rate_limited(request, "publish", get_package_settings().RATE_LIMIT_PUBLISH_PER_HOUR, 3600)
    pkg = await _get_package(db, organization_id, package_id)
    row = await _get_version(db, package_id, version)
    if row.status == PackageVersionStatus.PUBLISHED:
        return _to_version_response(row)
    report = validation_module.validate_package(dict(row.manifest or {}))
    if not report["passed"]:
        raise HTTPException(status_code=400, detail={
            "error": "Package failed validation; fix findings before publishing",
            "code": "VALIDATION_FAILED", "findings": report["findings"][:10]})
    if pkg.official or pkg.trust.value == TrustLevel.CORE.value:
        sig = (await db.execute(select(PackageSignature).where(
            PackageSignature.version_id == row.id))).scalar_one_or_none()
        if get_package_settings().REQUIRE_SIGNATURE_FOR_CORE and (
                sig is None or not sig.verified):
            raise HTTPException(status_code=400, detail={
                "error": "Official/core packages require a verified signature",
                "code": "SIGNATURE_REQUIRED"})
    # VALIDATING is an internal marker; accept DRAFT or VALIDATED here.
    if row.status == PackageVersionStatus.DRAFT:
        await _transition_version(db, row, PackageVersionStatus.VALIDATED.value)
    await _transition_version(db, row, PackageVersionStatus.PUBLISHED.value)
    row.risk = report["risk"]
    await db.commit()
    await db.refresh(row)
    await telemetry.audit(db, organization_id=organization_id,
                          actor_user_id=auth_context.user_id,
                          action="package.publish", resource_id=row.id,
                          metadata={"version": row.version})
    await telemetry.emit(db, event_type="PACKAGE_PUBLISHED", aggregate_id=package_id,
                         organization_id=organization_id, user_id=auth_context.user_id,
                         payload={"version": row.version})
    await db.commit()
    return _to_version_response(row)


@router.post("/{package_id}/versions/{version}/deprecate", response_model=VersionResponse,
             responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse},
                        404: {"model": ApiErrorResponse}, 409: {"model": ApiErrorResponse}})
async def deprecate_version(
    request: Request, organization_id: UUID, package_id: UUID, version: str,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "package:manage")
    await _get_package(db, organization_id, package_id)
    row = await _get_version(db, package_id, version)
    await _transition_version(db, row, PackageVersionStatus.DEPRECATED.value)
    await db.commit()
    await db.refresh(row)
    return _to_version_response(row)


class RevokeRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)


@router.post("/{package_id}/versions/{version}/revoke", response_model=VersionResponse,
             responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse},
                        404: {"model": ApiErrorResponse}, 409: {"model": ApiErrorResponse}})
async def revoke_version(
    request: Request, organization_id: UUID, package_id: UUID, version: str,
    data: RevokeRequest,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "package:manage")
    await _get_package(db, organization_id, package_id)
    row = await _get_version(db, package_id, version)
    await _transition_version(db, row, PackageVersionStatus.REVOKED.value, reason=data.reason)
    await db.commit()
    await db.refresh(row)
    await telemetry.audit(db, organization_id=organization_id,
                          actor_user_id=auth_context.user_id,
                          action="package.revoke", resource_id=row.id,
                          metadata={"version": row.version, "reason": data.reason})
    await telemetry.emit(db, event_type="PACKAGE_REVOKED", aggregate_id=package_id,
                         organization_id=organization_id, user_id=auth_context.user_id,
                         payload={"version": row.version})
    await db.commit()
    return _to_version_response(row)


@router.get("/{package_id}/versions/{v1}/diff/{v2}",
            responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse},
                       404: {"model": ApiErrorResponse}})
async def diff_versions(
    request: Request, organization_id: UUID, package_id: UUID, v1: str, v2: str,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "package:read")
    await _get_package(db, organization_id, package_id)
    old = await _get_version(db, package_id, v1)
    new = await _get_version(db, package_id, v2)
    return packaging.diff_manifests(dict(old.manifest or {}), dict(new.manifest or {}))


@router.get("/{package_id}/versions/{version}/security",
            responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse},
                       404: {"model": ApiErrorResponse}})
async def security_report(
    request: Request, organization_id: UUID, package_id: UUID, version: str,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "package:read")
    from openagent.packages.security import trust_policy

    pkg = await _get_package(db, organization_id, package_id)
    row = await _get_version(db, package_id, version)
    findings = security_module.scan_manifest_dict(dict(row.manifest or {}))
    manifest = parse_manifest(dict(row.manifest or {}))
    return {
        "trust_level": pkg.trust.value,
        "official": pkg.official,
        "risk": security_module.risk_level(findings),
        "capabilities": sorted({str(v) for r in manifest.resources
                                for v in (r.payload.get("capabilities", []) or [])
                                if isinstance(v, str)}),
        "requires_approval": manifest.security.required_approvals,
        "network": manifest.security.network,
        "sandbox": manifest.security.sandbox_profile,
        "credential_references": config_schema.required_references(
            manifest.configuration or {}),
        "warnings": findings,
        "policy": trust_policy(pkg.trust.value),
    }


@router.post("/{package_id}/versions/{version}/install-preview",
             responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse},
                        404: {"model": ApiErrorResponse}, 409: {"model": ApiErrorResponse}})
async def install_preview(
    request: Request, organization_id: UUID, package_id: UUID, version: str,
    body: InstallRequest,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "package:execute")
    await _get_package(db, organization_id, package_id)
    row = await _get_version(db, package_id, version)
    try:
        return await installer.preview_install(
            db, organization_id=organization_id, version_id=row.id,
            values=body.values)
    except installer.InstallationError as exc:
        raise HTTPException(status_code=409, detail={"error": str(exc), "code": exc.code})


@router.post("/{package_id}/versions/{version}/install",
             responses={400: {"model": ApiErrorResponse}, 401: {"model": ApiErrorResponse},
                        403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse},
                        409: {"model": ApiErrorResponse}, 429: {"model": ApiErrorResponse}})
async def install_version(
    request: Request, organization_id: UUID, package_id: UUID, version: str,
    body: InstallRequest,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "package:execute")
    await _rate_limited(request, "install",
                        get_package_settings().RATE_LIMIT_INSTALL_PER_HOUR, 3600)
    await _get_package(db, organization_id, package_id)
    row = await _get_version(db, package_id, version)
    try:
        installation = await installer.install(
            db, organization_id=organization_id, version_id=row.id,
            installed_by=auth_context.user_id, values=body.values,
            idempotency_key=body.idempotency_key)
    except installer.InstallationError as exc:
        code = 400 if exc.code in ("VALIDATION_FAILED", "NOT_PUBLISHED") else 409
        raise HTTPException(status_code=code,
                            detail={"error": str(exc), "code": exc.code})
    return {"id": str(installation.id), "status": installation.status.value,
            "version_id": str(installation.version_id),
            "error": installation.error}


@router.post("/{package_id}/fork", response_model=PackageResponse,
             status_code=status.HTTP_201_CREATED,
             responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse},
                        404: {"model": ApiErrorResponse}, 409: {"model": ApiErrorResponse}})
async def fork_package(
    request: Request, organization_id: UUID, package_id: UUID, data: ForkRequest,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "package:create")
    source = await _get_package(db, organization_id, package_id)
    if source.visibility == PackageVisibility.PRIVATE and \
            source.organization_id != organization_id:
        raise _not_found()
    existing = (await db.execute(select(ReusablePackage).where(
        ReusablePackage.organization_id == organization_id,
        ReusablePackage.slug == data.slug,
        ReusablePackage.deleted_at.is_(None)))).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail={"error": "Slug exists",
                                                     "code": "PACKAGE_EXISTS"})
    latest = None
    if source.latest_version:
        latest = (await db.execute(select(PackageVersion).where(
            PackageVersion.package_id == source.id,
            PackageVersion.version == source.latest_version,
        ))).scalar_one_or_none()
    fork = ReusablePackage(
        organization_id=organization_id, slug=data.slug, name=data.name,
        description=source.description, package_type=source.package_type,
        visibility=PackageVisibility.ORGANIZATION, trust=PackageTrust.ORGANIZATION,
        official=False, license=source.license, author_name="",
        publisher="", categories=source.categories, tags=source.tags,
        owner_user_id=auth_context.user_id, latest_version="",
    )
    db.add(fork)
    await db.flush()
    if latest is not None:
        forked_manifest = dict(latest.manifest or {})
        forked_manifest["package"] = {**(forked_manifest.get("package", {})),
                                      "id": data.slug, "name": data.name}
        await _create_version_rows(db, fork, forked_manifest, auth_context.user_id,
                                   source_package_id=source.id,
                                   source_version=latest.version)
    db.add(PackageFork(package_id=fork.id, parent_package_id=source.id,
                       parent_version=source.latest_version,
                       forked_by=auth_context.user_id))
    await db.commit()
    await db.refresh(fork)
    telemetry.inc("package_fork_total")
    await telemetry.audit(db, organization_id=organization_id,
                          actor_user_id=auth_context.user_id,
                          action="package.fork", resource_id=fork.id,
                          metadata={"parent": str(source.id)})
    await telemetry.emit(db, event_type="PACKAGE_FORKED", aggregate_id=fork.id,
                         organization_id=organization_id, user_id=auth_context.user_id,
                         payload={"parent_package_id": str(source.id)})
    await db.commit()
    return _to_package_response(fork)


@router.post("/{package_id}/versions/{version}/export",
             responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse},
                        404: {"model": ApiErrorResponse}, 429: {"model": ApiErrorResponse}})
async def export_version(
    request: Request, organization_id: UUID, package_id: UUID, version: str,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "package:read")
    await _rate_limited(request, "export", 60, 3600)
    await _get_package(db, organization_id, package_id)
    row = await _get_version(db, package_id, version)
    try:
        files = packaging.build_export_files(dict(row.manifest or {}))
    except packaging.PackagingError as exc:
        raise HTTPException(status_code=400, detail={"error": str(exc),
                                                     "code": "EXPORT_BLOCKED"})
    telemetry.inc("package_download_total")
    await telemetry.audit(db, organization_id=organization_id,
                          actor_user_id=auth_context.user_id,
                          action="package.export", resource_id=row.id)
    await telemetry.emit(db, event_type="PACKAGE_EXPORTED", aggregate_id=package_id,
                         organization_id=organization_id, user_id=auth_context.user_id,
                         payload={"version": row.version})
    await db.commit()
    return {"files": files, "format": "openagent-package", "format_version": "1"}


@router.post("/import",
             responses={400: {"model": ApiErrorResponse}, 401: {"model": ApiErrorResponse},
                        403: {"model": ApiErrorResponse}, 409: {"model": ApiErrorResponse},
                        429: {"model": ApiErrorResponse}})
async def import_package(
    request: Request, organization_id: UUID, data: ImportRequest,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "package:create")
    await _rate_limited(request, "import", 30, 3600)
    try:
        preview = packaging.import_preview(data.files)
    except packaging.PackagingError as exc:
        raise HTTPException(status_code=400, detail={"error": str(exc),
                                                     "code": "BAD_BUNDLE"})
    manifest_dict = packaging.parse_import_files(data.files)
    manifest = parse_manifest(manifest_dict)
    slug = data.slug or manifest.package.id
    existing = (await db.execute(select(ReusablePackage).where(
        ReusablePackage.organization_id == organization_id,
        ReusablePackage.slug == slug,
        ReusablePackage.deleted_at.is_(None)))).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail={"error": "Slug exists",
                                                     "code": "PACKAGE_EXISTS"})
    # Imported content is untrusted by default; PUBLIC visibility requires
    # publish rights and is never granted implicitly.
    visibility = PackageVisibility.ORGANIZATION
    if data.visibility.upper() in ("PRIVATE", "TEAM", "ORGANIZATION", "UNLISTED"):
        visibility = PackageVisibility(data.visibility.upper())
    pkg = ReusablePackage(
        organization_id=organization_id, slug=slug, name=manifest.package.name,
        description=manifest.description,
        package_type=ReusablePackageType(manifest.package.type),
        visibility=visibility, trust=PackageTrust.UNTRUSTED, official=False,
        license=manifest.license, author_name=manifest.author.name,
        publisher="", categories=manifest.categories, tags=manifest.tags,
        owner_user_id=auth_context.user_id,
    )
    db.add(pkg)
    await db.flush()
    row = await _create_version_rows(db, pkg, manifest_dict, auth_context.user_id)
    await db.commit()
    await db.refresh(pkg)
    await telemetry.audit(db, organization_id=organization_id,
                          actor_user_id=auth_context.user_id,
                          action="package.import", resource_id=row.id,
                          metadata={"slug": slug})
    await telemetry.emit(db, event_type="PACKAGE_IMPORTED", aggregate_id=pkg.id,
                         organization_id=organization_id, user_id=auth_context.user_id,
                         payload={"slug": slug, "version": row.version})
    await db.commit()
    return {"package": _to_package_response(pkg).model_dump(mode="json"),
            "preview": preview}


class AssetUpload(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    mime: str = Field(min_length=1, max_length=127)
    size: int = Field(ge=0)


@router.post("/{package_id}/assets/validate",
             responses={400: {"model": ApiErrorResponse}, 401: {"model": ApiErrorResponse},
                        403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}})
async def validate_asset_upload(
    request: Request, organization_id: UUID, package_id: UUID, data: AssetUpload,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "package:update")
    await _get_package(db, organization_id, package_id)
    problems = validate_asset(data.filename, data.mime, data.size)
    return {"valid": not problems, "problems": problems}


# ---------------------------------------------------------------------------
# Skills
# ---------------------------------------------------------------------------

class SkillResponse(BaseModel):
    id: UUID
    organization_id: Optional[UUID] = None
    slug: str
    name: str
    description: str
    status: str
    trust: str
    visibility: str
    official: bool
    categories: list[str]
    tags: list[str]
    latest_version: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class SkillListResponse(PaginatedResponse[SkillResponse]):
    pass


class SkillVersionResponse(BaseModel):
    id: UUID
    skill_id: UUID
    version: str
    status: str
    instructions: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    required_tools: list[str]
    required_connectors: list[str]
    evaluation_criteria: list[str]
    content_hash: str
    created_at: datetime

    class Config:
        from_attributes = True


def _to_skill_response(skill) -> SkillResponse:
    return SkillResponse(
        id=skill.id, organization_id=skill.organization_id, slug=skill.slug,
        name=skill.name, description=skill.description, status=skill.status.value,
        trust=skill.trust.value, visibility=skill.visibility.value,
        official=skill.official, categories=skill.categories, tags=skill.tags,
        latest_version=skill.latest_version, created_at=skill.created_at,
        updated_at=skill.updated_at,
    )


async def _get_skill(db: AsyncSession, organization_id: UUID, skill_id: UUID):
    skill = await db.get(Skill, skill_id)
    if skill is None or skill.deleted_at is not None:
        raise _not_found("Skill")
    if skill.organization_id is not None and skill.organization_id != organization_id:
        raise _not_found("Skill")
    if skill.organization_id is None and skill.visibility not in (
        PackageVisibility.PUBLIC, PackageVisibility.UNLISTED,
    ):
        raise _not_found("Skill")
    return skill


def _validate_skill_payload(data: SkillCreate | SkillVersionCreate) -> list[dict[str, str]]:
    instructions = data.instructions if isinstance(data, SkillVersionCreate) else data.instructions
    findings = security_module.scan_text_blob(instructions or "", "instructions")
    for hit in config_schema.find_secret_values({
        "instructions": instructions,
        "input_schema": data.input_schema, "output_schema": data.output_schema,
    }):
        findings.append({"code": "SECRET_LEAK", "path": hit["path"],
                         "severity": "BLOCKER",
                         "message": f"SECRET_LEAK: {hit['reason']} at {hit['path']}"})
    return findings


@skills_router.get("", response_model=SkillListResponse,
                   responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}})
async def list_skills(
    request: Request, organization_id: UUID,
    search: Optional[str] = Query(None), official: Optional[bool] = Query(None),
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "skill:read")
    query = select(Skill).where(Skill.deleted_at.is_(None),
                                _visible_to_org(Skill, organization_id))
    count_q = select(func.count(Skill.id)).where(Skill.deleted_at.is_(None),
                                                 _visible_to_org(Skill, organization_id))
    if official is not None:
        query = query.where(Skill.official.is_(official))
        count_q = count_q.where(Skill.official.is_(official))
    if search:
        like = f"%{search}%"
        query = query.where(or_(Skill.name.ilike(like), Skill.slug.ilike(like),
                                Skill.description.ilike(like)))
        count_q = count_q.where(or_(Skill.name.ilike(like), Skill.slug.ilike(like),
                                    Skill.description.ilike(like)))
    total = (await db.execute(count_q)).scalar_one()
    rows = list((await db.execute(query.order_by(Skill.updated_at.desc())
                  .limit(page_size).offset((page - 1) * page_size))).scalars().all())
    return SkillListResponse(data=[_to_skill_response(r) for r in rows],
                             meta=create_pagination_meta(page, page_size, total))


@skills_router.post("", response_model=SkillResponse, status_code=status.HTTP_201_CREATED,
                    responses={400: {"model": ApiErrorResponse}, 401: {"model": ApiErrorResponse},
                               403: {"model": ApiErrorResponse}, 409: {"model": ApiErrorResponse}})
async def create_skill(
    request: Request, organization_id: UUID, data: SkillCreate,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "skill:create")
    from openagent.db.models.package import PackageVersionStatus as Status

    findings = _validate_skill_payload(data)
    blockers = [f for f in findings if f["severity"] in ("ERROR", "BLOCKER")]
    if blockers:
        raise HTTPException(status_code=400, detail={"error": blockers[0]["message"],
                                                     "code": blockers[0]["code"]})
    dup = (await db.execute(select(Skill).where(
        Skill.organization_id == organization_id, Skill.slug == data.slug,
        Skill.deleted_at.is_(None)))).scalar_one_or_none()
    if dup is not None:
        raise HTTPException(status_code=409, detail={"error": "Skill slug exists",
                                                     "code": "SKILL_EXISTS"})
    skill = Skill(
        organization_id=organization_id, slug=data.slug, name=data.name,
        description=data.description, status=Status.DRAFT,
        trust=PackageTrust.ORGANIZATION, visibility=PackageVisibility(data.visibility.upper()),
        official=False, owner_user_id=auth_context.user_id, latest_version="1.0.0",
    )
    db.add(skill)
    await db.flush()
    db.add(SkillVersion(
        skill_id=skill.id, version="1.0.0", status=Status.DRAFT,
        instructions=data.instructions, input_schema=data.input_schema,
        output_schema=data.output_schema, required_tools=data.required_tools,
        required_connectors=data.required_connectors,
        evaluation_criteria=data.evaluation_criteria,
        content_hash=signing.content_hash({"instructions": data.instructions}),
        created_by=auth_context.user_id,
    ))
    await db.commit()
    await db.refresh(skill)
    await telemetry.audit(db, organization_id=organization_id,
                          actor_user_id=auth_context.user_id,
                          action="skill.create", resource_id=skill.id,
                          metadata={"slug": skill.slug})
    await db.commit()
    return _to_skill_response(skill)


@skills_router.get("/{skill_id}", response_model=SkillResponse,
                   responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse},
                              404: {"model": ApiErrorResponse}})
async def get_skill(
    request: Request, organization_id: UUID, skill_id: UUID,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "skill:read")
    return _to_skill_response(await _get_skill(db, organization_id, skill_id))


@skills_router.post("/{skill_id}/versions", response_model=SkillVersionResponse,
                    status_code=status.HTTP_201_CREATED,
                    responses={400: {"model": ApiErrorResponse}, 401: {"model": ApiErrorResponse},
                               403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse},
                               409: {"model": ApiErrorResponse}})
async def create_skill_version(
    request: Request, organization_id: UUID, skill_id: UUID, data: SkillVersionCreate,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "skill:update")
    from openagent.db.models.package import PackageVersionStatus as Status

    skill = await _get_skill(db, organization_id, skill_id)
    if not is_valid_version(data.version):
        raise HTTPException(status_code=400, detail={"error": "Invalid version",
                                                     "code": "BAD_VERSION"})
    dup = (await db.execute(select(SkillVersion).where(
        SkillVersion.skill_id == skill.id,
        SkillVersion.version == data.version.lstrip("v")))).scalar_one_or_none()
    if dup is not None:
        raise HTTPException(status_code=409, detail={"error": "Version exists",
                                                     "code": "VERSION_EXISTS"})
    findings = _validate_skill_payload(data)
    blockers = [f for f in findings if f["severity"] in ("ERROR", "BLOCKER")]
    if blockers:
        raise HTTPException(status_code=400, detail={"error": blockers[0]["message"],
                                                     "code": blockers[0]["code"]})
    row = SkillVersion(
        skill_id=skill.id, version=data.version.lstrip("v"), status=Status.DRAFT,
        instructions=data.instructions, input_schema=data.input_schema,
        output_schema=data.output_schema, required_tools=data.required_tools,
        required_connectors=data.required_connectors,
        model_requirements=data.model_requirements,
        memory_requirements=data.memory_requirements,
        evaluation_criteria=data.evaluation_criteria,
        content_hash=signing.content_hash({"instructions": data.instructions}),
        created_by=auth_context.user_id,
    )
    db.add(row)
    await db.flush()
    skill.latest_version = row.version
    await db.commit()
    await db.refresh(row)
    return SkillVersionResponse(
        id=row.id, skill_id=row.skill_id, version=row.version,
        status=row.status.value, instructions=row.instructions,
        input_schema=row.input_schema, output_schema=row.output_schema,
        required_tools=row.required_tools, required_connectors=row.required_connectors,
        evaluation_criteria=row.evaluation_criteria, content_hash=row.content_hash,
        created_at=row.created_at,
    )


@skills_router.post("/{skill_id}/versions/{version}/publish",
                    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse},
                               404: {"model": ApiErrorResponse}, 409: {"model": ApiErrorResponse}})
async def publish_skill_version(
    request: Request, organization_id: UUID, skill_id: UUID, version: str,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "skill:update")
    from openagent.db.models.package import PackageVersionStatus as Status

    skill = await _get_skill(db, organization_id, skill_id)
    row = (await db.execute(select(SkillVersion).where(
        SkillVersion.skill_id == skill.id,
        SkillVersion.version == version))).scalar_one_or_none()
    if row is None:
        raise _not_found("Skill version")
    findings = _validate_skill_payload(SkillVersionCreate(
        version=row.version, instructions=row.instructions,
        input_schema=row.input_schema, output_schema=row.output_schema,
        required_tools=row.required_tools, required_connectors=row.required_connectors,
        evaluation_criteria=row.evaluation_criteria))
    blockers = [f for f in findings if f["severity"] in ("ERROR", "BLOCKER")]
    if blockers:
        raise HTTPException(status_code=400, detail={"error": blockers[0]["message"],
                                                     "code": blockers[0]["code"]})
    if row.status == Status.PUBLISHED:
        pass
    elif row.status == Status.DRAFT:
        row.status = Status.PUBLISHED
        row.published_at = datetime.now(timezone.utc)
    else:
        raise HTTPException(status_code=409, detail={
            "error": f"Cannot publish from {row.status.value}", "code": "BAD_STATE"})
    await db.commit()
    return {"id": str(row.id), "status": row.status.value, "version": row.version}


@skills_router.post("/{skill_id}/validate",
                    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse},
                               404: {"model": ApiErrorResponse}})
async def validate_skill(
    request: Request, organization_id: UUID, skill_id: UUID,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "skill:read")
    skill = await _get_skill(db, organization_id, skill_id)
    latest = (await db.execute(select(SkillVersion).where(
        SkillVersion.skill_id == skill.id,
        SkillVersion.version == skill.latest_version))).scalar_one_or_none()
    payload = {
        "instructions": latest.instructions if latest else "",
        "input_schema": latest.input_schema if latest else {},
        "required_tools": latest.required_tools if latest else [],
    }
    findings = security_module.scan_text_blob(payload["instructions"], "instructions")
    for hit in config_schema.find_secret_values(payload):
        findings.append({"code": "SECRET_LEAK", "path": hit["path"],
                         "severity": "BLOCKER", "message": hit["reason"]})
    return {"passed": not any(f["severity"] in ("ERROR", "BLOCKER") for f in findings),
            "findings": findings}


@skills_router.post("/{skill_id}/attach",
                    responses={400: {"model": ApiErrorResponse}, 401: {"model": ApiErrorResponse},
                               403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}})
async def attach_skill(
    request: Request, organization_id: UUID, skill_id: UUID, data: SkillAttachRequest,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Attach a published skill to an agent or workflow.

    Creates a new *draft* version of the target with the skill appended to
    its skill list — the original version is never mutated. Skill
    requirements (tools/connectors) are checked against ToolPolicy denials;
    conflicts fail closed.
    """
    await _need(request, db, "skill:read")
    from openagent.db.models.tool import ToolPolicy

    skill = await _get_skill(db, organization_id, skill_id)
    latest = (await db.execute(select(SkillVersion).where(
        SkillVersion.skill_id == skill.id,
        SkillVersion.version == skill.latest_version))).scalar_one_or_none()
    if latest is None or latest.status.value != "PUBLISHED":
        raise HTTPException(status_code=409, detail={
            "error": "Only published skills can be attached", "code": "NOT_PUBLISHED"})
    try:
        policies = (await db.execute(select(ToolPolicy))).scalars().all()
        blocked = {t for p in policies for t in (getattr(p, "blocked_tools", []) or [])}
    except Exception:
        blocked = set()
    conflicts = sorted(set(latest.required_tools or []) & blocked)
    if conflicts:
        raise HTTPException(status_code=409, detail={
            "error": f"Skill requires tools blocked by policy: {conflicts}",
            "code": "POLICY_CONFLICT"})
    if data.target_type == "agent":
        await _need(request, db, "agent:update")
        from openagent.db.models.agent import Agent, AgentVersion

        target = await db.get(Agent, data.target_id)
        if target is None or target.organization_id != organization_id:
            raise _not_found("Agent")
        current = (await db.execute(select(AgentVersion).where(
            AgentVersion.agent_id == target.id).order_by(
            AgentVersion.created_at.desc()))).scalars().first()
        base_config = dict((current.configuration if current else {}) or {})
        skills = list(base_config.get("skills", []) or [])
        if skill.slug not in skills:
            skills.append(skill.slug)
        base_config["skills"] = skills
        new_version = f"{(current.version if current else '1.0')}-with-{skill.slug}"[:50]
        db.add(AgentVersion(
            agent_id=target.id, version=new_version, name=target.name,
            instructions=current.instructions if current else None,
            configuration=base_config, status="draft",
            created_by=auth_context.user_id,
        ))
        ref = {"target": "agent", "id": str(target.id), "version": new_version}
    else:
        await _need(request, db, "workflow:update")
        from openagent.db.models.workflow import Workflow, WorkflowVersion

        target = await db.get(Workflow, data.target_id)
        if target is None or target.organization_id != organization_id:
            raise _not_found("Workflow")
        current = (await db.execute(select(WorkflowVersion).where(
            WorkflowVersion.workflow_id == target.id).order_by(
            WorkflowVersion.created_at.desc()))).scalars().first()
        definition = dict((current.definition if current else {}) or {})
        skills = list(definition.get("skills", []) or [])
        if skill.slug not in skills:
            skills.append(skill.slug)
        definition["skills"] = skills
        new_version = f"{(current.version if current else '1.0')}-with-{skill.slug}"[:50]
        db.add(WorkflowVersion(
            workflow_id=target.id, version=new_version, definition=definition,
            status="draft", created_by=auth_context.user_id,
        ))
        ref = {"target": "workflow", "id": str(target.id), "version": new_version}
    telemetry.inc("skill_usage_total")
    await telemetry.audit(db, organization_id=organization_id,
                          actor_user_id=auth_context.user_id,
                          action="skill.attach", resource_id=skill.id,
                          metadata={"skill": skill.slug, **ref})
    await db.commit()
    return {"skill": skill.slug, **ref}


# ---------------------------------------------------------------------------
# Presets
# ---------------------------------------------------------------------------

class PresetResponse(BaseModel):
    id: UUID
    organization_id: Optional[UUID] = None
    slug: str
    name: str
    kind: str
    description: str
    visibility: str
    official: bool
    latest_version: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class PresetListResponse(PaginatedResponse[PresetResponse]):
    pass


def _to_preset_response(preset) -> PresetResponse:
    return PresetResponse(
        id=preset.id, organization_id=preset.organization_id, slug=preset.slug,
        name=preset.name, kind=preset.kind.value, description=preset.description,
        visibility=preset.visibility.value, official=preset.official,
        latest_version=preset.latest_version, created_at=preset.created_at,
        updated_at=preset.updated_at,
    )


async def _get_preset(db: AsyncSession, organization_id: UUID, preset_id: UUID):
    preset = await db.get(Preset, preset_id)
    if preset is None or preset.deleted_at is not None:
        raise _not_found("Preset")
    if preset.organization_id is not None and preset.organization_id != organization_id:
        raise _not_found("Preset")
    if preset.organization_id is None and preset.visibility not in (
        PackageVisibility.PUBLIC, PackageVisibility.UNLISTED,
    ):
        raise _not_found("Preset")
    return preset


def _validate_preset_payload(kind: str, payload: dict[str, Any]) -> list[str]:
    """Structural preset checks. Model routing always happens in Model Router.

    Presets store *hints* (strategy, capabilities, budgets) — never provider
    credentials or direct model handles.
    """
    problems: list[str] = []
    if not isinstance(payload, dict) or not payload:
        return ["preset payload must be a non-empty object"]
    leaks = config_schema.find_secret_values(payload)
    if leaks:
        problems.append(f"preset payload must not contain secrets ({leaks[0]['path']})")
    if kind == "MODEL_PRESET":
        allowed = {"strategy", "preferred_provider", "required_capabilities",
                   "minimum_context_window", "reasoning_required", "vision_required",
                   "coding_required", "budget", "fallback", "description"}
        unknown = set(payload) - allowed
        if unknown:
            problems.append(f"unknown model preset keys: {sorted(unknown)}")
    elif kind == "MEMORY_PRESET":
        allowed = {"memory_mode", "memory_scopes", "retention", "retrieval_policy",
                   "write_policy", "description"}
        unknown = set(payload) - allowed
        if unknown:
            problems.append(f"unknown memory preset keys: {sorted(unknown)}")
    return problems


@presets_router.get("", response_model=PresetListResponse,
                    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}})
async def list_presets(
    request: Request, organization_id: UUID,
    kind: Optional[str] = Query(None), search: Optional[str] = Query(None),
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "preset:read")
    query = select(Preset).where(Preset.deleted_at.is_(None),
                                 _visible_to_org(Preset, organization_id))
    count_q = select(func.count(Preset.id)).where(Preset.deleted_at.is_(None),
                                                  _visible_to_org(Preset, organization_id))
    if kind:
        query = query.where(Preset.kind == kind.upper())
        count_q = count_q.where(Preset.kind == kind.upper())
    if search:
        like = f"%{search}%"
        query = query.where(or_(Preset.name.ilike(like), Preset.slug.ilike(like)))
        count_q = count_q.where(or_(Preset.name.ilike(like), Preset.slug.ilike(like)))
    total = (await db.execute(count_q)).scalar_one()
    rows = list((await db.execute(query.order_by(Preset.updated_at.desc())
                  .limit(page_size).offset((page - 1) * page_size))).scalars().all())
    return PresetListResponse(data=[_to_preset_response(r) for r in rows],
                              meta=create_pagination_meta(page, page_size, total))


@presets_router.post("", response_model=PresetResponse, status_code=status.HTTP_201_CREATED,
                     responses={400: {"model": ApiErrorResponse}, 401: {"model": ApiErrorResponse},
                                403: {"model": ApiErrorResponse}, 409: {"model": ApiErrorResponse}})
async def create_preset(
    request: Request, organization_id: UUID, data: PresetCreate,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "preset:create")
    from openagent.db.models.package import PresetKind, PackageVersionStatus as Status

    problems = _validate_preset_payload(data.kind, data.payload)
    if problems:
        raise HTTPException(status_code=400, detail={"error": problems[0],
                                                     "code": "BAD_PRESET"})
    dup = (await db.execute(select(Preset).where(
        Preset.organization_id == organization_id, Preset.slug == data.slug,
        Preset.deleted_at.is_(None)))).scalar_one_or_none()
    if dup is not None:
        raise HTTPException(status_code=409, detail={"error": "Preset slug exists",
                                                     "code": "PRESET_EXISTS"})
    preset = Preset(
        organization_id=organization_id, slug=data.slug, name=data.name,
        kind=PresetKind(data.kind), description=data.description,
        visibility=PackageVisibility(data.visibility.upper()), official=False,
        latest_version="1.0.0",
    )
    db.add(preset)
    await db.flush()
    db.add(PresetVersion(
        preset_id=preset.id, version="1.0.0", status=Status.DRAFT,
        payload=data.payload,
        content_hash=signing.content_hash(data.payload),
        created_by=auth_context.user_id,
    ))
    await db.commit()
    await db.refresh(preset)
    await telemetry.audit(db, organization_id=organization_id,
                          actor_user_id=auth_context.user_id,
                          action="preset.create", resource_id=preset.id,
                          metadata={"slug": preset.slug, "kind": data.kind})
    await db.commit()
    return _to_preset_response(preset)


@presets_router.get("/{preset_id}", response_model=PresetResponse,
                    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse},
                               404: {"model": ApiErrorResponse}})
async def get_preset(
    request: Request, organization_id: UUID, preset_id: UUID,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "preset:read")
    return _to_preset_response(await _get_preset(db, organization_id, preset_id))


@presets_router.post("/{preset_id}/versions",
                     responses={400: {"model": ApiErrorResponse}, 401: {"model": ApiErrorResponse},
                                403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse},
                                409: {"model": ApiErrorResponse}})
async def create_preset_version(
    request: Request, organization_id: UUID, preset_id: UUID, data: PresetVersionCreate,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "preset:update")
    from openagent.db.models.package import PackageVersionStatus as Status

    preset = await _get_preset(db, organization_id, preset_id)
    if not is_valid_version(data.version):
        raise HTTPException(status_code=400, detail={"error": "Invalid version",
                                                     "code": "BAD_VERSION"})
    problems = _validate_preset_payload(preset.kind.value, data.payload)
    if problems:
        raise HTTPException(status_code=400, detail={"error": problems[0],
                                                     "code": "BAD_PRESET"})
    dup = (await db.execute(select(PresetVersion).where(
        PresetVersion.preset_id == preset.id,
        PresetVersion.version == data.version.lstrip("v")))).scalar_one_or_none()
    if dup is not None:
        raise HTTPException(status_code=409, detail={"error": "Version exists",
                                                     "code": "VERSION_EXISTS"})
    row = PresetVersion(
        preset_id=preset.id, version=data.version.lstrip("v"), status=Status.DRAFT,
        payload=data.payload, content_hash=signing.content_hash(data.payload),
        created_by=auth_context.user_id,
    )
    db.add(row)
    await db.flush()
    preset.latest_version = row.version
    await db.commit()
    await db.refresh(row)
    return {"id": str(row.id), "version": row.version, "status": row.status.value}


@presets_router.post("/{preset_id}/versions/{version}/publish",
                     responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse},
                                404: {"model": ApiErrorResponse}, 409: {"model": ApiErrorResponse}})
async def publish_preset_version(
    request: Request, organization_id: UUID, preset_id: UUID, version: str,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "preset:update")
    from openagent.db.models.package import PackageVersionStatus as Status

    preset = await _get_preset(db, organization_id, preset_id)
    row = (await db.execute(select(PresetVersion).where(
        PresetVersion.preset_id == preset.id,
        PresetVersion.version == version))).scalar_one_or_none()
    if row is None:
        raise _not_found("Preset version")
    problems = _validate_preset_payload(preset.kind.value, dict(row.payload or {}))
    if problems:
        raise HTTPException(status_code=400, detail={"error": problems[0],
                                                     "code": "BAD_PRESET"})
    if row.status != Status.PUBLISHED:
        if row.status != Status.DRAFT:
            raise HTTPException(status_code=409, detail={
                "error": f"Cannot publish from {row.status.value}", "code": "BAD_STATE"})
        row.status = Status.PUBLISHED
        row.published_at = datetime.now(timezone.utc)
        await db.commit()
    return {"id": str(row.id), "version": row.version, "status": row.status.value}


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------

@catalog_router.get("/search",
                    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse},
                               429: {"model": ApiErrorResponse}})
async def catalog_search(
    request: Request, organization_id: UUID,
    q: str = Query(""), categories: str = Query(""), tags: str = Query(""),
    types: str = Query(""), trust: str = Query(""), official_only: bool = Query(False),
    installed_only: bool = Query(False), max_risk: str = Query(""),
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "package:read")
    await _rate_limited(request, "search", 120, 60)
    from openagent.db.models.package import PackageInstallation, PackageVersion

    pkgs = list((await db.execute(select(ReusablePackage).where(
        ReusablePackage.deleted_at.is_(None),
        _visible_to_org(ReusablePackage, organization_id)).limit(500))).scalars().all())
    installed_ids = {
        row[0] for row in (await db.execute(select(PackageInstallation.package_id).where(
            PackageInstallation.organization_id == organization_id,
            PackageInstallation.status == PackageInstallStatus.INSTALLED))).all()
    }
    entries: list[catalog_module.CatalogEntry] = []
    for pkg in pkgs:
        latest = None
        if pkg.latest_version:
            latest = (await db.execute(select(PackageVersion).where(
                PackageVersion.package_id == pkg.id,
                PackageVersion.version == pkg.latest_version))).scalar_one_or_none()
        entries.append(catalog_module.CatalogEntry(
            package_id=str(pkg.id), slug=pkg.slug, name=pkg.name,
            description=pkg.description, type=pkg.package_type.value,
            version=pkg.latest_version, trust=pkg.trust.value,
            visibility=pkg.visibility.value, official=pkg.official,
            categories=list(pkg.categories or []), tags=list(pkg.tags or []),
            author=pkg.author_name or pkg.publisher, risk=latest.risk if latest else "LOW",
            installed=pkg.id in installed_ids,
            updated_at=pkg.updated_at.isoformat(),
        ))
    query = catalog_module.CatalogQuery(
        text=q,
        categories=[c for c in categories.split(",") if c],
        tags=[t for t in tags.split(",") if t],
        types=[t for t in types.split(",") if t],
        trust=[t for t in trust.split(",") if t],
        security_max_risk=max_risk, official_only=official_only,
        installed_only=installed_only, page=page, page_size=page_size,
    )
    provider = catalog_module.InMemoryCatalogProvider(entries)
    matches, total = provider.search(query)
    return {"data": [e.__dict__ for e in matches],
            "meta": create_pagination_meta(page, page_size, total).model_dump(),
            "provider": provider.name}


@catalog_router.get("/categories",
                    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}})
async def catalog_categories(
    request: Request, organization_id: UUID,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "package:read")
    from openagent.db.models.package import PackageCategory

    rows = list((await db.execute(select(PackageCategory).where(or_(
        PackageCategory.organization_id == organization_id,
        PackageCategory.organization_id.is_(None))))).scalars().all())
    if not rows:
        return {"data": [{"slug": c.lower().replace(" & ", "-").replace(" ", "-"),
                          "name": c, "official": True} for c in STANDARD_CATEGORIES]}
    return {"data": [{"slug": r.slug, "name": r.name, "official": r.official,
                      "description": r.description} for r in rows]}


# ---------------------------------------------------------------------------
# Installations
# ---------------------------------------------------------------------------

@installations_router.get("",
                          responses={401: {"model": ApiErrorResponse},
                                     403: {"model": ApiErrorResponse}})
async def list_installations(
    request: Request, organization_id: UUID,
    status_filter: Optional[str] = Query(None),
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "package:read")
    query = select(PackageInstallation).where(
        PackageInstallation.organization_id == organization_id)
    count_q = select(func.count(PackageInstallation.id)).where(
        PackageInstallation.organization_id == organization_id)
    if status_filter:
        try:
            wanted = PackageInstallStatus(status_filter.upper())
        except ValueError:
            raise HTTPException(status_code=400, detail={
                "error": f"Unknown installation status {status_filter!r}",
                "code": "BAD_STATUS"})
        query = query.where(PackageInstallation.status == wanted)
        count_q = count_q.where(PackageInstallation.status == wanted)
    total = (await db.execute(count_q)).scalar_one()
    rows = list((await db.execute(query.order_by(
        PackageInstallation.updated_at.desc()).limit(page_size).offset(
        (page - 1) * page_size))).scalars().all())
    data = []
    for inst in rows:
        pkg = await db.get(ReusablePackage, inst.package_id)
        ver = await db.get(PackageVersion, inst.version_id)
        data.append({
            "id": str(inst.id), "package_id": str(inst.package_id),
            "package_slug": pkg.slug if pkg else "",
            "package_name": pkg.name if pkg else "",
            "version": ver.version if ver else "",
            "version_id": str(inst.version_id),
            "status": inst.status.value,
            "trust": pkg.trust.value if pkg else "UNTRUSTED",
            "official": pkg.official if pkg else False,
            "update_available": inst.update_available,
            "error": inst.error,
            "installed_at": inst.installed_at.isoformat() if inst.installed_at else None,
            "updated_at": inst.updated_at.isoformat(),
        })
    return {"data": data, "meta": create_pagination_meta(page, page_size, total).model_dump()}


@installations_router.get("/{installation_id}",
                          responses={401: {"model": ApiErrorResponse},
                                     403: {"model": ApiErrorResponse},
                                     404: {"model": ApiErrorResponse}})
async def get_installation(
    request: Request, organization_id: UUID, installation_id: UUID,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "package:read")
    from openagent.db.models.package import PackageInstallation

    inst = await db.get(PackageInstallation, installation_id)
    if inst is None or inst.organization_id != organization_id:
        raise _not_found("Installation")
    pkg = await db.get(ReusablePackage, inst.package_id)
    ver = await db.get(PackageVersion, inst.version_id)
    resources = list((await db.execute(select(InstallationResource).where(
        InstallationResource.installation_id == inst.id))).scalars().all())
    findings = security_module.scan_manifest_dict(dict(ver.manifest or {}) if ver else {})
    return {
        "id": str(inst.id), "package_id": str(inst.package_id),
        "package_slug": pkg.slug if pkg else "",
        "package_name": pkg.name if pkg else "",
        "version": ver.version if ver else "", "status": inst.status.value,
        "configuration": inst.configuration,
        "resolved_dependencies": inst.resolved_dependencies,
        "update_available": inst.update_available, "error": inst.error,
        "resources": [{"kind": r.kind, "slug": r.slug, "name": r.name,
                       "local_ref_type": r.local_ref_type,
                       "local_ref_id": r.local_ref_id} for r in resources],
        "security": {"risk": security_module.risk_level(findings),
                     "findings": findings},
    }


@installations_router.post("/{installation_id}/update-plan",
                           responses={400: {"model": ApiErrorResponse},
                                      401: {"model": ApiErrorResponse},
                                      403: {"model": ApiErrorResponse},
                                      404: {"model": ApiErrorResponse},
                                      409: {"model": ApiErrorResponse}})
async def create_update_plan(
    request: Request, organization_id: UUID, installation_id: UUID, data: UpdatePlanRequest,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "package:execute")
    from openagent.db.models.package import PackageInstallation

    inst = await db.get(PackageInstallation, installation_id)
    if inst is None or inst.organization_id != organization_id:
        raise _not_found("Installation")
    target = (await db.execute(select(PackageVersion).where(
        PackageVersion.package_id == inst.package_id,
        PackageVersion.version == data.to_version))).scalar_one_or_none()
    if target is None:
        raise _not_found("Package version")
    try:
        plan = await installer.plan_update(
            db, installation_id=inst.id, to_version_id=target.id,
            organization_id=organization_id)
    except installer.InstallationError as exc:
        raise HTTPException(status_code=409, detail={"error": str(exc), "code": exc.code})
    return {"id": str(plan.id), "status": plan.status, "breaking": plan.breaking,
            "impact": plan.impact, "migration_steps": plan.migration_steps}


@installations_router.post("/{installation_id}/update",
                           responses={400: {"model": ApiErrorResponse},
                                      401: {"model": ApiErrorResponse},
                                      403: {"model": ApiErrorResponse},
                                      404: {"model": ApiErrorResponse},
                                      409: {"model": ApiErrorResponse}})
async def apply_installation_update(
    request: Request, organization_id: UUID, installation_id: UUID,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "package:execute")
    from openagent.db.models.package import PackageInstallation

    inst = await db.get(PackageInstallation, installation_id)
    if inst is None or inst.organization_id != organization_id:
        raise _not_found("Installation")
    try:
        updated = await installer.apply_update(
            db, installation_id=inst.id, organization_id=organization_id,
            approved_by=auth_context.user_id)
    except installer.InstallationError as exc:
        raise HTTPException(status_code=409, detail={"error": str(exc), "code": exc.code})
    return {"id": str(updated.id), "status": updated.status.value,
            "version_id": str(updated.version_id)}


@installations_router.post("/{installation_id}/rollback",
                           responses={400: {"model": ApiErrorResponse},
                                      401: {"model": ApiErrorResponse},
                                      403: {"model": ApiErrorResponse},
                                      404: {"model": ApiErrorResponse},
                                      409: {"model": ApiErrorResponse}})
async def rollback_installation(
    request: Request, organization_id: UUID, installation_id: UUID,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "package:execute")
    from openagent.db.models.package import PackageInstallation

    inst = await db.get(PackageInstallation, installation_id)
    if inst is None or inst.organization_id != organization_id:
        raise _not_found("Installation")
    try:
        rolled = await installer.rollback(
            db, installation_id=inst.id, organization_id=organization_id,
            actor=auth_context.user_id)
    except installer.InstallationError as exc:
        raise HTTPException(status_code=409, detail={"error": str(exc), "code": exc.code})
    return {"id": str(rolled.id), "status": rolled.status.value,
            "version_id": str(rolled.version_id)}


@installations_router.delete("/{installation_id}", status_code=status.HTTP_204_NO_CONTENT,
                             responses={401: {"model": ApiErrorResponse},
                                        403: {"model": ApiErrorResponse},
                                        404: {"model": ApiErrorResponse}})
async def uninstall_package(
    request: Request, organization_id: UUID, installation_id: UUID,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Uninstall: mark UNINSTALLED and soft-delete rows this install created."""
    await _need(request, db, "package:execute")
    from datetime import datetime as _dt

    from openagent.db.models.agent import Agent
    from openagent.db.models.package import PackageInstallation, Preset, Skill
    from openagent.db.models.workflow import Workflow

    inst = await db.get(PackageInstallation, installation_id)
    if inst is None or inst.organization_id != organization_id:
        raise _not_found("Installation")
    resources = list((await db.execute(select(InstallationResource).where(
        InstallationResource.installation_id == inst.id))).scalars().all())
    for record in resources:
        if not record.local_ref_id:
            continue
        try:
            ref = UUID(record.local_ref_id)
        except ValueError:
            continue
        if record.local_ref_type == "agent":
            row = await db.get(Agent, ref)
            if row is not None and (row.metadata or {}).get("installed_from") == str(inst.id):
                row.deleted_at = _dt.now(timezone.utc)
        elif record.local_ref_type == "workflow":
            row = await db.get(Workflow, ref)
            if row is not None and (row.metadata or {}).get("installed_from") == str(inst.id):
                row.deleted_at = _dt.now(timezone.utc)
        elif record.local_ref_type == "skill":
            row = await db.get(Skill, ref)
            if row is not None and row.organization_id == organization_id:
                row.deleted_at = _dt.now(timezone.utc)
        elif record.local_ref_type == "preset":
            row = await db.get(Preset, ref)
            if row is not None and row.organization_id == organization_id:
                row.deleted_at = _dt.now(timezone.utc)
    inst.status = PackageInstallStatus.UNINSTALLED
    await db.commit()
    await telemetry.audit(db, organization_id=organization_id,
                          actor_user_id=auth_context.user_id,
                          action="package.uninstall", resource_id=inst.id)
    await db.commit()

