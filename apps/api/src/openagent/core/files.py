import hashlib
import io
import mimetypes
import os
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, BinaryIO, Dict, List, Optional, AsyncGenerator
from dataclasses import dataclass, field

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import String, Text, ForeignKey, Index, Enum as SQLEnum, DateTime, JSON, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from openagent.db.models.base import Base, TimestampMixin, UUIDMixin
from openagent.db.session import get_db
from openagent.core.config import get_settings
from openagent.core.storage import StorageService, StoredFile, StorageProvider


class FileUploadStatus(str, Enum):
    PENDING = "pending"
    UPLOADING = "uploading"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"


class FileUpload(Base, TimestampMixin):
    """File upload tracking."""
    
    __tablename__ = "file_uploads"
    
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_provider: Mapped[str] = mapped_column(String(50), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    storage_bucket: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(
        SQLEnum(FileUploadStatus, name="file_upload_status", create_constraint=True),
        default=FileUploadStatus.PENDING,
        nullable=False
    )
    progress: Mapped[int] = mapped_column(default=0, nullable=False)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(nullable=True, index=True)
    metadata: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    
    __table_args__ = (
        Index("ix_file_uploads_org_status", "organization_id", "status"),
        Index("ix_file_uploads_user_status", "user_id", "status"),
        Index("ix_file_uploads_expires", "expires_at"),
    )


@dataclass
class FileUploadConfig:
    max_file_size: int = 100 * 1024 * 1024  # 100MB
    allowed_content_types: List[str] = field(default_factory=lambda: [
        "application/pdf",
        "application/json",
        "text/plain",
        "text/csv",
        "text/markdown",
        "image/jpeg",
        "image/png",
        "image/gif",
        "image/webp",
        "application/zip",
        "application/x-zip-compressed",
        "application/x-tar",
        "application/gzip",
    ])
    allowed_extensions: List[str] = field(default_factory=lambda: [
        ".pdf", ".json", ".txt", ".csv", ".md",
        ".jpg", ".jpeg", ".png", ".gif", ".webp",
        ".zip", ".tar", ".gz",
    ])
    storage_provider: Optional[str] = None
    storage_path: Optional[str] = None
    expires_in_hours: int = 168  # 7 days


class FileUploadService:
    """Service for handling file uploads."""
    
    def __init__(self, db: AsyncSession, config: Optional[FileUploadConfig] = None):
        self.db = db
        self.config = config or FileUploadConfig()
        self.storage = StorageService()
    
    def _validate_file(self, file: UploadFile) -> None:
        """Validate uploaded file."""
        # Check content type
        if file.content_type not in self.config.allowed_content_types:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": f"File type not allowed: {file.content_type}",
                    "code": "INVALID_FILE_TYPE",
                    "allowed_types": self.config.allowed_content_types,
                }
            )
        
        # Check file extension
        ext = Path(file.filename).suffix.lower()
        if ext not in self.config.allowed_extensions:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": f"File extension not allowed: {ext}",
                    "code": "INVALID_FILE_EXTENSION",
                    "allowed_extensions": self.config.allowed_extensions,
                }
            )
    
    def _generate_storage_key(self, filename: str, organization_id: uuid.UUID) -> str:
        """Generate a unique storage key."""
        ext = Path(filename).suffix
        unique_id = uuid.uuid4().hex[:16]
        return f"uploads/{organization_id}/{unique_id}{ext}"
    
    async def create_upload(
        self,
        organization_id: uuid.UUID,
        user_id: Optional[uuid.UUID],
        file: UploadFile,
        storage_provider: Optional[StorageProvider] = None,
    ) -> FileUpload:
        """Create a new file upload record."""
        self._validate_file(file)
        
        # Read file content to calculate size and checksum
        content = await file.read()
        await file.seek(0)
        
        size = len(content)
        if size > self.config.max_file_size:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail={
                    "error": f"File size exceeds maximum of {self.config.max_file_size} bytes",
                    "code": "FILE_TOO_LARGE",
                    "max_size": self.config.max_file_size,
                }
            )
        
        # Calculate checksum
        checksum = hashlib.sha256(content).hexdigest()
        
        # Generate storage key
        storage_key = self._generate_storage_key(file.filename, organization_id)
        
        # Create upload record
        upload = FileUpload(
            organization_id=organization_id,
            user_id=user_id,
            filename=Path(file.filename).stem,
            original_filename=file.filename,
            content_type=file.content_type or "application/octet-stream",
            size=size,
            checksum=checksum,
            storage_provider=(storage_provider or StorageProvider.LOCAL).value,
            storage_key=storage_key,
            status=FileUploadStatus.PENDING,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=self.config.expires_in_hours),
        )
        
        self.db.add(upload)
        await self.db.flush()
        
        return upload
    
    async def complete_upload(
        self,
        upload_id: uuid.UUID,
        file_content: bytes,
        storage_provider: Optional[StorageProvider] = None,
    ) -> FileUpload:
        """Complete a file upload by storing the file."""
        result = await self.db.execute(
            select(FileUpload).where(FileUpload.id == upload_id)
        )
        upload = result.scalar_one_or_none()
        
        if not upload:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "Upload not found", "code": "UPLOAD_NOT_FOUND"}
            )
        
        if upload.status != FileUploadStatus.PENDING:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "Upload already processed", "code": "UPLOAD_ALREADY_PROCESSED"}
            )
        
        try:
            upload.status = FileUploadStatus.UPLOADING
            await self.db.flush()
            
            # Store file
            provider = storage_provider or StorageProvider(upload.storage_provider)
            stored_file = await self.storage.upload(
                key=upload.storage_key,
                file=io.BytesIO(file_content),
                content_type=upload.content_type,
                filename=upload.original_filename,
            )
            
            # Verify checksum
            if stored_file.checksum != upload.checksum:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={"error": "Checksum mismatch", "code": "CHECKSUM_MISMATCH"}
                )
            
            # Update upload record
            upload.status = FileUploadStatus.COMPLETED
            upload.storage_key = stored_file.key
            upload.storage_provider = stored_file.storage_provider.value
            upload.storage_bucket = stored_file.bucket
            upload.metadata = stored_file.metadata
            
            await self.db.commit()
            
            return upload
            
        except Exception as e:
            upload.status = FileUploadStatus.FAILED
            upload.error = str(e)
            await self.db.flush()
            raise
    
    async def get_upload(self, upload_id: uuid.UUID) -> Optional[FileUpload]:
        result = await self.db.execute(
            select(FileUpload).where(FileUpload.id == upload_id)
        )
        return result.scalar_one_or_none()
    
    async def get_download_url(
        self,
        upload_id: uuid.UUID,
        expiration: int = 3600,
    ) -> str:
        """Get a presigned download URL for an upload."""
        upload = await self.get_upload(upload_id)
        if not upload:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "Upload not found", "code": "UPLOAD_NOT_FOUND"}
            )
        
        if upload.status != FileUploadStatus.COMPLETED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "File not ready for download", "code": "FILE_NOT_READY"}
            )
        
        provider = StorageProvider(upload.storage_provider)
        return await self.storage.generate_presigned_url(
            key=upload.storage_key,
            expiration=expiration,
            provider=provider,
        )
    
    async def delete_upload(self, upload_id: uuid.UUID) -> bool:
        """Delete an upload and its file."""
        upload = await self.get_upload(upload_id)
        if not upload:
            return False
        
        if upload.status == FileUploadStatus.COMPLETED:
            provider = StorageProvider(upload.storage_provider)
            await self.storage.delete(upload.storage_key, provider=provider)
        
        await self.db.delete(upload)
        await self.db.commit()
        return True
    
    async def cleanup_expired(self) -> int:
        """Clean up expired uploads."""
        now = datetime.now(timezone.utc)
        result = await self.db.execute(
            select(FileUpload).where(
                FileUpload.expires_at < now,
                FileUpload.status.in_([
                    FileUploadStatus.PENDING,
                    FileUploadStatus.FAILED,
                ])
            )
        )
        uploads = list(result.scalars().all())
        
        deleted = 0
        for upload in uploads:
            if upload.status == FileUploadStatus.COMPLETED:
                provider = StorageProvider(upload.storage_provider)
                await self.storage.delete(upload.storage_key, provider=provider)
            await self.db.delete(upload)
            deleted += 1
        
        await self.db.commit()
        return deleted


