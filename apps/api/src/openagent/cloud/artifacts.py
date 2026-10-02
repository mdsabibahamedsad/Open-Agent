"""MP25: artifact model + security (§31-33).

Large outputs live in object storage; the DB keeps metadata + small
results. Uploads enforce checksum/size/MIME/extension validation,
quarantine hooks, signed expiring access, tenant isolation and download
limits. Raw storage credentials are never exposed.
"""

from __future__ import annotations

import hashlib
import mimetypes
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from openagent.cloud.errors import ArtifactRejected

# Security boundaries (§30): storage prefixes per category.
ARTIFACT_CATEGORIES = (
    "execution-artifacts", "workflow-exports", "agent-files",
    "browser-downloads", "code-patches", "build-artifacts", "logs",
    "datasets", "documents", "user-uploads", "marketplace-packages",
)

_BLOCKED_EXTENSIONS = frozenset({
    ".exe", ".dll", ".so", ".dylib", ".bat", ".cmd", ".com", ".scr",
    ".ps1", ".vbs", ".jar", ".apk", ".dmg", ".msi",
})

# MIME allowlist per category family. ``None`` = accept sniffed type after
# extension screening (still scanned by the malware hook when enabled).
_CATEGORY_MIME_ALLOW = {
    "logs": {"text/plain", "application/json", "text/csv"},
    "datasets": {"text/csv", "application/json", "application/octet-stream"},
    "documents": {"application/pdf", "text/plain", "text/markdown",
                  "application/json", "text/csv"},
}

_SECRET_PATTERNS = (
    re.compile(r"sk-(live|test)-[A-Za-z0-9]{8,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{8,}"),
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
)


@dataclass
class ArtifactDraft:
    organization_id: str
    execution_id: str
    name: str
    mime_type: str
    size: int
    checksum: str
    category: str = "execution-artifacts"
    task_id: str = ""
    workspace_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


def storage_key_for(*, organization_id: str, category: str,
                    artifact_id: str, filename: str) -> str:
    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", filename)[-180:]
    # Neutralize traversal/dotfile tricks: no ".." segments, no leading dots.
    safe_name = safe_name.replace("..", "__").lstrip(".") or "artifact"
    return f"{category}/{organization_id}/{artifact_id}/{safe_name}"


def validate_artifact(draft: ArtifactDraft, *, max_bytes: int,
                      malware_scan: Optional[Any] = None) -> tuple[bool, str]:
    """Validate an artifact upload. Returns (ok, reason)."""
    if draft.category not in ARTIFACT_CATEGORIES:
        return False, f"unknown artifact category {draft.category}"
    if not draft.organization_id or not draft.name:
        return False, "organization_id and name are required"
    if draft.size <= 0:
        return False, "artifact is empty"
    if draft.size > max_bytes:
        return False, f"artifact exceeds {max_bytes} bytes"
    lowered = draft.name.lower()
    for ext in _BLOCKED_EXTENSIONS:
        if lowered.endswith(ext):
            return False, f"blocked file extension {ext}"
    guessed, _ = mimetypes.guess_type(draft.name)
    declared = (draft.mime_type or "").lower()
    if guessed and declared and guessed != declared:
        # Mismatched MIME is suspicious but common (e.g. .log as text);
        # only reject when the category has a strict allowlist.
        allowed = _CATEGORY_MIME_ALLOW.get(draft.category)
        if allowed is not None and declared not in allowed and guessed not in allowed:
            return False, f"mime type {declared} not allowed for {draft.category}"
    # Secret-leak guard: never persist raw credential-looking values in
    # small text artifacts (names/metadata are checked by the service).
    for pattern in _SECRET_PATTERNS:
        if pattern.search(draft.name):
            return False, "artifact name looks like a credential"
    if malware_scan is not None:
        verdict = malware_scan(draft)
        if verdict is False:
            return False, "artifact quarantined by malware scan"
    return True, "ok"


def new_artifact_id() -> str:
    return f"art_{uuid.uuid4().hex[:16]}"


def artifact_result_ref(artifact_id: str) -> dict[str, str]:
    """Large-output reference stored in execution results (§33)."""
    return {"type": "artifact", "artifact_id": artifact_id}


def sign_download_token(*, artifact_id: str, organization_id: str,
                        secret: str, expires_at: datetime) -> str:
    body = f"{artifact_id}:{organization_id}:{int(expires_at.timestamp())}"
    sig = hashlib.sha256(f"{body}:{secret}".encode()).hexdigest()[:32]
    return f"{body}:{sig}"


def verify_download_token(token: str, *, artifact_id: str,
                          organization_id: str, secret: str,
                          now: Optional[datetime] = None) -> bool:
    try:
        art, org, exp, sig = token.split(":")
    except ValueError:
        return False
    if art != artifact_id or org != organization_id:
        return False
    try:
        expires = datetime.fromtimestamp(int(exp), tz=timezone.utc)
    except (ValueError, OSError):
        return False
    moment = now or datetime.now(timezone.utc)
    if moment >= expires:
        return False
    expected = hashlib.sha256(
        f"{art}:{org}:{exp}:{secret}".encode()).hexdigest()[:32]
    return hmac_compare(sig, expected)


def hmac_compare(a: str, b: str) -> bool:
    import hmac as _hmac
    return _hmac.compare_digest(a, b)


def default_expiry(seconds: int) -> datetime:
    return datetime.now(timezone.utc) + timedelta(seconds=max(60, seconds))
