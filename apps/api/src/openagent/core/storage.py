import abc
import hashlib
import mimetypes
import os
import shutil
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, BinaryIO, Dict, List, Optional, AsyncGenerator
from dataclasses import dataclass, field

from openagent.core.config import get_settings


class StorageProvider(str, Enum):
    LOCAL = "local"
    S3 = "s3"
    GCS = "gcs"
    AZURE = "azure"


@dataclass
class StorageConfig:
    provider: StorageProvider = StorageProvider.LOCAL
    # Local storage
    local_path: str = "./storage"
    # S3
    s3_bucket: Optional[str] = None
    s3_region: Optional[str] = None
    s3_access_key: Optional[str] = None
    s3_secret_key: Optional[str] = None
    s3_endpoint: Optional[str] = None
    # GCS
    gcs_bucket: Optional[str] = None
    gcs_credentials_path: Optional[str] = None
    # Azure
    azure_container: Optional[str] = None
    azure_account: Optional[str] = None
    azure_key: Optional[str] = None


@dataclass
class StoredFile:
    id: str
    key: str
    filename: str
    content_type: str
    size: int
    checksum: str
    storage_provider: StorageProvider
    bucket: Optional[str] = None
    path: Optional[str] = None
    url: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: Optional[datetime] = None


class StorageBackend(abc.ABC):
    """Abstract base class for storage backends."""
    
    @abc.abstractmethod
    async def upload(
        self,
        key: str,
        file: BinaryIO,
        content_type: str,
        filename: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> StoredFile:
        """Upload a file."""
        pass
    
    @abc.abstractmethod
    async def download(self, key: str) -> Optional[AsyncGenerator[bytes, None]]:
        """Download a file as async generator."""
        pass
    
    @abc.abstractmethod
    async def delete(self, key: str) -> bool:
        """Delete a file."""
        pass
    
    @abc.abstractmethod
    async def exists(self, key: str) -> bool:
        """Check if file exists."""
        pass
    
    @abc.abstractmethod
    async def get_metadata(self, key: str) -> Optional[StoredFile]:
        """Get file metadata."""
        pass
    
    @abc.abstractmethod
    async def generate_presigned_url(
        self,
        key: str,
        expiration: int = 3600,
        method: str = "GET",
    ) -> str:
        """Generate a presigned URL for file access."""
        pass
    
    @abc.abstractmethod
    async def list_files(
        self,
        prefix: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> List[StoredFile]:
        """List files with prefix."""
        pass


class LocalStorageBackend(StorageBackend):
    """Local filesystem storage backend."""
    
    def __init__(self, base_path: str = "./storage"):
        self.base_path = Path(base_path).resolve()
        self.base_path.mkdir(parents=True, exist_ok=True)
    
    def _get_file_path(self, key: str) -> Path:
        return self.base_path / key
    
    def _get_metadata_path(self, key: str) -> Path:
        return self.base_path / f".{key}.meta"
    
    async def upload(
        self,
        key: str,
        file: BinaryIO,
        content_type: str,
        filename: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> StoredFile:
        file_path = self._get_file_path(key)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Calculate checksum while uploading
        hasher = hashlib.sha256()
        size = 0
        
        with open(file_path, "wb") as f:
            while chunk := file.read(8192):
                f.write(chunk)
                hasher.update(chunk)
                size += len(chunk)
        
        checksum = hasher.hexdigest()
        
        stored_file = StoredFile(
            id=str(uuid.uuid4()),
            key=key,
            filename=filename,
            content_type=content_type,
            size=size,
            checksum=checksum,
            storage_provider=StorageProvider.LOCAL,
            path=str(file_path),
            metadata=metadata or {},
        )
        
        # Save metadata
        meta_path = self._get_metadata_path(key)
        import json
        with open(meta_path, "w") as f:
            json.dump({
                "id": stored_file.id,
                "key": stored_file.key,
                "filename": stored_file.filename,
                "content_type": stored_file.content_type,
                "size": stored_file.size,
                "checksum": stored_file.checksum,
                "storage_provider": stored_file.storage_provider.value,
                "metadata": stored_file.metadata,
                "created_at": stored_file.created_at.isoformat(),
            }, f)
        
        return stored_file
    
    async def download(self, key: str) -> Optional[AsyncGenerator[bytes, None]]:
        file_path = self._get_file_path(key)
        if not file_path.exists():
            return None
        
        async def file_generator():
            with open(file_path, "rb") as f:
                while chunk := f.read(8192):
                    yield chunk
        
        return file_generator()
    
    async def delete(self, key: str) -> bool:
        file_path = self._get_file_path(key)
        meta_path = self._get_metadata_path(key)
        
        deleted = False
        if file_path.exists():
            file_path.unlink()
            deleted = True
        if meta_path.exists():
            meta_path.unlink()
        
        return deleted
    
    async def exists(self, key: str) -> bool:
        return self._get_file_path(key).exists()
    
    async def get_metadata(self, key: str) -> Optional[StoredFile]:
        meta_path = self._get_metadata_path(key)
        if not meta_path.exists():
            return None
        
        import json
        with open(meta_path, "r") as f:
            data = json.load(f)
        
        return StoredFile(
            id=data["id"],
            key=data["key"],
            filename=data["filename"],
            content_type=data["content_type"],
            size=data["size"],
            checksum=data["checksum"],
            storage_provider=StorageProvider(data["storage_provider"]),
            metadata=data["metadata"],
            created_at=datetime.fromisoformat(data["created_at"]),
        )
    
    async def generate_presigned_url(
        self,
        key: str,
        expiration: int = 3600,
        method: str = "GET",
    ) -> str:
        # For local storage, return a direct URL
        # In production, this would be a signed URL
        return f"/api/v1/storage/files/{key}"
    
    async def list_files(
        self,
        prefix: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> List[StoredFile]:
        files = []
        prefix_path = self.base_path / prefix
        
        if not prefix_path.exists():
            return files
        
        meta_files = sorted(
            prefix_path.glob(".**meta"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        
        for meta_file in meta_files[offset:offset + limit]:
            import json
            with open(meta_file, "r") as f:
                data = json.load(f)
            files.append(StoredFile(
                id=data["id"],
                key=data["key"],
                filename=data["filename"],
                content_type=data["content_type"],
                size=data["size"],
                checksum=data["checksum"],
                storage_provider=StorageProvider(data["storage_provider"]),
                metadata=data["metadata"],
                created_at=datetime.fromisoformat(data["created_at"]),
            ))
        
        return files


class S3StorageBackend(StorageBackend):
    """S3-compatible storage backend."""
    
    def __init__(
        self,
        bucket: str,
        region: str = "us-east-1",
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        endpoint_url: Optional[str] = None,
    ):
        self.bucket = bucket
        self.region = region
        self.access_key = access_key
        self.secret_key = secret_key
        self.endpoint_url = endpoint_url
        self._client = None
    
    async def _get_client(self):
        if self._client is None:
            import boto3
            self._client = boto3.client(
                "s3",
                region_name=self.region,
                aws_access_key_id=self.access_key,
                aws_secret_access_key=self.secret_key,
                endpoint_url=self.endpoint_url,
            )
        return self._client
    
    async def upload(
        self,
        key: str,
        file: BinaryIO,
        content_type: str,
        filename: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> StoredFile:
        client = await self._get_client()
        
        # Calculate checksum
        hasher = hashlib.sha256()
        file.seek(0)
        content = file.read()
        hasher.update(content)
        file.seek(0)
        
        checksum = hasher.hexdigest()
        size = len(content)
        
        extra_args = {
            "ContentType": content_type,
        }
        if metadata:
            extra_args["Metadata"] = {k: str(v) for k, v in metadata.items()}
        
        client = await self._get_client()
        await client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=content,
            **extra_args,
        )
        
        return StoredFile(
            id=str(uuid.uuid4()),
            key=key,
            filename=filename,
            content_type=content_type,
            size=size,
            checksum=checksum,
            storage_provider=StorageProvider.S3,
            bucket=self.bucket,
            metadata=metadata or {},
        )
    
    async def download(self, key: str) -> Optional[AsyncGenerator[bytes, None]]:
        client = await self._get_client()
        try:
            response = await client.get_object(Bucket=self.bucket, Key=key)
            async for chunk in response["Body"].iter_chunks():
                yield chunk
        except client.exceptions.NoSuchKey:
            return
    
    async def delete(self, key: str) -> bool:
        client = await self._get_client()
        try:
            await client.delete_object(Bucket=self.bucket, Key=key)
            return True
        except client.exceptions.NoSuchKey:
            return False
    
    async def exists(self, key: str) -> bool:
        client = await self._get_client()
        try:
            await client.head_object(Bucket=self.bucket, Key=key)
            return True
        except client.exceptions.NoSuchKey:
            return False
    
    async def get_metadata(self, key: str) -> Optional[StoredFile]:
        client = await self._get_client()
        try:
            response = await client.head_object(Bucket=self.bucket, Key=key)
            return StoredFile(
                id=key,
                key=key,
                filename=key.split("/")[-1],
                content_type=response.get("ContentType", "application/octet-stream"),
                size=response.get("ContentLength", 0),
                checksum=response.get("ETag", "").strip('"'),
                storage_provider=StorageProvider.S3,
                bucket=self.bucket,
                metadata=response.get("Metadata", {}),
                created_at=response.get("LastModified", datetime.now(timezone.utc)),
            )
        except client.exceptions.NoSuchKey:
            return None
    
    async def generate_presigned_url(
        self,
        key: str,
        expiration: int = 3600,
        method: str = "GET",
    ) -> str:
        client = await self._get_client()
        return client.generate_presigned_url(
            "get_object" if method == "GET" else "put_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expiration,
        )
    
    async def list_files(
        self,
        prefix: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> List[StoredFile]:
        client = await self._get_client()
        paginator = client.get_paginator("list_objects_v2")
        files = []
        
        async for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                if len(files) >= offset + limit:
                    break
                if len(files) >= offset:
                    files.append(StoredFile(
                        id=obj["Key"],
                        key=obj["Key"],
                        filename=obj["Key"].split("/")[-1],
                        content_type="application/octet-stream",  # Would need HEAD request
                        size=obj["Size"],
                        checksum=obj["ETag"].strip('"'),
                        storage_provider=StorageProvider.S3,
                        bucket=self.bucket,
                        created_at=obj["LastModified"],
                    ))
        
        return files[:limit]


class StorageService:
    """High-level storage service with multiple backend support."""
    
    def __init__(self):
        self.settings = get_settings()
        self._backends: Dict[StorageProvider, StorageBackend] = {}
        self._default_backend: Optional[StorageBackend] = None
    
    def register_backend(self, provider: StorageProvider, backend: StorageBackend) -> None:
        self._backends[provider] = backend
        if self._default_backend is None:
            self._default_backend = backend
    
    def set_default_backend(self, provider: StorageProvider) -> None:
        if provider in self._backends:
            self._default_backend = self._backends[provider]
    
    def get_backend(self, provider: Optional[StorageProvider] = None) -> StorageBackend:
        if provider and provider in self._backends:
            return self._backends[provider]
        if self._default_backend:
            return self._default_backend
        raise ValueError("No storage backend configured")
    
    async def upload(
        self,
        key: str,
        file: BinaryIO,
        content_type: str,
        filename: str,
        provider: Optional[StorageProvider] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> StoredFile:
        backend = self.get_backend(provider)
        return await backend.upload(key, file, content_type, filename, metadata)
    
    async def download(
        self,
        key: str,
        provider: Optional[StorageProvider] = None,
    ) -> Optional[AsyncGenerator[bytes, None]]:
        backend = self.get_backend(provider)
        return await backend.download(key)
    
    async def delete(
        self,
        key: str,
        provider: Optional[StorageProvider] = None,
    ) -> bool:
        backend = self.get_backend(provider)
        return await backend.delete(key)
    
    async def exists(
        self,
        key: str,
        provider: Optional[StorageProvider] = None,
    ) -> bool:
        backend = self.get_backend(provider)
        return await backend.exists(key)
    
    async def get_metadata(
        self,
        key: str,
        provider: Optional[StorageProvider] = None,
    ) -> Optional[StoredFile]:
        backend = self.get_backend(provider)
        return await backend.get_metadata(key)
    
    async def generate_presigned_url(
        self,
        key: str,
        expiration: int = 3600,
        method: str = "GET",
        provider: Optional[StorageProvider] = None,
    ) -> str:
        backend = self.get_backend(provider)
        return await backend.generate_presigned_url(key, expiration, method)
    
    async def list_files(
        self,
        prefix: str = "",
        limit: int = 100,
        offset: int = 0,
        provider: Optional[StorageProvider] = None,
    ) -> List[StoredFile]:
        backend = self.get_backend(provider)
        return await backend.list_files(prefix, limit, offset)


def create_storage_service() -> StorageService:
    """Create storage service from settings."""
    settings = get_settings()
    service = StorageService()
    
    # Local storage (default)
    local_path = getattr(settings, "STORAGE_LOCAL_PATH", "./storage")
    local_backend = LocalStorageBackend(local_path)
    service.register_backend(StorageProvider.LOCAL, local_backend)
    
    # S3 storage (if configured)
    if hasattr(settings, "S3_BUCKET") and settings.S3_BUCKET:
        s3_backend = S3StorageBackend(
            bucket=settings.S3_BUCKET,
            region=getattr(settings, "S3_REGION", "us-east-1"),
            access_key=getattr(settings, "S3_ACCESS_KEY", None),
            secret_key=getattr(settings, "S3_SECRET_KEY", None),
            endpoint_url=getattr(settings, "S3_ENDPOINT_URL", None),
        )
        service.register_backend(StorageProvider.S3, s3_backend)
        service.set_default_backend(StorageProvider.S3)
    
    return service


# Dependency
async def get_storage_service() -> StorageService:
    return create_storage_service()


# Import needed for StorageFile
from typing import List
import asyncio
from contextlib import asynccontextmanager