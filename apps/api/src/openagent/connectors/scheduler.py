"""Polling scheduler wiring (MP21).

Polling triggers run as bounded `connector_poll` scheduled jobs on the
EXISTING scheduler (no second scheduler, no uncontrolled loops). Each tick
runs one bounded cycle per due connection, persists the cursor, and
publishes new items as normalized connector events.
"""

from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from openagent.connectors import metrics as connector_metrics
from openagent.connectors.polling import PollCursor, run_poll_cycle

logger = structlog.get_logger("openagent.connectors.scheduler")

JOB_TYPE = "connector_poll"


def register_poll_handler(scheduler: Any, db_factory: Any) -> None:
    """Register the poll handler on a SchedulerService instance."""
    scheduler.register_handler(JOB_TYPE, lambda payload:
                               _handle_poll_job(db_factory, payload))


async def _handle_poll_job(db_factory: Any, payload: dict[str, Any]) -> dict[str, Any]:
    async with db_factory() as db:
        return await run_due_polls(
            db, organization_id=UUID(payload["organization_id"]),
            connection_id=UUID(payload["connection_id"])
            if payload.get("connection_id") else None,
            trigger_id=str(payload.get("trigger_id", "")))


async def ensure_poll_job(db: AsyncSession, *, organization_id: UUID,
                          connection_id: UUID, trigger_id: str,
                          interval_seconds: int = 300) -> Any:
    """Create (or reuse) an interval scheduler job for a polling trigger."""
    from openagent.connectors.config import ConnectorSettings
    from openagent.core.scheduler import (
        ScheduleConfig, ScheduleTriggerType, SchedulerService,
    )
    floor = ConnectorSettings().CONNECTOR_POLL_MIN_INTERVAL
    interval = max(int(interval_seconds or floor), floor)
    service = SchedulerService(db)
    existing = await service.list_jobs(organization_id, job_type=JOB_TYPE,
                                       limit=100)
    for job in existing:
        payload = job.payload or {}
        if str(payload.get("connection_id")) == str(connection_id) and \
                str(payload.get("trigger_id")) == trigger_id:
            return job
    return await service.create_job(
        organization_id=organization_id,
        name=f"connector-poll:{connection_id}:{trigger_id}",
        job_type=JOB_TYPE,
        payload={"organization_id": str(organization_id),
                 "connection_id": str(connection_id),
                 "trigger_id": trigger_id},
        config=ScheduleConfig(trigger_type=ScheduleTriggerType.INTERVAL,
                              interval_seconds=interval),
        description=f"Poll {trigger_id}")


async def run_due_polls(db: AsyncSession, *, organization_id: UUID,
                        connection_id: Optional[UUID] = None,
                        trigger_id: str = "") -> dict[str, Any]:
    """Run one bounded poll cycle for due polling cursors. Safe to call from
    a scheduler tick or the manual poll endpoint."""
    from openagent.connectors.engine import ConnectorEngine
    from openagent.connectors.registry import registry
    from openagent.connectors.providers import provider_ids, register_official
    from openagent.db.models.connector import ConnectorConnection, ConnectorCursor
    if not provider_ids():
        register_official()
    query = select(ConnectorConnection).where(
        ConnectorConnection.organization_id == organization_id)
    if connection_id is not None:
        query = query.where(ConnectorConnection.id == connection_id)
    connections = (await db.execute(query)).scalars().all()
    engine = ConnectorEngine(db)
    processed = 0
    new_events = 0
    for connection in connections:
        manifest = registry.get(str(connection.connector_id))
        if manifest is None:
            continue
        triggers = [t for t in manifest.triggers if t.kind.value == "polling"]
        if trigger_id:
            triggers = [t for t in triggers if t.id == trigger_id]
        for trigger in triggers:
            cursor_row = (await db.execute(select(ConnectorCursor).where(
                ConnectorCursor.connection_id == connection.id,
                ConnectorCursor.trigger_id == trigger.id))).scalar_one_or_none()
            if cursor_row is None:
                cursor_row = ConnectorCursor(
                    connection_id=connection.id,
                    organization_id=organization_id,
                    trigger_id=trigger.id, state={})
                db.add(cursor_row)
                await db.flush()
            cursor = PollCursor.from_dict(dict(cursor_row.state or {}))
            poll_cfg = trigger.poll_config or {}

            async def _fetch(params: dict[str, Any],
                             _connection=connection,
                             _trigger=trigger) -> list[dict[str, Any]]:
                return await _poll_fetch(engine=engine, connection=_connection,
                                         trigger=_trigger, params=params,
                                         organization_id=organization_id)

            _fetch.parked = False  # type: ignore[attr-defined]

            result = await run_poll_cycle(
                cursor=cursor, fetch=_fetch,
                max_items=int((poll_cfg or {}).get("max_items", 100) or 100))
            if getattr(_fetch, "parked", False):
                # Approval-parked reads are not empty provider cycles; don't
                # inflate empty backoff.
                result.cursor.consecutive_empty = 0
                result.cursor.backoff_until_epoch = 0.0
            cursor_row.state = result.cursor.to_dict()
            processed += 1
            for item in result.new_items:
                await _store_poll_event(db, connection=connection,
                                        trigger=trigger, item=item,
                                        organization_id=organization_id)
                new_events += 1
            _ = poll_cfg
    await db.commit()
    connector_metrics.inc("connector_trigger_events_total", new_events)
    return {"processed": processed, "new_events": new_events}


