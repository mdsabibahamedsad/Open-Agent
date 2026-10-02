"""MP25 unit: artifacts (validation, signed URLs) + object storage fakes."""

import hashlib
from datetime import datetime, timedelta, timezone

import pytest

from openagent.cloud.artifacts import (
    ArtifactDraft, artifact_result_ref, default_expiry,
    sign_download_token, storage_key_for, validate_artifact,
    verify_download_token,
)
from openagent.cloud.storage_cloud import FakeObjectStorageProvider


def _draft(**overrides):
    base = dict(organization_id="org-1", execution_id="cexe_1",
                name="report.json", mime_type="application/json",
                size=128, checksum="abc123", category="execution-artifacts")
    base.update(overrides)
    return ArtifactDraft(**base)


def test_valid_artifact_passes():
    ok, reason = validate_artifact(_draft(), max_bytes=1024)
    assert ok, reason


def test_oversize_rejected():
    ok, reason = validate_artifact(_draft(size=2048), max_bytes=1024)
    assert not ok and "exceeds" in reason


def test_blocked_extension_quarantined():
    ok, reason = validate_artifact(_draft(name="payload.exe"), max_bytes=65536)
    assert not ok and "blocked" in reason


def test_unknown_category_rejected():
    ok, _ = validate_artifact(_draft(category="nope"), max_bytes=65536)
    assert not ok


def test_empty_rejected():
    ok, _ = validate_artifact(_draft(size=0), max_bytes=65536)
    assert not ok


def test_storage_key_scoped_by_org_and_category():
    key = storage_key_for(organization_id="org-1", category="logs",
                          artifact_id="art_x", filename="../../evil.txt")
    assert key.startswith("logs/org-1/art_x/")
    assert ".." not in key


def test_result_ref_shape():
    assert artifact_result_ref("art_1") == {"type": "artifact", "artifact_id": "art_1"}


def test_signed_url_expiry_enforced():
    secret = "test-secret"
    expires = default_expiry(3600)
    token = sign_download_token(artifact_id="art_1", organization_id="org-1",
                                secret=secret, expires_at=expires)
    assert verify_download_token(token, artifact_id="art_1",
                                 organization_id="org-1", secret=secret)
    # Wrong tenant fails.
    assert not verify_download_token(token, artifact_id="art_1",
                                     organization_id="org-2", secret=secret)
    # Expired fails.
    future = datetime.now(timezone.utc) + timedelta(seconds=7200)
    assert not verify_download_token(token, artifact_id="art_1",
                                     organization_id="org-1", secret=secret,
                                     now=future)


@pytest.mark.asyncio
async def test_fake_storage_roundtrip_with_checksum():
    provider = FakeObjectStorageProvider()
    data = b'{"ok": true}'
    stored = await provider.put("execution-artifacts/org-1/art_1/report.json",
                                data, "application/json")
    assert stored.size == len(data)
    assert stored.checksum == hashlib.sha256(data).hexdigest()
    assert await provider.exists(stored.key)
    assert await provider.get(stored.key) == data
    meta = await provider.metadata(stored.key)
    assert meta is not None and meta.checksum == stored.checksum
    copied = await provider.copy(stored.key, stored.key + ".bak")
    assert await provider.get(copied.key) == data
    assert await provider.delete(stored.key) is True
    assert not await provider.exists(stored.key)


@pytest.mark.asyncio
async def test_fake_storage_list_prefix_isolation():
    provider = FakeObjectStorageProvider()
    await provider.put("execution-artifacts/org-A/a.txt", b"a", "text/plain")
    await provider.put("execution-artifacts/org-B/b.txt", b"b", "text/plain")
    items, _ = await provider.list(prefix="execution-artifacts/org-A/")
    assert [i.key for i in items] == ["execution-artifacts/org-A/a.txt"]
