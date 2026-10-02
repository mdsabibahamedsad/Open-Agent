"""Marketplace worker: analytics aggregation, notification fan-out,
artifact verification and listing rescans for MP23.

Logical queue ``marketplace`` shares the Redis infrastructure with the
other workers. Jobs are idempotent: aggregation upserts daily rows,
notification fan-out skips already-notified recipients via idempotency
markers in metadata, verification recomputes from stored bytes.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict
from uuid import UUID

import redis.asyncio as redis
import structlog

from worker.base import BaseWorker
from worker.config import WorkerSettings
from worker.queue import Job, RetryPolicy

logger = structlog.get_logger("worker.marketplace")

MARKETPLACE_JOB_TYPES = (
    "marketplace.aggregate",
    "marketplace.notify",
    "marketplace.verify_artifact",
    "marketplace.rescan",
)


class MarketplaceWorker(BaseWorker):
    """Worker that processes marketplace background jobs."""

    def __init__(
        self,
        settings: WorkerSettings,
        redis_client: redis.Redis,
        queue_name: str = "marketplace",
    ):
        super().__init__(
            settings,
            redis_client,
            queue_name,
            RetryPolicy(max_attempts=3, base_delay_seconds=5.0,
                        max_delay_seconds=300.0),
        )
        import uuid as _uuid

        self.worker_id = f"marketplace_worker_{_uuid.uuid4().hex[:8]}"

    async def process_job(self, job: Job) -> Dict[str, Any]:
        if job.type == "marketplace.aggregate":
            return await self._aggregate(job)
        if job.type == "marketplace.notify":
            return await self._notify(job)
        if job.type == "marketplace.verify_artifact":
            return await self._verify_artifact(job)
        if job.type == "marketplace.rescan":
            return await self._rescan(job)
        raise ValueError(f"Unknown marketplace job type: {job.type}")

    async def _session(self):
        from openagent.db.session import get_db

        db_gen = get_db()
        db = await db_gen.__anext__()
        return db_gen, db

    async def _aggregate(self, job: Job) -> Dict[str, Any]:
        """Roll raw marketplace_events into daily counters (idempotent)."""
        from sqlalchemy import func, select

        from openagent.db.models.marketplace import (
            AnalyticsEventType,
            MarketplaceAnalyticsDaily,
            MarketplaceEvent,
        )

        payload = job.payload or {}
        day_str = payload.get("day") or datetime.now(timezone.utc).date().isoformat()
        db_gen, db = await self._session()
        try:
            rows = (await db.execute(select(
                MarketplaceEvent.listing_id, MarketplaceEvent.event_type,
                func.count(MarketplaceEvent.id)).where(
                    func.date(MarketplaceEvent.created_at) == day_str,
                    MarketplaceEvent.listing_id.is_not(None))
                .group_by(MarketplaceEvent.listing_id,
                          MarketplaceEvent.event_type))).all()
            by_listing: Dict[str, Dict[str, int]] = {}
            for listing_id, event_type, count in rows:
                bucket = by_listing.setdefault(str(listing_id), {})
                bucket[str(event_type)] = int(count)
            column_map = {
                AnalyticsEventType.VIEW.value: "views",
                AnalyticsEventType.CLICK.value: "clicks",
                AnalyticsEventType.INSTALL_STARTED.value: "installs_started",
                AnalyticsEventType.INSTALL_COMPLETED.value: "installs_completed",
                AnalyticsEventType.INSTALL_FAILED.value: "installs_failed",
                AnalyticsEventType.UPDATE.value: "updates",
                AnalyticsEventType.UNINSTALL.value: "uninstalls",
                AnalyticsEventType.FAVORITE.value: "favorites",
                AnalyticsEventType.SHARE.value: "shares",
                AnalyticsEventType.REVIEW.value: "reviews",
            }
            touched = 0
            for listing_id, counts in by_listing.items():
                existing = (await db.execute(select(MarketplaceAnalyticsDaily).where(
                    MarketplaceAnalyticsDaily.listing_id == UUID(listing_id),
                    func.date(MarketplaceAnalyticsDaily.day) == day_str
                ))).scalar_one_or_none()
                if existing is None:
                    existing = MarketplaceAnalyticsDaily(
                        listing_id=UUID(listing_id), day=day_str)
                    db.add(existing)
                    await db.flush()
                for event_name, count in counts.items():
                    column = column_map.get(event_name)
                    if column:
                        setattr(existing, column, count)
                touched += 1
            await db.commit()
            return {"day": day_str, "listings": touched}
        finally:
            await db.close()

    async def _notify(self, job: Job) -> Dict[str, Any]:
        """Fan-out notifications with per-recipient idempotency markers."""
        from sqlalchemy import select

        from openagent.db.models.marketplace import MarketplaceNotification
        from openagent.marketplace import notifications as notif_module

        payload = job.payload or {}
        notif_type = str(payload.get("type", ""))
        title = str(payload.get("title", ""))[:255]
        body = str(payload.get("body", ""))[:2000]
        recipients = [str(u) for u in (payload.get("user_ids") or [])]
        marker = str(payload.get("idempotency_marker", ""))
        listing_id = payload.get("listing_id")
        publisher_id = payload.get("publisher_id")
        organization_id = payload.get("organization_id")
        if not notif_type or not title or not recipients:
            raise ValueError("type, title and user_ids required")
        db_gen, db = await self._session()
        try:
            created = 0
            skipped = 0
            for uid in dict.fromkeys(recipients)[:1000]:
                if marker:
                    dup = (await db.execute(select(MarketplaceNotification).where(
                        MarketplaceNotification.user_id == UUID(uid),
                        MarketplaceNotification.type == notif_type,
                        MarketplaceNotification.title == title,
                    ))).scalar_one_or_none()
                    # Idempotency: same marker payload already delivered.
                    if dup is not None and marker in (dup.body or ""):
                        skipped += 1
                        continue
                db.add(MarketplaceNotification(
                    user_id=UUID(uid),
                    organization_id=UUID(organization_id) if organization_id else None,
                    type=notif_type,  # type: ignore[arg-type]
                    title=title, body=f"{body}\n[{marker}]" if marker else body,
                    listing_id=UUID(listing_id) if listing_id else None,
                    publisher_id=UUID(publisher_id) if publisher_id else None))
                created += 1
            await db.commit()
            _ = notif_module.DEFAULT_PREFS  # prefs honored by API fan-out path
            return {"created": created, "skipped": skipped}
        finally:
            await db.close()

    async def _verify_artifact(self, job: Job) -> Dict[str, Any]:
        """Re-verify a stored artifact from bytes (hash + archive safety)."""
        from sqlalchemy import select

        from openagent.db.models.marketplace import (
            ArtifactStatus, DistributionArtifact,
        )
        from openagent.marketplace.distribution import (
            LocalArtifactStorage, sha256_bytes, verify_archive,
        )

        payload = job.payload or {}
        artifact_id = payload.get("artifact_id")
        if not artifact_id:
            raise ValueError("artifact_id required")
        db_gen, db = await self._session()
        try:
            row = await db.get(DistributionArtifact, UUID(artifact_id))
            if row is None:
                raise ValueError("artifact not found")
            row.status = ArtifactStatus.VERIFYING
            await db.flush()
            stored = await LocalArtifactStorage().get(row.storage_key)
            problems: list[str] = []
            if stored is None:
                problems.append("artifact bytes missing from storage")
            elif sha256_bytes(stored) != row.sha256:
                problems.append("hash mismatch: storage corruption")
            elif row.artifact_type.value == "PACKAGE_ARCHIVE":
                problems.extend(
                    verify_archive(stored, filename=row.filename)["problems"])
            if problems:
                row.status = ArtifactStatus.REJECTED
                row.artifact_metadata = {**(row.artifact_metadata or {}),
                                         "reverify_problems": problems[:10]}
            else:
                row.status = ArtifactStatus.VERIFIED
                row.verified_at = datetime.now(timezone.utc)
            await db.commit()
            return {"status": row.status.value, "problems": problems[:10]}
        finally:
            await db.close()

    async def _rescan(self, job: Job) -> Dict[str, Any]:
        """Re-run the MP22 security scan for a listing's current version."""
        from sqlalchemy import select

        from openagent.db.models.marketplace import MarketplaceListing
        from openagent.db.models.package import PackageVersion
        from openagent.packages import security as security_module

        payload = job.payload or {}
        listing_id = payload.get("listing_id")
        if not listing_id:
            raise ValueError("listing_id required")
        db_gen, db = await self._session()
        try:
            listing = await db.get(MarketplaceListing, UUID(listing_id))
            if listing is None or not listing.published_version_id:
                raise ValueError("listing or published version not found")
            version = await db.get(PackageVersion, listing.published_version_id)
            if version is None:
                raise ValueError("package version not found")
            findings = security_module.scan_manifest_dict(
                dict(version.manifest or {}))
            risk = security_module.risk_level(findings)
            listing.security_status = risk
            await db.commit()
            return {"risk": risk, "findings": len(findings)}
        finally:
            await db.close()
