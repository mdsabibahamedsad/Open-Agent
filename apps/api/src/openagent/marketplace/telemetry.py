"""MP23: marketplace metrics (thin counters, same pattern as MP22)."""

from __future__ import annotations

_counters: dict[str, float] = {}


def inc(metric: str, amount: float = 1.0) -> float:
    """Increment a marketplace-domain counter; returns the new value."""
    _counters[metric] = _counters.get(metric, 0.0) + amount
    try:
        from openagent.core.logging import get_logger

        get_logger("openagent.marketplace.metrics").info(
            "marketplace metric", metric=metric, value=_counters[metric]
        )
    except Exception:
        pass
    return _counters[metric]


def snapshot() -> dict[str, float]:
    return dict(_counters)
