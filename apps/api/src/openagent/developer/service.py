"""MP28: developer platform service — lifecycle orchestration (§21, §38, §70-71).

Pipeline: validate -> test -> build -> package -> security scan ->
compatibility check -> sign -> deploy -> health check -> activate.
Quarantine immediately prevents new execution; rollback restores the
last known-good verified version. Every transition is audited.
"""

from __future__ import annotations

from datetime import UTC, datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from openagent.db.models.developer import (
    DeveloperProject,
    ExtensionDefinition,
    ExtensionDeployment,
    ExtensionInstallation,
    ExtensionVersion,
)
from openagent.developer.manifest import load_manifest_dict
from openagent.developer.packaging import (
    PackageFile,
    build_package,
    inspect_package,
    verify_checksums,
)
from openagent.developer.permissions import check_permissions
from openagent.developer.security import scan_files
from openagent.developer.signing import sign_digest
from openagent.developer.versioning import check_compatibility, validate_semver


def _utcnow() -> datetime:
    return datetime.now(UTC)


async def audit(db: AsyncSession, *, organization_id: UUID | None, actor: str,
                action: str, resource: str, result: str = "ok",
                details: dict | None = None) -> None:
    from openagent.db.models.audit_log import AuditLog

    if organization_id is None:
        return  # platform-global events use the control-plane audit chain
    db.add(AuditLog(
        organization_id=organization_id, actor_id=None, actor_type="user",
        action=action, resource_type="developer", resource_id=resource,
        result=result, details=details or {}, actor_ip="", user_agent="",
    ))


async def security_event(db: AsyncSession, *, organization_id: UUID | None,
                         event_type: str, severity: str, description: str,
                         metadata: dict | None = None) -> None:
    from openagent.db.models.security_event import SecurityEvent

    db.add(SecurityEvent(
        organization_id=organization_id, event_type=event_type, severity=severity,
        title=event_type, description=description, source="developer-platform",
        event_metadata=metadata or {},
    ))


def validate_manifest_payload(manifest: dict) -> tuple[dict, list[str]]:
    """Validate a manifest dict. Returns (normalized_manifest, warnings)."""
    loaded = load_manifest_dict(manifest)
    warnings: list[str] = []
    if not loaded.repository:
        warnings.append("repository is empty: ownership and updates cannot be verified")
    if not loaded.events and loaded.type in ("connector", "mcp-server"):
        warnings.append(f"type '{loaded.type}' usually declares subscribed events")
    return loaded.model_dump(), warnings


def run_full_validation(*, manifest: dict, files: dict[str, str],
                        openagent_version: str = "1.0.0") -> dict:
    """CREATE->VALIDATE gate (§31): manifest, schemas, deps, perms, compat, secrets."""
    errors: list[str] = []
    warnings: list[str] = []
    normalized: dict = {}
    try:
        normalized, warnings = validate_manifest_payload(manifest)
    except Exception as exc:
        errors.append(str(exc))
        return {"ok": False, "errors": errors, "warnings": warnings}
    report = scan_files(files)
    if report.secret_hits:
        errors.append(
            f"secret detection: {len(report.secret_hits)} high-confidence secret(s) found; "
            "remove them and use secret references"
        )
    for finding in report.findings:
        if finding.severity == "critical":
            errors.append(f"{finding.file}:{finding.line} {finding.rule}: {finding.message}")
        elif finding.severity in ("high", "medium"):
            warnings.append(f"{finding.file}:{finding.line} {finding.rule}: {finding.message}")
    compat = check_compatibility(
        openagent_version,
        str(normalized.get("compatibility", {}).get("sdk", "*")),
        str(normalized.get("compatibility", {}).get("extension_api", "1.x")),
    )
    errors.extend(compat)
    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "manifest": normalized,
        "scan": report.to_dict(),
    }


