"""MP22: metrics, audit and event helpers (thin adapters).

Metrics reuse the in-process counters via structlog-friendly increments so
Prometheus scraping keeps working without a new pipeline. Audit entries
reuse the existing ``audit_logs`` table (never logging secret values).
Events reuse the outbox ``EventService`` with the ``package`` aggregate.
"""

from __future__ import annotations

import uuid
from collections import Counter
from typing import Any

_counters: Counter[str] = Counter()


def inc(metric: str, amount: float = 1.0) -> float:
    """Increment a package-domain counter; returns the new value."""
    _counters[metric] += amount
    try:  # best-effort bridge into structlog when configured
        from openagent.core.logging import get_logger

        get_logger("openagent.packages.metrics").info(
            "package metric", metric=metric, value=_counters[metric]
        )
    except Exception:
        pass
    return _counters[metric]


def snapshot() -> dict[str, float]:
    return dict(_counters)


async def audit(
    db,
    *,
    organization_id,
    actor_user_id,
    action: str,
    resource_id=None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Write an audit row, stripping anything that looks secret-bearing."""
    from openagent.db.models.audit_log import AuditLog

    safe_meta = dict(metadata or {})
    for key in ("configuration", "values", "inputs"):
        if isinstance(safe_meta.get(key), dict):
            safe_meta[key] = {
                name: ("<redacted>" if "secret" in str(name).lower()
                       or "token" in str(name).lower()
                       or "password" in str(name).lower() else value)
                for name, value in safe_meta[key].items()
            }
    db.add(
        AuditLog(
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            action=action,
            resource_type="package",
            resource_id=resource_id,
            metadata=safe_meta,
        )
    )
    await db.flush()


async def emit(
    db,
    *,
    event_type: str,
    aggregate_id,
    organization_id=None,
    user_id=None,
    payload: dict[str, Any] | None = None,
) -> None:
    """Publish a package-domain event through the outbox (best effort)."""
    try:
        from openagent.core.events import EventService

        service = EventService(db)
        await service.publish(
            event_type=event_type,
            aggregate_type="package",
            aggregate_id=aggregate_id
            if isinstance(aggregate_id, uuid.UUID)
            else uuid.UUID(str(aggregate_id)),
            payload=payload or {},
            organization_id=organization_id,
            user_id=user_id,
        )
    except Exception:
        # Event delivery must never break the primary transaction path;
        # the outbox row is a side effect, not the commit itself.
        pass