# Dependency
async def get_file_upload_service(
    db: AsyncSession = Depends(get_db),
) -> FileUploadService:
    return FileUploadService(db)


# FastAPI endpoints for file uploads
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/files", tags=["file-uploads"])


class FileUploadResponse(BaseModel):
    id: uuid.UUID
    filename: str
    original_filename: str
    content_type: str
    size: int
    status: str
    created_at: datetime
    expires_at: Optional[datetime]


class FileUploadCompleteResponse(FileUploadResponse):
    download_url: Optional[str] = None


@router.post(
    "/uploads",
    response_model=FileUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_upload(
    file: UploadFile = File(...),
    organization_id: uuid.UUID = Form(...),
    user_id: Optional[uuid.UUID] = Form(None),
    storage_provider: Optional[str] = Form(None),
    service: FileUploadService = Depends(get_file_upload_service),
):
    """Initiate a file upload."""
    upload = await service.create_upload(
        organization_id=organization_id,
        user_id=user_id,
        file=file,
        storage_provider=StorageProvider(storage_provider) if storage_provider else None,
    )
    return FileUploadResponse(
        id=upload.id,
        filename=upload.filename,
        original_filename=upload.original_filename,
        content_type=upload.content_type,
        size=upload.size,
        status=upload.status.value,
        created_at=upload.created_at,
        expires_at=upload.expires_at,
    )


@router.post(
    "/uploads/{upload_id}/complete",
    response_model=FileUploadCompleteResponse,
)
async def complete_upload(
    upload_id: uuid.UUID,
    file: UploadFile = File(...),
    service: FileUploadService = Depends(get_file_upload_service),
):
    """Complete a file upload by providing the file content."""
    content = await file.read()
    upload = await service.complete_upload(
        upload_id=upload_id,
        file_content=content,
    )
    
    download_url = None
    if upload.status == FileUploadStatus.COMPLETED:
        download_url = await service.get_download_url(upload.id)
    
    return FileUploadCompleteResponse(
        id=upload.id,
        filename=upload.filename,
        original_filename=upload.original_filename,
        content_type=upload.content_type,
        size=upload.size,
        status=upload.status.value,
        created_at=upload.created_at,
        expires_at=upload.expires_at,
        download_url=download_url,
    )


@router.get(
    "/uploads/{upload_id}",
    response_model=FileUploadResponse,
)
async def get_upload(
    upload_id: uuid.UUID,
    service: FileUploadService = Depends(get_file_upload_service),
):
    """Get upload status."""
    upload = await service.get_upload(upload_id)
    if not upload:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Upload not found", "code": "UPLOAD_NOT_FOUND"},
        )
    return FileUploadResponse(
        id=upload.id,
        filename=upload.filename,
        original_filename=upload.original_filename,
        content_type=upload.content_type,
        size=upload.size,
        status=upload.status.value,
        created_at=upload.created_at,
        expires_at=upload.expires_at,
    )


