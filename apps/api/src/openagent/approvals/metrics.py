"""Approval metrics (MP19). Lightweight in-process counters; the API exposes
them for scraping alongside existing observability. No external dependency."""

from __future__ import annotations

import threading

_counters: dict[str, int] = {}
_lock = threading.Lock()

METRICS = ("approval_requests_total", "approval_pending", "approval_approved_total",
           "approval_rejected_total", "approval_expired_total", "approval_escalation_total",
           "policy_denials_total", "high_risk_actions_total", "approval_latency_ms_sum",
           "approval_latency_ms_count")


def inc(metric: str, amount: int = 1) -> None:
    if metric not in METRICS:
        raise ValueError(f"Unknown approval metric {metric}")
    with _lock:
        _counters[metric] = _counters.get(metric, 0) + amount


def snapshot() -> dict[str, int]:
    with _lock:
        return {m: _counters.get(m, 0) for m in METRICS}