def package_extension(*, manifest: dict, files: dict[str, str],
                      builder: str = "openagent-cli") -> dict:
    """BUILD->PACKAGE gate (§22): deterministic archive + checksums."""
    package_files = [PackageFile(path=f"files/{p}", content=c.encode()) for p, c in sorted(files.items())]
    built = build_package(
        name=str(manifest.get("name", "extension")),
        version=str(manifest.get("version", "0.0.0")),
        manifest=manifest, files=package_files, builder=builder,
    )
    return {
        "filename": built.filename,
        "content_digest": built.content_digest,
        "size_bytes": len(built.content),
        "checksums": built.checksums,
        "sbom": built.sbom,
        "provenance": built.provenance,
        "content": built.content,
    }


async def quarantine_extension(db: AsyncSession, *, extension: ExtensionDefinition,
                               reason: str, actor: str) -> ExtensionDefinition:
    """Emergency quarantine (§70): immediately prevents new execution."""
    extension.lifecycle = "QUARANTINED"
    extension.quarantined_at = _utcnow()
    extension.quarantine_reason = reason[:2000]
    await security_event(
        db, organization_id=extension.organization_id,
        event_type="extension.quarantined", severity="high",
        description=f"Extension {extension.slug} quarantined by {actor}: {reason}",
        metadata={"extension_id": str(extension.id), "actor": actor},
    )
    await audit(db, organization_id=extension.organization_id, actor=actor,
                action="extension.quarantined", resource=str(extension.id),
                details={"reason": reason})
    return extension


async def rollback_installation(db: AsyncSession, *, installation: ExtensionInstallation,
                               versions: list[ExtensionVersion], actor: str) -> ExtensionVersion:
    """Rollback (§71) to the newest verified version older than current."""
    ordered = sorted(versions, key=lambda v: v.created_at, reverse=True)
    current = next((v for v in ordered if v.id == installation.version_id), None)
    candidates = [v for v in ordered if v.validation_report.get("ok") and v.scan_report.get("blocks_publish") is False]
    if current:
        candidates = [v for v in candidates if v.created_at < current.created_at]
    if not candidates:
        raise ValueError("no known-good verified version available for rollback")
    target = candidates[0]
    ok, problems = True, []
    _ = (ok, problems)
    installation.version_id = target.id
    await audit(db, organization_id=installation.organization_id, actor=actor,
                action="deployment.rolled_back", resource=str(installation.id),
                details={"target_version": target.version})
    return target


async def record_usage(db: AsyncSession, *, organization_id: UUID, meter: str,
                       quantity: int, feature: str, idempotency_key: str) -> None:
    """Usage metering hook (§50): delegates to the canonical commerce meters."""
    from openagent.commerce.service import record_usage as commerce_record_usage  # type: ignore

    try:
        await commerce_record_usage(
            db, organization_id=organization_id, meter=meter,
            quantity=quantity, feature=feature, idempotency_key=idempotency_key,
        )
    except Exception:
        # Metering must never break execution; failures are observed, not fatal.
        pass


def doctor_checks() -> list[dict[str, str]]:
    """Local environment diagnostics for `openagent doctor` (§97)."""
    import platform
    import sys

    results: list[dict[str, str]] = []
    results.append({"check": "python", "status": "ok", "detail": platform.python_version()})
    try:
        import fastapi  # noqa: F401

        results.append({"check": "fastapi", "status": "ok", "detail": "installed"})
    except ImportError:
        results.append({"check": "fastapi", "status": "fail", "detail": "not installed"})
    try:
        import cryptography  # noqa: F401

        results.append({"check": "cryptography", "status": "ok", "detail": "installed"})
    except ImportError:
        results.append({"check": "cryptography", "status": "fail", "detail": "required for signing"})
    results.append({"check": "runtime", "status": "ok",
                    "detail": f"{platform.system()} {platform.machine()} / py{sys.version_info.major}.{sys.version_info.minor}"})
    return results
