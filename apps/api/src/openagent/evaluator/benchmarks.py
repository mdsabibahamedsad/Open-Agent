"""Benchmark abstraction + regression detection (MP20).

Benchmarks are data (tasks, datasets, expected outcomes, criteria) — never
hard-coded datasets. Runs execute items through a caller-supplied callback so
the engine stays runtime-agnostic; regression compares the new run against a
baseline run.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Optional
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from openagent.evaluator.scoring import normalize_score

logger = structlog.get_logger("openagent.evaluator.benchmarks")

REGRESSION_FLOOR = 0.05  # score drops beyond this count as regressions


class BenchmarkError(Exception):
    def __init__(self, message: str, code: str = "BENCHMARK_ERROR"):
        super().__init__(message)
        self.code = code


def detect_regression(*, baseline: dict[str, Any], current: dict[str, Any],
                      floor: float = REGRESSION_FLOOR,
                      keys: Optional[list[str]] = None) -> dict[str, Any]:
    watched = keys or sorted(set(baseline) & set(current))
    regressions: list[str] = []
    for key in watched:
        base, now = baseline.get(key), current.get(key)
        if isinstance(base, (int, float)) and isinstance(now, (int, float)):
            if float(now) < float(base) - floor:
                regressions.append(f"{key}: {base} -> {now}")
    return {"regressed": bool(regressions), "regressions": regressions}


async def run_benchmark(*, db: AsyncSession, organization_id: UUID,
                        benchmark_id: UUID,
                        execute_item: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]],
                        baseline_run_id: Optional[UUID] = None,
                        score_keys: Optional[list[str]] = None) -> dict[str, Any]:
    """Execute every dataset item, aggregate normalized scores, compare."""
    from openagent.db.models.evaluation import Benchmark, BenchmarkRun
    result = await db.execute(select(Benchmark).where(Benchmark.id == benchmark_id))
    benchmark = result.scalar_one_or_none()
    if benchmark is None or benchmark.organization_id != organization_id:
        raise BenchmarkError("Benchmark not found", code="NOT_FOUND")
    dataset = list(benchmark.dataset or [])
    run = BenchmarkRun(benchmark_id=benchmark.id, organization_id=organization_id,
                       status="running", scores={}, items=[],
                       baseline_run_id=baseline_run_id, regression={})
    db.add(run)
    await db.flush()
    items: list[dict[str, Any]] = []
    totals: dict[str, float] = {}
    counts: dict[str, int] = {}
    failed = 0
    for index, item in enumerate(dataset):
        try:
            outcome = await execute_item(dict(item) if isinstance(item, dict) else {"item": item})
        except Exception as exc:
            failed += 1
            items.append({"index": index, "status": "error",
                          "error": str(exc)[:500]})
            continue
        scores = {k: normalize_score(v) for k, v in (outcome.get("scores", {}) or {}).items()}
        items.append({"index": index, "status": "ok", "scores": scores,
                      "evaluation_id": outcome.get("evaluation_id")})
        for key, value in scores.items():
            totals[key] = totals.get(key, 0.0) + value
            counts[key] = counts.get(key, 0) + 1
    aggregate = {k: round(totals[k] / counts[k], 4) for k in totals}
    aggregate["items_total"] = len(dataset)
    aggregate["items_failed"] = failed
    regression: dict[str, Any] = {"regressed": False, "regressions": []}
    if baseline_run_id:
        base = (await db.execute(
            select(BenchmarkRun).where(BenchmarkRun.id == baseline_run_id))).scalar_one_or_none()
        if base is not None and base.organization_id == organization_id:
            regression = detect_regression(
                baseline=dict(base.scores or {}), current=aggregate,
                keys=score_keys)
    run.status = "completed"
    run.scores = aggregate
    run.items = items
    run.regression = regression
    await db.flush()
    try:
        from openagent.db.models.audit_log import AuditLog
        db.add(AuditLog(organization_id=organization_id, actor_user_id=None,
                        action="benchmark.completed", resource_type="benchmark",
                        resource_id=run.id,
                        metadata={"benchmark_id": str(benchmark_id),
                                  "scores": aggregate}))
        await db.flush()
    except Exception as exc:  # pragma: no cover - audit best-effort
        logger.warning("benchmark audit skipped", error=str(exc))
    return {"run_id": str(run.id), "status": run.status, "scores": aggregate,
            "regression": regression, "items": len(items)}