@router.get(
    "/uploads/{upload_id}/download",
)
async def download_file(
    upload_id: uuid.UUID,
    service: FileUploadService = Depends(get_file_upload_service),
):
    """Download a file by streaming from storage."""
    upload = await service.get_upload(upload_id)
    if not upload:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Upload not found", "code": "UPLOAD_NOT_FOUND"},
        )
    
    if upload.status != FileUploadStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "File not ready for download", "code": "FILE_NOT_READY"},
        )
    
    provider = StorageProvider(upload.storage_provider)
    stream = await service.storage.download(upload.storage_key, provider=provider)
    
    if not stream:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "File not found in storage", "code": "FILE_NOT_IN_STORAGE"},
        )
    
    return StreamingResponse(
        stream,
        media_type=upload.content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{upload.original_filename}"',
            "Content-Length": str(upload.size),
        }
    )


@router.get(
    "/uploads/{upload_id}/url",
)
async def get_download_url(
    upload_id: uuid.UUID,
    expiration: int = Query(3600, ge=60, le=86400),
    service: FileUploadService = Depends(get_file_upload_service),
):
    """Get a presigned download URL."""
    url = await service.get_download_url(upload_id, expiration=expiration)
    return {"download_url": url, "expires_in": expiration}


@router.delete(
    "/uploads/{upload_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_upload(
    upload_id: uuid.UUID,
    service: FileUploadService = Depends(get_file_upload_service),
):
    """Delete an upload and its file."""
    success = await service.delete_upload(upload_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Upload not found", "code": "UPLOAD_NOT_FOUND"},
        )

