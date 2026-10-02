"""Evaluator metrics (MP20). Lightweight in-process counters, mirroring the
approvals metrics module. No external dependency."""

from __future__ import annotations

import threading

_counters: dict[str, int] = {}
_lock = threading.Lock()

METRICS = ("evaluations_total", "evaluations_passed", "evaluations_failed",
           "evaluations_uncertain", "evaluations_error",
           "deterministic_checks_total", "deterministic_checks_passed",
           "llm_votes_total", "disagreements_total",
           "corrections_total", "corrections_succeeded", "corrections_stopped",
           "retries_total", "human_reviews_total", "feedback_total",
           "evaluation_latency_ms_sum", "evaluation_latency_ms_count",
           "evaluation_cost_sum_micros", "benchmark_runs_total")


def inc(metric: str, amount: int = 1) -> None:
    if metric not in METRICS:
        raise ValueError(f"Unknown evaluator metric {metric}")
    with _lock:
        _counters[metric] = _counters.get(metric, 0) + amount


def snapshot() -> dict[str, int]:
    with _lock:
        return {m: _counters.get(m, 0) for m in METRICS}
