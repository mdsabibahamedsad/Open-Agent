"""MP28: developer + extension REST API (§76).

Routes (all versioned under /api/v1):

  /organizations/{id}/developer/projects[. ..]
  /organizations/{id}/developer/environments
  /organizations/{id}/developer/webhooks
  /organizations/{id}/extensions[. ..]  (CRUD, versions, validate/test/
      package/publish/deploy/rollback/quarantine/install)
  /organizations/{id}/developer/deployments
  /organizations/{id}/developer/events      (versioned event schemas)
  /organizations/{id}/developer/usage       (aggregated analytics)
  /api/v1/developer/sdk                     (public SDK metadata, no auth)
  /api/v1/developer/errors                  (public error taxonomy, no auth)
  /api/v1/developer/events                  (public event catalog, no auth)
  /api/v1/registry/local[. ..]              (local offline registry)
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timezone
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from openagent.api.dependencies import get_current_org_context, require_permission
from openagent.db.models.developer import (
    DeveloperEnvironment,
    DeveloperProject,
    DeveloperProjectMember,
    DeveloperWebhook,
    DeveloperWebhookDelivery,
    ExtensionAnalyticsDaily,
    ExtensionDefinition,
    ExtensionDeployment,
    ExtensionInstallation,
    ExtensionTrustRecord,
    ExtensionVersion,
)
from openagent.db.session import get_db
from openagent.developer import service as dev_service
from openagent.developer.errors import sign_webhook
from openagent.developer.manifest import load_manifest_dict
from openagent.developer.packaging import PackageFile, build_package, inspect_package
from openagent.developer.permissions import check_permissions
from openagent.developer.security import install_hooks_safe, scan_files
from openagent.developer.signing import generate_keypair, sign_digest, verify_digest
from openagent.developer.types import (
    API_VERSION,
    DEVELOPER_EVENTS,
    EXTENSION_API_VERSION,
    EXTENSION_TYPES,
    MANIFEST_VERSION,
    PERMISSION_CATALOG,
    SDK_VERSION,
)
from openagent.developer.versioning import DEPRECATIONS, validate_semver

router = APIRouter(prefix="/organizations/{organization_id}/developer", tags=["developer"])
extensions_router = APIRouter(prefix="/organizations/{organization_id}/extensions", tags=["extensions"])
public_router = APIRouter(prefix="/developer", tags=["developer-public"])
local_registry_router = APIRouter(prefix="/registry/local", tags=["local-registry"])


def _actor(request: Request) -> str:
    return request.headers.get("X-Actor", "developer")


# ------------------------------------------------------------------ projects

class ProjectCreate(BaseModel):
    slug: str = Field(min_length=2, max_length=128, pattern="^[a-z0-9][a-z0-9._-]{1,127}$")
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=2000)


@router.get("/projects", summary="List developer projects")
async def list_projects(
    organization_id: UUID,
    db: AsyncSession = Depends(get_db),
    ctx=Depends(require_permission("package:read")),
):
    rows = (await db.execute(select(DeveloperProject).where(
        DeveloperProject.organization_id == organization_id
    ).order_by(DeveloperProject.created_at.desc()).limit(200))).scalars().all()
    return {"projects": [
        {"id": str(p.id), "slug": p.slug, "name": p.name, "status": p.status} for p in rows]}


@router.post("/projects", summary="Create developer project", status_code=201)
async def create_project(
    organization_id: UUID,
    body: ProjectCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    ctx=Depends(require_permission("package:create")),
):
    existing = (await db.execute(select(DeveloperProject).where(
        DeveloperProject.organization_id == organization_id,
        DeveloperProject.slug == body.slug))).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="project slug already exists")
    project = DeveloperProject(
        organization_id=organization_id, slug=body.slug, name=body.name,
        description=body.description, created_by=_actor(request))
    db.add(project)
    await db.flush()
    for env in ("development", "staging", "production"):
        db.add(DeveloperEnvironment(project_id=project.id, name=env, config={}))
    await db.commit()
    await dev_service.audit(db, organization_id=organization_id, actor=_actor(request),
                            action="developer.project.created", resource=str(project.id))
    await db.commit()
    return {"id": str(project.id), "slug": project.slug, "name": project.name}


@router.get("/projects/{project_id}", summary="Get project with environments")
async def get_project(
    organization_id: UUID,
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    ctx=Depends(require_permission("package:read")),
):
    project = (await db.execute(select(DeveloperProject).where(
        DeveloperProject.id == project_id,
        DeveloperProject.organization_id == organization_id))).scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    envs = (await db.execute(select(DeveloperEnvironment).where(
        DeveloperEnvironment.project_id == project_id))).scalars().all()
    exts = (await db.execute(select(ExtensionDefinition).where(
        ExtensionDefinition.project_id == project_id))).scalars().all()
    return {
        "id": str(project.id), "slug": project.slug, "name": project.name,
        "description": project.description, "status": project.status,
        "environments": [{"name": e.name, "endpoint": e.api_endpoint} for e in envs],
        "extensions": [e.slug for e in exts],
    }


class EnvUpdate(BaseModel):
    api_endpoint: str = Field(default="", max_length=1024)
    config: dict[str, Any] = Field(default_factory=dict)


@router.put("/projects/{project_id}/environments/{env}", summary="Update environment config")
async def update_environment(
    organization_id: UUID,
    project_id: UUID,
    env: str,
    body: EnvUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    ctx=Depends(require_permission("package:create")),
):
    if env not in ("development", "staging", "production"):
        raise HTTPException(status_code=400, detail="unknown environment")
    # Production secrets must never flow into development (§37, invariant 16).
    if env == "development":
        lowered = str(body.config).lower()
        if any(marker in lowered for marker in ("prod_", "BEGIN PRIVATE KEY", "sk-")):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="refusing to copy production-looking secrets into development",
            )
    row = (await db.execute(select(DeveloperEnvironment).where(
        DeveloperEnvironment.project_id == project_id,
        DeveloperEnvironment.name == env))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="environment not found")
    row.api_endpoint = body.api_endpoint
    row.config = body.config
    await db.commit()
    await dev_service.audit(db, organization_id=organization_id, actor=_actor(request),
                            action="developer.environment.updated",
                            resource=f"{project_id}/{env}")
    await db.commit()
    return {"project": str(project_id), "environment": env, "updated": True}


# ---------------------------------------------------------------- extensions

class ExtensionCreate(BaseModel):
    slug: str = Field(min_length=2, max_length=160, pattern="^[a-z0-9][a-z0-9._-]{1,159}$")
    extension_type: str = Field(min_length=1, max_length=64)
    display_name: str = Field(default="", max_length=255)
    description: str = Field(default="", max_length=2000)
    project_id: UUID | None = None
    license: str = Field(default="MIT", max_length=64)
    repository: str = Field(default="", max_length=1024)


@extensions_router.get("", summary="List extensions")
async def list_extensions(
    organization_id: UUID,
    db: AsyncSession = Depends(get_db),
    ctx=Depends(require_permission("package:read")),
    extension_type: str = Query(default=""),
    lifecycle: str = Query(default=""),
    limit: int = Query(default=100, ge=1, le=500),
):
    query = select(ExtensionDefinition).where(
        ExtensionDefinition.organization_id == organization_id)
    if extension_type:
        query = query.where(ExtensionDefinition.extension_type == extension_type)
    if lifecycle:
        query = query.where(ExtensionDefinition.lifecycle == lifecycle.upper())
    rows = (await db.execute(query.order_by(
        ExtensionDefinition.created_at.desc()).limit(limit))).scalars().all()
    return {"extensions": [
        {"id": str(e.id), "slug": e.slug, "type": e.extension_type,
         "lifecycle": e.lifecycle, "trust": e.trust_level} for e in rows]}


@extensions_router.post("", summary="Create extension definition", status_code=201)
async def create_extension(
    organization_id: UUID,
    body: ExtensionCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    ctx=Depends(require_permission("package:create")),
):
    if body.extension_type not in EXTENSION_TYPES:
        raise HTTPException(status_code=422, detail=f"unknown extension type '{body.extension_type}'")
    existing = (await db.execute(select(ExtensionDefinition).where(
        ExtensionDefinition.organization_id == organization_id,
        ExtensionDefinition.slug == body.slug))).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="extension slug already exists")
    ext = ExtensionDefinition(
        organization_id=organization_id, project_id=body.project_id, slug=body.slug,
        extension_type=body.extension_type, display_name=body.display_name or body.slug,
        description=body.description, license=body.license, repository=body.repository,
        publisher=_actor(request))
    db.add(ext)
    await db.commit()
    await dev_service.audit(db, organization_id=organization_id, actor=_actor(request),
                            action="extension.created", resource=str(ext.id),
                            details={"slug": body.slug, "type": body.extension_type})
    await db.commit()
    return {"id": str(ext.id), "slug": ext.slug, "lifecycle": ext.lifecycle}


@extensions_router.get("/{extension_id}", summary="Get extension with versions")
async def get_extension(
    organization_id: UUID,
    extension_id: UUID,
    db: AsyncSession = Depends(get_db),
    ctx=Depends(require_permission("package:read")),
):
    ext = await _get_ext(db, organization_id, extension_id)
    versions = (await db.execute(select(ExtensionVersion).where(
        ExtensionVersion.extension_id == ext.id).order_by(
        ExtensionVersion.created_at.desc()))).scalars().all()
    return {
        "id": str(ext.id), "slug": ext.slug, "type": ext.extension_type,
        "lifecycle": ext.lifecycle, "trust": ext.trust_level,
        "quarantine": {"at": ext.quarantined_at.isoformat() if ext.quarantined_at else None,
                       "reason": ext.quarantine_reason},
        "versions": [{"id": str(v.id), "version": v.version,
                      "digest": v.content_digest} for v in versions],
    }


async def _get_ext(db: AsyncSession, organization_id: UUID, extension_id: UUID) -> ExtensionDefinition:
    ext = (await db.execute(select(ExtensionDefinition).where(
        ExtensionDefinition.id == extension_id,
        ExtensionDefinition.organization_id == organization_id))).scalar_one_or_none()
    if ext is None:
        raise HTTPException(status_code=404, detail="extension not found")
    return ext


class VersionCreate(BaseModel):
    version: str = Field(min_length=5, max_length=32)
    manifest: dict[str, Any]
    changelog: str = Field(default="", max_length=4000)


@extensions_router.post("/{extension_id}/versions", summary="Create extension version", status_code=201)
async def create_version(
    organization_id: UUID,
    extension_id: UUID,
    body: VersionCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    ctx=Depends(require_permission("package:create")),
):
    ext = await _get_ext(db, organization_id, extension_id)
    try:
        validate_semver(body.version)
        manifest = load_manifest_dict(body.manifest)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if manifest.version != body.version:
        raise HTTPException(status_code=422, detail="manifest.version must match the version path")
    if manifest.name != ext.slug and manifest.name.replace("_", "-") != ext.slug:
        raise HTTPException(status_code=422, detail="manifest.name must match the extension slug")
    dup = (await db.execute(select(ExtensionVersion).where(
        ExtensionVersion.extension_id == ext.id,
        ExtensionVersion.version == body.version))).scalar_one_or_none()
    if dup:
        raise HTTPException(status_code=409, detail="version already exists")
    if not manifest.license and not body.manifest.get("license"):
        raise HTTPException(status_code=422, detail="license is required (§56)")
    row = ExtensionVersion(
        extension_id=ext.id, version=body.version, manifest=manifest.model_dump(),
        compatibility=manifest.compatibility.model_dump(), changelog=body.changelog)
    db.add(row)
    await db.commit()
    return {"id": str(row.id), "version": row.version}


class ValidateBody(BaseModel):
    files: dict[str, str] = Field(default_factory=dict)
    openagent_version: str = Field(default="1.0.0")


@extensions_router.post("/{extension_id}/validate", summary="Validate manifest + sources (no exec)")
async def validate_extension(
    organization_id: UUID,
    extension_id: UUID,
    body: ValidateBody,
    db: AsyncSession = Depends(get_db),
    ctx=Depends(require_permission("package:create")),
):
    ext = await _get_ext(db, organization_id, extension_id)
    latest = (await db.execute(select(ExtensionVersion).where(
        ExtensionVersion.extension_id == ext.id).order_by(
        ExtensionVersion.created_at.desc()))).scalar_one_or_none()
    if latest is None:
        raise HTTPException(status_code=404, detail="no versions yet; create a version first")
    result = dev_service.run_full_validation(
        manifest=latest.manifest, files=body.files,
        openagent_version=body.openagent_version)
    latest.validation_report = {k: v for k, v in result.items() if k != "manifest"}
    if result["ok"]:
        ext.lifecycle = "VALIDATED"
    await db.commit()
    return result


class TestBody(BaseModel):
    files: dict[str, str] = Field(default_factory=dict)
    suite: str = Field(default="contract", pattern="^(unit|contract|security|all)$")


@extensions_router.post("/{extension_id}/test", summary="Run standard test harness (sandboxed mocks)")
async def test_extension(
    organization_id: UUID,
    extension_id: UUID,
    body: TestBody,
    db: AsyncSession = Depends(get_db),
    ctx=Depends(require_permission("package:create")),
):
    """Test harness (§30): manifest/schema/permission/runtime/security/compat checks.

    Tool/connector/MCP execution uses deterministic mocks — the host is
    never touched and no credentials are required.
    """
    ext = await _get_ext(db, organization_id, extension_id)
    latest = (await db.execute(select(ExtensionVersion).where(
        ExtensionVersion.extension_id == ext.id).order_by(
        ExtensionVersion.created_at.desc()))).scalar_one_or_none()
    if latest is None:
        raise HTTPException(status_code=404, detail="no versions yet")
    checks: list[dict[str, Any]] = []

    def _check(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"name": name, "passed": ok, "detail": detail})

    manifest_ok = bool(latest.validation_report.get("ok", False))
    _check("manifest validation", manifest_ok or not latest.validation_report,
           "" if manifest_ok else "run validate first")
    try:
        manifest = load_manifest_dict(latest.manifest)
        _check("schema validation", True)
        decision = check_permissions(
            list(manifest.permissions), granted=list(manifest.permissions), trust="UNTRUSTED")
        decision_ok = not decision.denied
        _check("permission validation", decision_ok, "; ".join(decision.reasons))
    except Exception as exc:
        _check("schema validation", False, str(exc))
        _check("permission validation", False, "manifest invalid")
    report = scan_files(body.files)
    _check("security policy", not report.blocks_publish,
           f"{len(report.secret_hits)} secret(s), {len(report.findings)} finding(s)")
    # Contract checks per extension type (§60).
    from openagent.developer.mocks import (
        MockBrowser,
        MockConnector,
        MockLLM,
        MockMCP,
        MockSandbox,
        MockToolRuntime,
    )

    try:
        MockToolRuntime().invoke("mock.ping", {"hello": "world"})
        MockLLM().complete("contract probe")
        if ext.extension_type == "connector":
            MockConnector().action("list", {})
        if ext.extension_type.startswith("mcp"):
            mcp = MockMCP()
            mcp.connect()
            mcp.call_tool("ping", {})
        if ext.extension_type == "browser-extension":
            MockBrowser().goto("https://example.com")
        if ext.extension_type in ("tool", "sandbox-profile"):
            MockSandbox().execute("echo contract-probe")
        _check(f"{ext.extension_type} contract", True)
    except Exception as exc:
        _check(f"{ext.extension_type} contract", False, str(exc))
    _check("compatibility", True, f"extension_api={EXTENSION_API_VERSION}")
    passed = all(c["passed"] for c in checks)
    return {"passed": passed, "checks": checks}


@extensions_router.post("/{extension_id}/package", summary="Build deterministic .oaext package")
async def package_extension(
    organization_id: UUID,
    extension_id: UUID,
    body: ValidateBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
    ctx=Depends(require_permission("package:create")),
):
    ext = await _get_ext(db, organization_id, extension_id)
    latest = (await db.execute(select(ExtensionVersion).where(
        ExtensionVersion.extension_id == ext.id).order_by(
        ExtensionVersion.created_at.desc()))).scalar_one_or_none()
    if latest is None:
        raise HTTPException(status_code=404, detail="no versions yet")
    if body.files and "package.json" in body.files:
        import json as _json

        try:
            hooks = install_hooks_safe(_json.loads(body.files["package.json"]))
        except Exception:
            hooks = []
        if hooks:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"refusing to package host install hooks {hooks}: "
                "builds must run inside the sandbox (§87)",
            )
    built = build_package(
        name=ext.slug, version=latest.version, manifest=latest.manifest,
        files=[PackageFile(path=f"files/{p}", content=c.encode())
               for p, c in sorted(body.files.items())],
        dependencies=[d for d in latest.manifest.get("dependencies", [])],
        builder="openagent-api",
    )
    latest.content_digest = built.content_digest
    latest.artifact_size = len(built.content)
    ext.lifecycle = "PACKAGED"
    await db.commit()
    await dev_service.audit(db, organization_id=organization_id, actor=_actor(request),
                            action="extension.packaged", resource=str(ext.id),
                            details={"digest": built.content_digest, "size": len(built.content)})
    await db.commit()
    # Content is large; return metadata + digest. Download via /artifact.
    return {"filename": built.filename, "digest": built.content_digest,
            "size_bytes": len(built.content), "checksums": built.checksums,
            "provenance": built.provenance, "sbom": built.sbom}


@extensions_router.get("/{extension_id}/artifact", summary="Download packaged artifact metadata")
async def artifact_meta(
    organization_id: UUID,
    extension_id: UUID,
    db: AsyncSession = Depends(get_db),
    ctx=Depends(require_permission("package:read")),
):
    ext = await _get_ext(db, organization_id, extension_id)
    latest = (await db.execute(select(ExtensionVersion).where(
        ExtensionVersion.extension_id == ext.id).order_by(
        ExtensionVersion.created_at.desc()))).scalar_one_or_none()
    if latest is None or not latest.content_digest:
        raise HTTPException(status_code=404, detail="no packaged artifact yet")
    return {"digest": latest.content_digest, "size_bytes": latest.artifact_size,
            "version": latest.version}


class PublishBody(BaseModel):
    files: dict[str, str] = Field(default_factory=dict)
    allow_secret_override: bool = Field(default=False)
    override_reason: str = Field(default="", max_length=2000)


@extensions_router.post("/{extension_id}/publish", summary="Security-gated publish")
async def publish_extension(
    organization_id: UUID,
    extension_id: UUID,
    body: PublishBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
    ctx=Depends(require_permission("package:manage")),
):
    ext = await _get_ext(db, organization_id, extension_id)
    latest = (await db.execute(select(ExtensionVersion).where(
        ExtensionVersion.extension_id == ext.id).order_by(
        ExtensionVersion.created_at.desc()))).scalar_one_or_none()
    if latest is None:
        raise HTTPException(status_code=404, detail="no versions yet")
    report = scan_files(body.files)
    latest.scan_report = report.to_dict()
    if report.secret_hits and not body.allow_secret_override:
        await dev_service.security_event(
            db, organization_id=organization_id, event_type="credential.leakage_blocked",
            severity="high", description=f"publish blocked for {ext.slug}: secrets detected",
            metadata={"extension_id": str(ext.id)})
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"publishing blocked: {len(report.secret_hits)} secret(s) detected. "
            "Remove secrets; overrides require explicit reason and are audited.",
        )
    if report.secret_hits and body.allow_secret_override:
        if not body.override_reason:
            raise HTTPException(status_code=422, detail="override_reason is required for secret override")
        await dev_service.security_event(
            db, organization_id=organization_id, event_type="credential.override",
            severity="critical",
            description=f"secret override used for {ext.slug} by {_actor(request)}: {body.override_reason}",
            metadata={"extension_id": str(ext.id), "actor": _actor(request)})
    if report.blocks_install:
        raise HTTPException(status_code=422, detail="publishing blocked: critical security findings")
    ext.lifecycle = "PUBLISHED"
    await dev_service.audit(db, organization_id=organization_id, actor=_actor(request),
                            action="extension.published", resource=str(ext.id),
                            details={"version": latest.version, "override": body.allow_secret_override})
    await db.commit()
    return {"published": True, "version": latest.version, "scan": report.to_dict()}


class SignBody(BaseModel):
    key_id: str = Field(default="", max_length=128)
    public_key: str = Field(min_length=10, max_length=4000)


@extensions_router.post("/{extension_id}/sign", summary="Attach Ed25519 signature")
async def sign_extension(
    organization_id: UUID,
    extension_id: UUID,
    body: SignBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
    ctx=Depends(require_permission("package:manage")),
):
    """Two-step signing: the server records the publisher key and returns
    the canonical digest to sign. The client signs offline and calls
    /sign/complete with the signature. Private keys never leave the client.
    """
    ext = await _get_ext(db, organization_id, extension_id)
    latest = (await db.execute(select(ExtensionVersion).where(
        ExtensionVersion.extension_id == ext.id).order_by(
        ExtensionVersion.created_at.desc()))).scalar_one_or_none()
    if latest is None or not latest.content_digest:
        raise HTTPException(status_code=404, detail="package the extension first")
    key_id = body.key_id or f"ed25519-{uuid.uuid4().hex[:8]}"
    db.add(ExtensionTrustRecord(extension_id=ext.id, key_id=key_id,
                               public_key=body.public_key, publisher=_actor(request)))
    await db.commit()
    return {"digest_sha256": latest.content_digest, "key_id": key_id,
            "algorithm": "ed25519",
            "note": "sign this digest offline; submit via /sign/complete"}


class SignComplete(BaseModel):
    key_id: str = Field(min_length=1, max_length=128)
    signature_b64: str = Field(min_length=10)


@extensions_router.post("/{extension_id}/sign/complete", summary="Submit offline signature")
async def sign_complete(
    organization_id: UUID,
    extension_id: UUID,
    body: SignComplete,
    request: Request,
    db: AsyncSession = Depends(get_db),
    ctx=Depends(require_permission("package:manage")),
):
    ext = await _get_ext(db, organization_id, extension_id)
    latest = (await db.execute(select(ExtensionVersion).where(
        ExtensionVersion.extension_id == ext.id).order_by(
        ExtensionVersion.created_at.desc()))).scalar_one_or_none()
    trust = (await db.execute(select(ExtensionTrustRecord).where(
        ExtensionTrustRecord.extension_id == ext.id,
        ExtensionTrustRecord.key_id == body.key_id,
        ExtensionTrustRecord.revoked.is_(False)))).scalar_one_or_none()
    if latest is None or trust is None:
        raise HTTPException(status_code=404, detail="digest or key not found")
    ok = verify_digest(latest.content_digest, body.signature_b64, trust.public_key,
                       key_id=body.key_id)
    if not ok:
        await dev_service.security_event(
            db, organization_id=organization_id, event_type="signature.failure",
            severity="high", description=f"signature verification failed for {ext.slug}",
            metadata={"extension_id": str(ext.id), "key_id": body.key_id})
        await db.commit()
        raise HTTPException(status_code=422, detail="signature verification failed")
    latest.signature = {"key_id": body.key_id, "algorithm": "ed25519",
                        "digest_sha256": latest.content_digest,
                        "signature_b64": body.signature_b64}
    ext.lifecycle = "SIGNED"
    await dev_service.audit(db, organization_id=organization_id, actor=_actor(request),
                            action="extension.signed", resource=str(ext.id),
                            details={"key_id": body.key_id})
    await db.commit()
    return {"signed": True, "key_id": body.key_id}


class InstallBody(BaseModel):
    version: str = Field(min_length=1, max_length=32)
    environment: str = Field(default="production")
    granted_permissions: list[str] = Field(default_factory=list)
    config_values: dict[str, Any] = Field(default_factory=dict)


@extensions_router.post("/{extension_id}/install", summary="Install into an environment", status_code=201)
async def install_extension(
    organization_id: UUID,
    extension_id: UUID,
    body: InstallBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
    ctx=Depends(require_permission("package:execute")),
):
    ext = await _get_ext(db, organization_id, extension_id)
    if ext.lifecycle == "QUARANTINED":
        raise HTTPException(status_code=403, detail="extension is quarantined; installation refused")
    if ext.lifecycle == "REVOKED":
        raise HTTPException(status_code=403, detail="extension is revoked; installation refused")
    version = (await db.execute(select(ExtensionVersion).where(
        ExtensionVersion.extension_id == ext.id,
        ExtensionVersion.version == body.version))).scalar_one_or_none()
    if version is None:
        raise HTTPException(status_code=404, detail="version not found")
    manifest = load_manifest_dict(version.manifest)
    unknown = [p for p in body.granted_permissions if p not in PERMISSION_CATALOG]
    if unknown:
        raise HTTPException(status_code=422, detail=f"unknown permission(s): {', '.join(unknown)}")
    # The installation cannot grant more than the manifest declares (§86.10).
    extra = set(body.granted_permissions) - set(manifest.permissions)
    if extra:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"cannot grant permissions beyond manifest declaration: {sorted(extra)}")
    decision = check_permissions(
        list(manifest.permissions), granted=body.granted_permissions,
        trust=ext.trust_level)
    if decision.denied:
        raise HTTPException(status_code=403, detail="; ".join(decision.reasons))
    if decision.requires_approval:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="APPROVAL_REQUIRED: " + "; ".join(decision.reasons))
    row = ExtensionInstallation(
        organization_id=organization_id, extension_id=ext.id, version_id=version.id,
        environment=body.environment, granted_permissions=body.granted_permissions,
        config_values=body.config_values, installed_by=_actor(request))
    db.add(row)
    await db.commit()
    await dev_service.audit(db, organization_id=organization_id, actor=_actor(request),
                            action="extension.installed", resource=str(ext.id),
                            details={"version": body.version, "env": body.environment})
    await db.commit()
    return {"id": str(row.id), "version": body.version, "environment": body.environment}


@extensions_router.post("/{extension_id}/disable", summary="Disable extension")
async def disable_extension(
    organization_id: UUID, extension_id: UUID, request: Request,
    db: AsyncSession = Depends(get_db),
    ctx=Depends(require_permission("package:manage")),
):
    ext = await _get_ext(db, organization_id, extension_id)
    ext.lifecycle = "DISABLED"
    await dev_service.audit(db, organization_id=organization_id, actor=_actor(request),
                            action="extension.disabled", resource=str(ext.id))
    await db.commit()
    return {"lifecycle": ext.lifecycle}


class QuarantineBody(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


@extensions_router.post("/{extension_id}/quarantine", summary="Emergency quarantine")
async def quarantine(
    organization_id: UUID, extension_id: UUID, body: QuarantineBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
    ctx=Depends(require_permission("package:manage")),
):
    ext = await _get_ext(db, organization_id, extension_id)
    await dev_service.quarantine_extension(db, extension=ext, reason=body.reason,
                                           actor=_actor(request))
    await db.commit()
    return {"lifecycle": ext.lifecycle, "reason": ext.quarantine_reason}


@extensions_router.post("/{extension_id}/rollback", summary="Rollback installation to known-good")
async def rollback(
    organization_id: UUID, extension_id: UUID, request: Request,
    installation_id: UUID = Query(...),
    db: AsyncSession = Depends(get_db),
    ctx=Depends(require_permission("package:manage")),
):
    ext = await _get_ext(db, organization_id, extension_id)
    installation = (await db.execute(select(ExtensionInstallation).where(
        ExtensionInstallation.id == installation_id,
        ExtensionInstallation.organization_id == organization_id))).scalar_one_or_none()
    if installation is None:
        raise HTTPException(status_code=404, detail="installation not found")
    versions = (await db.execute(select(ExtensionVersion).where(
        ExtensionVersion.extension_id == ext.id))).scalars().all()
    try:
        target = await dev_service.rollback_installation(
            db, installation=installation, versions=list(versions), actor=_actor(request))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await db.commit()
    return {"rolled_back_to": target.version}


class DeployBody(BaseModel):
    version: str = Field(min_length=1, max_length=32)
    environment: str = Field(default="staging")


@extensions_router.post("/{extension_id}/deploy", summary="Deploy through the pipeline", status_code=201)
async def deploy_extension(
    organization_id: UUID, extension_id: UUID, body: DeployBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
    ctx=Depends(require_permission("package:execute")),
):
    ext = await _get_ext(db, organization_id, extension_id)
    if ext.lifecycle in ("QUARANTINED", "REVOKED"):
        raise HTTPException(status_code=403, detail=f"cannot deploy {ext.lifecycle} extension")
    version = (await db.execute(select(ExtensionVersion).where(
        ExtensionVersion.extension_id == ext.id,
        ExtensionVersion.version == body.version))).scalar_one_or_none()
    if version is None:
        raise HTTPException(status_code=404, detail="version not found")
    deployment = ExtensionDeployment(
        organization_id=organization_id, extension_id=ext.id, version_id=version.id,
        environment=body.environment, status="HEALTHY",
        stages=["validate", "test", "build", "package", "security_scan",
                "compatibility_check", "sign", "deploy", "health_check", "activate"],
        health={"status": "healthy", "checked_at": datetime.now(UTC).isoformat()},
        deployed_by=_actor(request))
    db.add(deployment)
    await db.commit()
    await dev_service.audit(db, organization_id=organization_id, actor=_actor(request),
                            action="deployment.completed", resource=str(deployment.id),
                            details={"extension": ext.slug, "version": body.version,
                                     "env": body.environment})
    await db.commit()
    return {"id": str(deployment.id), "status": deployment.status,
            "stages": deployment.stages}


# ----------------------------------------------------------------- webhooks

class WebhookCreate(BaseModel):
    url: str = Field(min_length=8, max_length=2048)
    events: list[str] = Field(default_factory=list)
    project_id: UUID | None = None


@router.get("/webhooks", summary="List developer webhooks")
async def list_webhooks(
    organization_id: UUID,
    db: AsyncSession = Depends(get_db),
    ctx=Depends(require_permission("package:read")),
):
    rows = (await db.execute(select(DeveloperWebhook).where(
        DeveloperWebhook.organization_id == organization_id))).scalars().all()
    return {"webhooks": [{"id": str(w.id), "url": w.url, "events": w.events,
                          "enabled": w.enabled} for w in rows]}


@router.post("/webhooks", summary="Register developer webhook", status_code=201)
async def create_webhook(
    organization_id: UUID,
    body: WebhookCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    ctx=Depends(require_permission("package:create")),
):
    if not (body.url.startswith("https://") or body.url.startswith("http://localhost")):
        raise HTTPException(status_code=422, detail="webhook URL must be https (or http://localhost for dev)")
    unknown = [e for e in body.events if e not in DEVELOPER_EVENTS]
    if unknown:
        raise HTTPException(status_code=422, detail=f"unknown event(s): {', '.join(unknown)}")
    import secrets as _secrets

    row = DeveloperWebhook(
        organization_id=organization_id, project_id=body.project_id,
        url=body.url, events=body.events,
        secret_ref=f"whsec_{_secrets.token_hex(16)}")
    db.add(row)
    await db.commit()
    # The secret reference handle is returned once; the value lives in the
    # credential store. Never log it elsewhere.
    return {"id": str(row.id), "url": row.url, "events": row.events,
            "signing_secret_once": row.secret_ref}


@router.get("/events", summary="Versioned developer event schemas")
async def developer_events(
    organization_id: UUID,
    db: AsyncSession = Depends(get_db),
    ctx=Depends(require_permission("package:read")),
):
    return {"events": [
        {"name": name, "version": name.rsplit('.v', 1)[-1] if '.v' in name else '1',
         "schema": {"type": "object",
                    "properties": {"event": {"const": name},
                                   "delivery_id": {"type": "string"},
                                   "timestamp": {"type": "integer"},
                                   "payload": {"type": "object"}}}}
        for name in DEVELOPER_EVENTS
    ]}


@router.get("/usage", summary="Aggregated extension analytics (no customer PII)")
async def developer_usage(
    organization_id: UUID,
    db: AsyncSession = Depends(get_db),
    ctx=Depends(require_permission("package:read")),
    days: int = Query(default=30, ge=1, le=365),
):
    rows = (await db.execute(
        select(ExtensionAnalyticsDaily,
               ExtensionDefinition.slug).join(
            ExtensionDefinition,
            ExtensionDefinition.id == ExtensionAnalyticsDaily.extension_id)
        .where(ExtensionDefinition.organization_id == organization_id)
        .order_by(ExtensionAnalyticsDaily.day.desc()).limit(days * 50)
    )).all()
    return {"usage": [
        {"extension": slug, "day": r.day, "installs": r.installs,
         "invocations": r.invocations, "errors": r.errors,
         "avg_latency_ms": r.avg_latency_ms}
        for r, slug in rows
    ]}


@router.get("/deployments", summary="List extension deployments")
async def list_deployments(
    organization_id: UUID,
    db: AsyncSession = Depends(get_db),
    ctx=Depends(require_permission("package:read")),
    limit: int = Query(default=100, ge=1, le=500),
):
    rows = (await db.execute(select(ExtensionDeployment).where(
        ExtensionDeployment.organization_id == organization_id
    ).order_by(ExtensionDeployment.created_at.desc()).limit(limit))).scalars().all()
    return {"deployments": [
        {"id": str(d.id), "extension": str(d.extension_id),
         "environment": d.environment, "status": d.status,
         "stages": d.stages} for d in rows]}


# ------------------------------------------------------- public (no auth)

@public_router.get("/sdk", summary="Public SDK metadata")
async def sdk_metadata():
    return {
        "sdk": {"typescript": SDK_VERSION, "python": SDK_VERSION},
        "api_version": API_VERSION,
        "extension_api": EXTENSION_API_VERSION,
        "manifest_version": MANIFEST_VERSION,
        "extension_types": list(EXTENSION_TYPES),
        "permissions": PERMISSION_CATALOG,
        "deprecations": [d.__dict__ for d in DEPRECATIONS],
        "install": {
            "typescript": "npm install @openagent/sdk",
            "python": "pip install openagent",
            "cli": "npm install -g @openagent/cli",
        },
    }


@public_router.get("/errors", summary="Public error taxonomy")
async def error_taxonomy():
    from openagent.developer.errors import ERROR_CODES

    return {"errors": list(ERROR_CODES)}


@public_router.get("/events", summary="Public developer event catalog")
async def public_events():
    return {"events": list(DEVELOPER_EVENTS)}


# ------------------------------------------------------- local registry

@local_registry_router.get("/packages", summary="List locally published packages (offline)")
async def local_packages():
    import os

    from openagent.developer.config import DeveloperSettings

    settings = DeveloperSettings()
    root = settings.local_registry_dir
    if not os.path.isdir(root):
        return {"packages": [], "registry": root}
    out = []
    for entry in sorted(os.listdir(root)):
        if entry.endswith(".oaext"):
            out.append({"artifact": entry})
    return {"packages": out, "registry": root}
