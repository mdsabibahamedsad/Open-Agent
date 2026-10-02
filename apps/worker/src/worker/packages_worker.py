"""Packages worker: background validation, security scans, installs,
updates, rollbacks and export builds for MP22 reusable packages.

Logical queue ``packages`` shares the Redis infrastructure with the other
workers. Crash recovery: on startup the worker marks installations stuck in
transitional states FAILED (safe — installs are idempotent and
transactional, so a retry resumes cleanly); interrupted updates keep their
previous version intact.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict
from uuid import UUID

import redis.asyncio as redis
import structlog

from worker.base import BaseWorker
from worker.config import WorkerSettings
from worker.queue import Job, RetryPolicy

logger = structlog.get_logger("worker.packages")

PACKAGE_JOB_TYPES = (
    "package.validate",
    "package.security_scan",
    "package.install",
    "package.update",
    "package.rollback",
    "package.export_build",
    "package.recover",
)


class PackagesWorker(BaseWorker):
    """Worker that processes reusable-package jobs."""

    def __init__(
        self,
        settings: WorkerSettings,
        redis_client: redis.Redis,
        queue_name: str = "packages",
    ):
        super().__init__(
            settings,
            redis_client,
            queue_name,
            RetryPolicy(max_attempts=3, base_delay_seconds=5.0,
                        max_delay_seconds=300.0),
        )
        self.worker_id = f"packages_worker_{uuid.uuid4().hex[:8]}"

    async def process_job(self, job: Job) -> Dict[str, Any]:
        if job.type == "package.validate":
            return await self._validate(job)
        if job.type == "package.security_scan":
            return await self._security_scan(job)
        if job.type == "package.install":
            return await self._install(job)
        if job.type == "package.update":
            return await self._update(job)
        if job.type == "package.rollback":
            return await self._rollback(job)
        if job.type == "package.export_build":
            return await self._export_build(job)
        if job.type == "package.recover":
            return await self._recover(job)
        raise ValueError(f"Unknown packages job type: {job.type}")

    async def _session(self):
        from openagent.db.session import get_db

        db_gen = get_db()
        db = await db_gen.__anext__()
        return db_gen, db

    async def _validate(self, job: Job) -> Dict[str, Any]:
        from openagent.db.models.package import (
            PackageValidationResult,
            PackageVersion,
            PackageVersionStatus,
        )
        from openagent.packages import telemetry, validation as validation_module

        payload = job.payload or {}
        version_id = payload.get("version_id")
        if not version_id:
            raise ValueError("version_id required")
        db_gen, db = await self._session()
        try:
            row = await db.get(PackageVersion, UUID(version_id))
            if row is None:
                raise ValueError("package version not found")
            row.status = PackageVersionStatus.VALIDATING
            await db.flush()
            report = validation_module.validate_package(dict(row.manifest or {}))
            db.add(PackageValidationResult(
                version_id=row.id, passed=report["passed"],
                findings=report["findings"], stages=report["stages"]))
            row.status = (PackageVersionStatus.VALIDATED if report["passed"]
                          else PackageVersionStatus.DRAFT)
            telemetry.inc("package_validation_total")
            if not report["passed"]:
                telemetry.inc("package_validation_failed_total")
            await db.commit()
            return {"passed": report["passed"], "risk": report["risk"],
                    "findings": len(report["findings"])}
        finally:
            await db.close()

    async def _security_scan(self, job: Job) -> Dict[str, Any]:
        from openagent.db.models.package import PackageSecurityScan, PackageVersion
        from openagent.packages import security as security_module
        from openagent.packages import telemetry

        payload = job.payload or {}
        version_id = payload.get("version_id")
        if not version_id:
            raise ValueError("version_id required")
        db_gen, db = await self._session()
        try:
            row = await db.get(PackageVersion, UUID(version_id))
            if row is None:
                raise ValueError("package version not found")
            findings = security_module.scan_manifest_dict(dict(row.manifest or {}))
            risk = security_module.risk_level(findings)
            db.add(PackageSecurityScan(
                version_id=row.id, risk=risk, findings=findings,
                scanner_version="1"))
            row.risk = risk
            await db.commit()
            await telemetry.emit(
                db, event_type="SECURITY_SCAN_COMPLETED",
                aggregate_id=row.package_id, payload={"risk": risk})
            await db.commit()
            return {"risk": risk, "findings": len(findings)}
        finally:
            await db.close()

    async def _install(self, job: Job) -> Dict[str, Any]:
        from openagent.packages import installer

        payload = job.payload or {}
        for key in ("organization_id", "version_id"):
            if not payload.get(key):
                raise ValueError(f"{key} required")
        db_gen, db = await self._session()
        try:
            installation = await installer.install(
                db, organization_id=UUID(payload["organization_id"]),
                version_id=UUID(payload["version_id"]),
                installed_by=UUID(payload["installed_by"])
                if payload.get("installed_by") else None,
                values=payload.get("values", {}),
                idempotency_key=payload.get("idempotency_key", ""))
            return {"installation_id": str(installation.id),
                    "status": installation.status.value}
        finally:
            await db.close()

    async def _update(self, job: Job) -> Dict[str, Any]:
        from openagent.packages import installer

        payload = job.payload or {}
        for key in ("organization_id", "installation_id", "to_version_id"):
            if not payload.get(key):
                raise ValueError(f"{key} required")
        db_gen, db = await self._session()
        try:
            plan = await installer.plan_update(
                db, installation_id=UUID(payload["installation_id"]),
                to_version_id=UUID(payload["to_version_id"]),
                organization_id=UUID(payload["organization_id"]))
            if payload.get("auto_apply") and not plan.breaking:
                updated = await installer.apply_update(
                    db, installation_id=UUID(payload["installation_id"]),
                    organization_id=UUID(payload["organization_id"]),
                    approved_by=UUID(payload["approved_by"])
                    if payload.get("approved_by") else None)
                return {"plan_id": str(plan.id),
                        "status": updated.status.value}
            return {"plan_id": str(plan.id), "breaking": plan.breaking,
                    "status": plan.status}
        finally:
            await db.close()

    async def _rollback(self, job: Job) -> Dict[str, Any]:
        from openagent.packages import installer

        payload = job.payload or {}
        for key in ("organization_id", "installation_id"):
            if not payload.get(key):
                raise ValueError(f"{key} required")
        db_gen, db = await self._session()
        try:
            rolled = await installer.rollback(
                db, installation_id=UUID(payload["installation_id"]),
                organization_id=UUID(payload["organization_id"]),
                actor=UUID(payload["actor"]) if payload.get("actor") else None)
            return {"installation_id": str(rolled.id),
                    "status": rolled.status.value}
        finally:
            await db.close()

    async def _export_build(self, job: Job) -> Dict[str, Any]:
        from openagent.db.models.package import PackageVersion
        from openagent.packages import packaging

        payload = job.payload or {}
        version_id = payload.get("version_id")
        if not version_id:
            raise ValueError("version_id required")
        db_gen, db = await self._session()
        try:
            row = await db.get(PackageVersion, UUID(version_id))
            if row is None:
                raise ValueError("package version not found")
            files = packaging.build_export_files(dict(row.manifest or {}))
            return {"files": len(files),
                    "manifest_hash": files["integrity.json"][:64]}
        finally:
            await db.close()

    async def _recover(self, job: Job) -> Dict[str, Any]:
        """Mark interrupted installations FAILED (idempotent retry is safe)."""
        from sqlalchemy import select

        from openagent.db.models.package import (
            InstallationResource,  # noqa: F401 (keeps model registered)
            PackageInstallation,
            PackageInstallStatus,
        )

        db_gen, db = await self._session()
        try:
            stuck = (await db.execute(select(PackageInstallation).where(
                PackageInstallation.status.in_([
                    PackageInstallStatus.REQUESTED,
                    PackageInstallStatus.RESOLVING,
                    PackageInstallStatus.VALIDATING,
                    PackageInstallStatus.INSTALLING,
                    PackageInstallStatus.VERIFYING,
                    PackageInstallStatus.UPDATING,
                    PackageInstallStatus.ROLLING_BACK,
                ])))).scalars().all()
            count = 0
            for installation in stuck:
                # Installations mid-rollback keep their previous version; only
                # the status marker needs repair.
                if installation.status == PackageInstallStatus.ROLLING_BACK:
                    installation.status = PackageInstallStatus.INSTALLED
                else:
                    installation.status = PackageInstallStatus.FAILED
                    if not installation.error:
                        installation.error = (
                            "worker interrupted; safe to retry "
                            f"(failed at {datetime.now(timezone.utc).isoformat()})")
                count += 1
            await db.commit()
            return {"recovered": count}
        finally:
            await db.close()

    async def start(self) -> None:
        # Crash recovery first: repair interrupted installations, then serve.
        await self._recover(Job(type="package.recover", payload={}))
        await super().start()
