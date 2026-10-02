"""Connector metrics (MP21). Mirrors approvals/evaluator metric modules."""

from __future__ import annotations

import threading

_counters: dict[str, int] = {}
_lock = threading.Lock()

METRICS = ("connector_calls_total", "connector_success_total",
           "connector_failure_total", "connector_latency_ms_sum",
           "connector_rate_limited_total", "connector_auth_failures_total",
           "connector_webhook_events_total", "connector_trigger_events_total",
           "connector_retry_total", "approval_gates_total",
           "evaluation_hooks_total", "circuit_opens_total")


def inc(metric: str, amount: int = 1) -> None:
    if metric not in METRICS:
        raise ValueError(f"Unknown connector metric {metric}")
    with _lock:
        _counters[metric] = _counters.get(metric, 0) + amount


def snapshot() -> dict[str, int]:
    with _lock:
        return {m: _counters.get(m, 0) for m in METRICS}