async def _poll_fetch(*, engine: Any, connection: Any, trigger: Any,
                      params: dict[str, Any],
                      organization_id: UUID) -> list[dict[str, Any]]:
    """Default fetch: list/read action declared in trigger poll_config.

    poll_config: {"action": "<connector.action>", "params": {...},
                  "items_path": "result.items", "id_path": "id"}.
    """
    from openagent.connectors.mapping import resolve_path
    poll_cfg = trigger.poll_config or {}
    action_id = str(poll_cfg.get("action", ""))
    if not action_id:
        return []
    from openagent.connectors.types import ConnectorExecutionContext
    poll_ctx = ConnectorExecutionContext(
        organization_id=str(organization_id),
        connector_id=str(connection.connector_id),
        connection_id=str(connection.id),
        policy_context={"poll": True, "trigger_id": str(trigger.id)})
    outcome = await engine.execute_action(
        connector_id=str(connection.connector_id), action_id=action_id,
        connection_id=connection.id, organization_id=organization_id,
        arguments=dict(poll_cfg.get("params", {}) or {}),
        context=poll_ctx, approval_id=None)
    if outcome.get("status") == "WAITING_FOR_APPROVAL":
        _poll_fetch.parked = True  # type: ignore[attr-defined]
        return []  # gated reads park; the cycle simply yields nothing
    result = outcome.get("result", {}) or {}
    items = resolve_path(result, str(poll_cfg.get("items_path", "items")))
    id_path = str(poll_cfg.get("id_path", "id"))
    normalized = []
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict):
            item = dict(item)
            item.setdefault("id", resolve_path(item, id_path, ""))
            normalized.append(item)
    return normalized


async def _store_poll_event(db: AsyncSession, *, connection: Any,
                            trigger: Any, item: dict[str, Any],
                            organization_id: UUID) -> None:
    from openagent.connectors.resources import normalize
    from openagent.db.models.connector import ConnectorEvent
    kind = str((trigger.poll_config or {}).get("resource_kind", "task"))
    record = normalize(kind, str(connection.connector_id), item)
    event = ConnectorEvent(
        webhook_id=None, connection_id=connection.id,
        organization_id=organization_id, event_type=f"{trigger.id}.polled",
        provider=str(connection.connector_id),
        resource_id=str(record.get("provider_id", ""))[:256],
        delivery_id=f"poll:{trigger.id}:{record.get('provider_id', '')}"[:128],
        attributes={"resource": record})
    db.add(event)
    try:
        from openagent.core.events import EventService
        await EventService(db).publish(
            f"connector.{event.event_type}", "connector_event", event.id,
            {"provider": event.provider, "resource_id": event.resource_id},
            organization_id=organization_id)
    except Exception as exc:
        logger.warning("poll event publish skipped", error=str(exc))
