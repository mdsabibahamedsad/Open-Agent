import pytest
import pytest_asyncio
import io
import uuid
import hashlib
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from openagent.db.models import FileUpload, FileUploadStatus
from openagent.core.storage import (
    StorageService, LocalStorageBackend, S3StorageBackend,
    StoredFile, StorageProvider, StorageConfig, FileUploadConfig,
)
from openagent.core.files import FileUploadService, FileUploadConfig
from openagent.db.models import User, UserStatus, Organization, OrganizationStatus
from openagent.core.security import hash_password


@pytest_asyncio.fixture
async def org(db_session: AsyncSession):
    from openagent.db.repositories import OrganizationRepository
    repo = OrganizationRepository(db_session)
    org = await repo.create(
        name="Test Org Storage",
        slug="test-org-storage",
        status=OrganizationStatus.ACTIVE
    )
    await db_session.commit()
    return org


@pytest_asyncio.fixture
async def user(db_session: AsyncSession, org):
    from openagent.db.repositories import UserRepository, MembershipRepository
    from openagent.db.models import Membership, MembershipRole, MembershipStatus
    from openagent.core.security import hash_password
    
    user_repo = UserRepository(db_session)
    user = await user_repo.create(
        email="test-storage@example.com",
        display_name="Test User",
        password_hash="hashed_password",
        status=UserStatus.ACTIVE,
        email_verified=True,
    )
    
    from openagent.db.models import Membership, MembershipRole, MembershipStatus
    membership = Membership(
        user_id=user.id,
        organization_id=org.id,
        role=MembershipRole.MEMBER,
        status=MembershipStatus.ACTIVE,
    )
    db_session.add(membership)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def file_upload_service(db_session: AsyncSession):
    from openagent.core.files import FileUploadService
    return FileUploadService(db_session)


class TestLocalStorageBackend:
    async def test_upload_and_download(self, db_session: AsyncSession):
        from openagent.core.storage import LocalStorageBackend
        import tempfile
        import os
        
        with tempfile.TemporaryDirectory() as tmpdir:
            backend = LocalStorageBackend(tmpdir)
            
            content = b"Hello, World!"
            file_obj = io.BytesIO(content)
            
            stored = await backend.upload(
                key="test.txt",
                file=file_obj,
                content_type="text/plain",
                filename="test.txt",
            )
            
            assert stored.key == "test.txt"
            assert stored.filename == "test.txt"
            assert stored.content_type == "text/plain"
            assert stored.size == len(content)
            assert stored.checksum == hashlib.sha256(b"Hello, World!").hexdigest()
            assert stored.storage_provider.value == "local"
            
            # Download
            stream = await backend.download("test.txt")
            assert stream is not None
            
            content_read = b""
            async for chunk in stream:
                content_read += chunk
            
            assert content_read == content
            
            # Metadata
            meta = await backend.get_metadata("test.txt")
            assert meta is not None
            assert meta.size == len(content)
            
            # Delete
            deleted = await backend.delete("test.txt")
            assert deleted is True
            
            exists = await backend.exists("test.txt")
            assert exists is False
    
    async def test_upload_with_metadata(self, db_session: AsyncSession):
        from openagent.core.storage import LocalStorageBackend
        import tempfile
        
        with tempfile.TemporaryDirectory() as tmpdir:
            backend = LocalStorageBackend(tmpdir)
            
            content = b"Test with metadata"
            file_obj = io.BytesIO(content)
            
            stored = await backend.upload(
                key="meta.txt",
                file=file_obj,
                content_type="text/plain",
                filename="meta.txt",
                metadata={"custom": "data", "version": "1.0"},
            )
            
            assert stored.metadata == {"custom": "data", "version": "1.0"}
            
            # Check metadata persisted
            meta = await backend.get_metadata("meta.txt")
            assert meta.metadata == {"custom": "data", "version": "1.0"}

    async def test_list_files(self, db_session: AsyncSession):
        from openagent.core.storage import LocalStorageBackend
        import tempfile
        
        with tempfile.TemporaryDirectory() as tmpdir:
            backend = LocalStorageBackend(tmpdir)
            
            # Upload multiple files
            for i in range(5):
                content = f"File {i}".encode()
                await backend.upload(
                    key=f"file{i}.txt",
                    file=io.BytesIO(content),
                    content_type="text/plain",
                    filename=f"file{i}.txt",
                )
            
            files = await backend.list_files(limit=10, offset=0)
            assert len(files) == 5
            
            # Test pagination
            files_page1 = await backend.list_files(limit=2, offset=0)
            files_page2 = await backend.list_files(limit=2, offset=2)
            
            assert len(files_page1) == 2
            assert len(files_page2) == 2
            assert files_page1[0].key != files_page2[0].key


