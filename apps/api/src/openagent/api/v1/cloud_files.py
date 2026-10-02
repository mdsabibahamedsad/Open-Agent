"""MP25: cloud file/artifact API (§31-32, §60).

Every operation enforces organization ownership. Downloads use
short-lived signed tokens (never raw storage credentials); uploads
enforce checksum/size/MIME/extension validation with quarantine hooks.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from openagent.api.dependencies import get_current_org_context
from openagent.cloud.artifacts import (
    ARTIFACT_CATEGORIES, artifact_result_ref, default_expiry,
    new_artifact_id, sign_download_token, storage_key_for,
    validate_artifact, verify_download_token,
    ArtifactDraft,
)
from openagent.cloud.service import get_cloud_service
from openagent.core.config import get_settings
from openagent.db.models.cloud import CloudArtifact
from openagent.db.session import get_db
from openagent.services.authorization import AuthorizationContext

router = APIRouter(prefix="/cloud/files", tags=["cloud-files"])


class ShareRequest(BaseModel):
    expires_seconds: int = Field(default=3600, ge=60, le=604800)


def _secret() -> str:
    return get_settings().SECRET_KEY or "dev-only-secret"


@router.post("/upload", response_model=Dict[str, Any])
async def upload_artifact(
    execution_id: str = Query(min_length=1, max_length=64),
    category: str = Query(default="execution-artifacts", max_length=64),
    file: UploadFile = File(...),
    auth: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    service = get_cloud_service()
    service.require_enabled()
    if category not in ARTIFACT_CATEGORIES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"unknown category {category}")
    data = await file.read()
    max_bytes = service.settings.ARTIFACT_MAX_BYTES
    if len(data) > max_bytes:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            detail=f"file exceeds {max_bytes} bytes")
    checksum = hashlib.sha256(data).hexdigest()
    artifact_id = new_artifact_id()
    draft = ArtifactDraft(
        organization_id=str(auth.organization_id), execution_id=execution_id,
        name=file.filename or "artifact",
        mime_type=file.content_type or "application/octet-stream",
        size=len(data), checksum=checksum, category=category)
    ok, reason = validate_artifact(draft, max_bytes=max_bytes)
    if not ok:
        # Quarantine record for audit (§32, §75).
        db.add(CloudArtifact(
            artifact_id=artifact_id, organization_id=auth.organization_id,
            execution_id=execution_id, name=draft.name[:500],
            mime_type=draft.mime_type, size=len(data),
            storage_key="", checksum=checksum, category=category,
            state="QUARANTINED"))
        await db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=reason)
    key = storage_key_for(organization_id=str(auth.organization_id),
                          category=category, artifact_id=artifact_id,
                          filename=draft.name)
    stored = await service.storage().put(key, data, draft.mime_type,
                                         {"organization_id": str(auth.organization_id),
                                          "execution_id": execution_id,
                                          "checksum": checksum})
    row = CloudArtifact(
        artifact_id=artifact_id, organization_id=auth.organization_id,
        execution_id=execution_id, name=draft.name[:500],
        mime_type=draft.mime_type, size=stored.size, storage_key=stored.key,
        checksum=stored.checksum, category=category, state="ACTIVE",
        expires_at=default_expiry(service.settings.ARTIFACT_DEFAULT_TTL_SECONDS))
    db.add(row)
    await db.commit()
    return {"artifact": artifact_result_ref(artifact_id), "id": artifact_id,
            "size": stored.size, "checksum": stored.checksum}


@router.get("", response_model=Dict[str, Any])
async def list_artifacts(
    auth: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
    execution_id: str = Query(default=""),
    limit: int = Query(default=50, ge=1, le=200),
):
    get_cloud_service().require_enabled()
    query = select(CloudArtifact).where(
        CloudArtifact.organization_id == auth.organization_id,
        CloudArtifact.state == "ACTIVE")
    if execution_id:
        query = query.where(CloudArtifact.execution_id == execution_id)
    rows = (await db.execute(
        query.order_by(CloudArtifact.created_at.desc()).limit(limit))).scalars().all()
    return {"artifacts": [
        {"id": r.artifact_id, "name": r.name, "size": r.size,
         "mime": r.mime_type, "category": r.category,
         "execution": r.execution_id, "checksum": r.checksum} for r in rows]}


@router.get("/{artifact_id}", response_model=Dict[str, Any])
async def download_artifact(
    artifact_id: str,
    token: str = Query(default=""),
    auth: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    service = get_cloud_service()
    service.require_enabled()
    row = (await db.execute(
        select(CloudArtifact).where(
            CloudArtifact.artifact_id == artifact_id,
            CloudArtifact.organization_id == auth.organization_id))).scalar_one_or_none()
    if row is None or row.state != "ACTIVE":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Artifact not found")
    if token:
        if not verify_download_token(token, artifact_id=artifact_id,
                                     organization_id=str(auth.organization_id),
                                     secret=_secret()):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail="Expired or invalid download token")
    data = await service.storage().get(row.storage_key)
    if data is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Object missing from storage")
    if row.checksum and hashlib.sha256(data).hexdigest() != row.checksum:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY,
                            detail="Checksum mismatch")
    row.download_count += 1
    await db.commit()
    from fastapi.responses import Response
    return Response(content=data, media_type=row.mime_type,
                    headers={"Content-Disposition": f'attachment; filename="{row.name}"',
                             "X-Checksum-Sha256": row.checksum})


@router.post("/{artifact_id}/share", response_model=Dict[str, Any])
async def share_artifact(
    artifact_id: str, body: ShareRequest,
    auth: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    get_cloud_service().require_enabled()
    row = (await db.execute(
        select(CloudArtifact).where(
            CloudArtifact.artifact_id == artifact_id,
            CloudArtifact.organization_id == auth.organization_id))).scalar_one_or_none()
    if row is None or row.state != "ACTIVE":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Artifact not found")
    expires = default_expiry(body.expires_seconds)
    token = sign_download_token(artifact_id=artifact_id,
                                organization_id=str(auth.organization_id),
                                secret=_secret(), expires_at=expires)
    return {"artifact_id": artifact_id, "token": token,
            "expires_at": expires.isoformat()}


@router.delete("/{artifact_id}", response_model=Dict[str, Any])
async def delete_artifact(
    artifact_id: str,
    auth: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    get_cloud_service().require_enabled()
    row = (await db.execute(
        select(CloudArtifact).where(
            CloudArtifact.artifact_id == artifact_id,
            CloudArtifact.organization_id == auth.organization_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Artifact not found")
    row.state = "DELETED"
    await db.commit()
    return {"id": artifact_id, "state": "DELETED"}
