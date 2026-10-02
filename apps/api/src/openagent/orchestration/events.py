"""Orchestration observability: events + in-memory metrics."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import UUID

_metrics = Counter()


def record_metric(name: str, amount: int = 1) -> None:
    _metrics[name] += amount


def get_metrics() -> Dict[str, int]:
    return dict(_metrics)


ORCHESTRATION_METRIC_NAMES = [
    "orchestrations_total",
    "orchestrations_success_total",
    "orchestrations_failed_total",
    "tasks_total",
    "tasks_completed_total",
    "tasks_failed_total",
    "agent_runs_total",
    "agent_failures_total",
    "delegations_total",
    "handoffs_total",
]


@dataclass
class OrchestrationEvent:
    event_type: str
    orchestration_run_id: str
    task_id: Optional[str] = None
    agent_id: Optional[str] = None
    payload: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


async def publish_event(
    db: Any,
    *,
    event_type: str,
    organization_id: Optional[UUID],
    aggregate_id: UUID,
    payload: Optional[Dict[str, Any]] = None,
) -> None:
    """Persist to the existing outbox (core.events.Event) for durable delivery."""
    from openagent.core.events import Event as OutboxEvent

    outbox = OutboxEvent(
        event_type=event_type,
        aggregate_type="orchestration_run",
        aggregate_id=aggregate_id,
        organization_id=organization_id,
        payload=payload or {},
        metadata={"source": "orchestration"},
    )
    db.add(outbox)