class TestFileUploadService:
    async def test_create_upload(self, db_session: AsyncSession, org, user, file_upload_service):
        from fastapi import UploadFile
        import io
        
        # Create mock upload file
        content = b"Test file content"
        file = UploadFile(
            filename="test.txt",
            file=io.BytesIO(b"Test file content"),
        )
        file.content_type = "text/plain"
        
        upload = await file_upload_service.create_upload(
            organization_id=org.id,
            user_id=user.id,
            file=file,
        )
        
        assert upload.id is not None
        assert upload.original_filename == "test.txt"
        assert upload.content_type == "text/plain"
        assert upload.size == len(b"Test file content")
        assert upload.status == FileUploadStatus.PENDING
        assert upload.checksum == hashlib.sha256(b"Test file content").hexdigest()
    
    async def test_create_upload_invalid_type(self, db_session: AsyncSession, org, user, file_upload_service):
        from fastapi import UploadFile
        import io
        
        file = UploadFile(
            filename="test.exe",
            file=io.BytesIO(b"executable"),
        )
        file.content_type = "application/x-msdownload"
        
        with pytest.raises(Exception) as exc_info:
            await file_upload_service.create_upload(
                organization_id=org.id,
                user_id=user.id,
                file=file,
            )
        
        assert exc_info.value.status_code == 400
        assert exc_info.value.detail["code"] == "INVALID_FILE_TYPE"
    
    async def test_create_upload_invalid_extension(self, db_session: AsyncSession, org, user, file_upload_service):
        from fastapi import UploadFile
        import io
        
        file = UploadFile(
            filename="test.exe",
            file=io.BytesIO(b"executable"),
        )
        file.content_type = "application/octet-stream"
        
        with pytest.raises(Exception) as exc_info:
            await file_upload_service.create_upload(
                organization_id=org.id,
                user_id=user.id,
                file=file,
            )
        
        assert exc_info.value.status_code == 400
        assert exc_info.value.detail["code"] == "INVALID_FILE_EXTENSION"
    
    async def test_create_upload_too_large(self, db_session: AsyncSession, org, user, file_upload_service):
        from fastapi import UploadFile
        import io
        
        # Create a file larger than max size
        large_content = b"x" * (101 * 1024 * 1024)  # 101MB
        file = UploadFile(
            filename="large.txt",
            file=io.BytesIO(large_content),
        )
        file.content_type = "text/plain"
        
        with pytest.raises(Exception) as exc_info:
            await file_upload_service.create_upload(
                organization_id=org.id,
                user_id=user.id,
                file=file,
            )
        
        assert exc_info.value.status_code == 413
        assert exc_info.value.detail["code"] == "FILE_TOO_LARGE"
    
    async def test_complete_upload(self, db_session: AsyncSession, org, user, file_upload_service):
        from fastapi import UploadFile
        import io
        
        # Create upload
        file = UploadFile(
            filename="complete.txt",
            file=io.BytesIO(b"Initial"),
        )
        file.content_type = "text/plain"
        
        upload = await file_upload_service.create_upload(
            organization_id=org.id,
            user_id=user.id,
            file=file,
        )
        
        # Complete upload
        content = b"Complete file content for testing"
        complete_file = UploadFile(
            filename="complete.txt",
            file=io.BytesIO(content),
        )
        complete_file.content_type = "text/plain"
        
        completed = await file_upload_service.complete_upload(
            upload_id=upload.id,
            file_content=content,
        )
        
        assert completed.status == FileUploadStatus.COMPLETED
        assert completed.size == len(content)
    
    async def test_get_download_url(self, db_session: AsyncSession, org, user, file_upload_service):
        # Create and complete upload
        file = UploadFile(
            filename="download.txt",
            file=io.BytesIO(b"Download test"),
        )
        file.content_type = "text/plain"
        
        upload = await file_upload_service.create_upload(
            organization_id=org.id,
            user_id=user.id,
            file=file,
        )
        
        content = b"Download test content"
        await file_upload_service.complete_upload(
            upload_id=upload.id,
            file_content=content,
        )
        
        # Get download URL
        url = await file_upload_service.get_download_url(upload.id)
        
        assert url is not None
        assert "download" in url or "presigned" in url or "signed" in url
    
    async def test_delete_upload(self, db_session: AsyncSession, org, user, file_upload_service):
        file = UploadFile(
            filename="delete.txt",
            file=io.BytesIO(b"Delete test"),
        )
        file.content_type = "text/plain"
        
        upload = await file_upload_service.create_upload(
            organization_id=org.id,
            user_id=user.id,
            file=file,
        )
        
        content = b"Delete test content"
        await file_upload_service.complete_upload(
            upload_id=upload.id,
            file_content=content,
        )
        
        success = await file_upload_service.delete_upload(upload.id)
        assert success is True
        
        # Verify deleted
        deleted_upload = await file_upload_service.get_upload(upload.id)
        assert deleted_upload is None
    
    async def test_cleanup_expired(self, db_session: AsyncSession, org, user, file_upload_service):
        from openagent.db.models import FileUpload
        
        # Create expired upload
        expired = FileUpload(
            organization_id=org.id,
            user_id=user.id,
            filename="expired.txt",
            original_filename="expired.txt",
            content_type="text/plain",
            size=100,
            checksum="abc123",
            storage_provider="local",
            storage_key="expired.txt",
            status=FileUploadStatus.PENDING,
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        db_session.add(expired)
        await db_session.commit()
        
        # Create non-expired
        valid = FileUpload(
            organization_id=org.id,
            user_id=user.id,
            filename="valid.txt",
            original_filename="valid.txt",
            content_type="text/plain",
            size=100,
            checksum="def456",
            storage_provider="local",
            storage_key="valid.txt",
            status=FileUploadStatus.PENDING,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        db_session.add(valid)
        await db_session.commit()
        
        # Cleanup
        file_upload_service.config.expires_in_hours = 1
        deleted = await file_upload_service.cleanup_expired()
        
        assert deleted == 1
        
        # Verify valid upload still exists
        result = await db_session.execute(
            select(FileUpload).where(FileUpload.id == valid.id)
        )
        assert result.scalar_one_or_none() is not None