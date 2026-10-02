"""Commerce worker: usage aggregation, entitlement expiry, webhook retry,
payout eligibility sweeps for MP24.

Logical queue ``commerce`` shares the Redis infrastructure with the other
workers. All jobs are idempotent: aggregation upserts summaries, expiry only
transitions ACTIVE/expired rows once, webhook retry reuses the persisted
event rows, payout sweeps only move PENDING -> ELIGIBLE when the ledger
says so.
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

logger = structlog.get_logger("worker.commerce")

COMMERCE_JOB_TYPES = (
    "commerce.aggregate_usage",
    "commerce.expire_entitlements",
    "commerce.retry_webhooks",
    "commerce.sweep_payouts",
)


class CommerceWorker(BaseWorker):
    """Worker that processes commerce background jobs."""

    def __init__(
        self,
        settings: WorkerSettings,
        redis_client: redis.Redis,
        queue_name: str = "commerce",
    ):
        super().__init__(
            settings,
            redis_client,
            queue_name,
            RetryPolicy(max_attempts=3, base_delay_seconds=5.0,
                        max_delay_seconds=300.0),
        )
        import uuid as _uuid

        self.worker_id = f"commerce_worker_{_uuid.uuid4().hex[:8]}"

    async def process_job(self, job: Job) -> Dict[str, Any]:
        if job.type == "commerce.aggregate_usage":
            return await self._aggregate_usage(job)
        if job.type == "commerce.expire_entitlements":
            return await self._expire_entitlements(job)
        if job.type == "commerce.retry_webhooks":
            return await self._retry_webhooks(job)
        if job.type == "commerce.sweep_payouts":
            return await self._sweep_payouts(job)
        raise ValueError(f"Unknown commerce job type: {job.type}")

    async def _session(self):
        from openagent.db.session import get_db

        db_gen = get_db()
        db = await db_gen.__anext__()
        return db_gen, db

    async def _aggregate_usage(self, job: Job) -> Dict[str, Any]:
        """Roll raw usage_records into usage_summaries (idempotent upsert)."""
        from sqlalchemy import func, select

        from openagent.db.models.commerce import (
            UsageMeter,
            UsageRecord,
            UsageSummary,
        )

        payload = job.payload or {}
        meter_slug = str(payload.get("meter", ""))
        period_start_raw = str(payload.get("period_start", ""))
        period_end_raw = str(payload.get("period_end", ""))
        db_gen, db = await self._session()
        try:
            meters = [meter_slug] if meter_slug else [
                m.slug for m in (await db.execute(
                    select(UsageMeter).where(UsageMeter.is_active == True)  # noqa: E712
                )).scalars().all()]
            if period_start_raw and period_end_raw:
                period_start = datetime.fromisoformat(period_start_raw)
                period_end = datetime.fromisoformat(period_end_raw)
            else:
                now = datetime.now(timezone.utc)
                period_start = now.replace(day=1, hour=0, minute=0,
                                           second=0, microsecond=0)
                period_end = now
            touched = 0
            for slug in meters:
                meter = (await db.execute(select(UsageMeter).where(
                    UsageMeter.slug == slug))).scalar_one_or_none()
                if meter is None:
                    continue
                rows = (await db.execute(select(
                    UsageRecord.organization_id, UsageRecord.user_id,
                    func.sum(UsageRecord.quantity)).where(
                        UsageRecord.meter_id == meter.id,
                        UsageRecord.occurred_at >= period_start,
                        UsageRecord.occurred_at < period_end)
                    .group_by(UsageRecord.organization_id,
                              UsageRecord.user_id))).all()
                for org_id, user_id, total in rows:
                    existing = (await db.execute(select(UsageSummary).where(
                        UsageSummary.meter_id == meter.id,
                        UsageSummary.organization_id == org_id,
                        UsageSummary.user_id == user_id,
                        UsageSummary.period_start == period_start
                    ))).scalar_one_or_none()
                    if existing is None:
                        db.add(UsageSummary(
                            organization_id=org_id, user_id=user_id,
                            meter_id=meter.id, period_start=period_start,
                            period_end=period_end, total=int(total or 0)))
                    else:
                        existing.total = int(total or 0)
                    touched += 1
            await db.commit()
            return {"meters": len(meters), "summaries": touched}
        finally:
            await db.close()

    async def _expire_entitlements(self, job: Job) -> Dict[str, Any]:
        """Expire ACTIVE commerce entitlements past valid_until (once each)."""
        from sqlalchemy import select

        from openagent.db.models.commerce import CommerceEntitlement

        db_gen, db = await self._session()
        try:
            now = datetime.now(timezone.utc)
            rows = (await db.execute(select(CommerceEntitlement).where(
                CommerceEntitlement.status.in_(["ACTIVE", "TRIAL"]),
                CommerceEntitlement.valid_until.is_not(None),
                CommerceEntitlement.valid_until < now
            ).limit(500))).scalars().all()
            for row in rows:
                row.status = "EXPIRED"
            await db.commit()
            return {"expired": len(rows)}
        finally:
            await db.close()

    async def _retry_webhooks(self, job: Job) -> Dict[str, Any]:
        """Report unprocessed billing webhooks (retry is driven by providers).

        Re-delivery itself comes from the provider; this job surfaces the
        backlog + dead-letters rows stuck after 5 attempts so operators can
        act without inventing financial outcomes.
        """
        from sqlalchemy import select

        from openagent.db.models.marketplace import BillingWebhookEvent

        db_gen, db = await self._session()
        try:
            rows = (await db.execute(select(BillingWebhookEvent).where(
                BillingWebhookEvent.processed == False  # noqa: E712
            ).limit(200))).scalars().all()
            dead = sum(1 for r in rows
                       if bool(getattr(r, "dead_letter", False)))
            return {"unprocessed": len(rows), "dead_letter": dead}
        finally:
            await db.close()

    async def _sweep_payouts(self, job: Job) -> Dict[str, Any]:
        """Move PENDING payouts to ELIGIBLE when the ledger covers them."""
        from sqlalchemy import select

        from openagent.commerce import ledger as ledger_lib
        from openagent.commerce.config import get_commerce_settings
        from openagent.db.models.commerce import (
            CommercePayout,
            CreatorLedgerEntry,
            PayoutEvent,
        )

        db_gen, db = await self._session()
        try:
            settings = get_commerce_settings()
            rows = (await db.execute(select(CommercePayout).where(
                CommercePayout.status == "PENDING").limit(200)
            )).scalars().all()
            moved = 0
            for payout in rows:
                entries = (await db.execute(select(CreatorLedgerEntry).where(
                    CreatorLedgerEntry.publisher_id == payout.publisher_id,
                    CreatorLedgerEntry.status == "POSTED"
                ))).scalars().all()
                balance = ledger_lib.ledger_balance(
                    [{"type": e.type, "amount_minor": e.amount_minor,
                      "currency": e.currency} for e in entries],
                    currency=payout.currency)
                eligible, _ = ledger_lib.payout_eligibility(
                    balance_minor=balance,
                    minimum_minor=settings.PAYOUT_MINIMUM_MINOR,
                    publisher_verified=False, require_verification=False)
                if eligible and balance >= payout.amount_minor:
                    payout.status = "ELIGIBLE"
                    db.add(PayoutEvent(
                        payout_id=payout.id, event_type="PAYOUT_ELIGIBLE",
                        actor_user_id=None,
                        payload={"balance_minor": balance}))
                    moved += 1
            await db.commit()
            return {"scanned": len(rows), "eligible": moved}
        finally:
            await db.close()
