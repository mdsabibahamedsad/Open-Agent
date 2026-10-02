"""Result aggregation and conflict representation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from openagent.orchestration.types import AggregationStrategy


@dataclass
class AgentResult:
    task_id: str
    agent_id: str | None
    output: Dict[str, Any]
    confidence: float = 1.0
    sources: List[str] = field(default_factory=list)


@dataclass
class Conflict:
    sources: List[str]
    claims: List[Any]
    evidence: List[Any]
    confidence: Dict[str, Any]
    resolution_status: str = "open"


def detect_conflicts(results: List[AgentResult]) -> List[Conflict]:
    """Naive conflict detector: differing scalar 'value'/'estimate' claims."""
    by_key: Dict[str, List[AgentResult]] = {}
    for r in results:
        for key in ("value", "estimate", "answer", "result"):
            if key in r.output:
                by_key.setdefault(key, []).append(r)
    conflicts: List[Conflict] = []
    for key, group in by_key.items():
        values = {str(g.output[key]) for g in group}
        if len(values) > 1:
            conflicts.append(
                Conflict(
                    sources=[g.agent_id or g.task_id for g in group],
                    claims=[{key: g.output[key], "task": g.task_id} for g in group],
                    evidence=[{"task": g.task_id, "sources": g.sources} for g in group],
                    confidence={g.task_id: g.confidence for g in group},
                )
            )
    return conflicts


def aggregate_results(
    strategy: AggregationStrategy,
    results: List[AgentResult],
) -> Dict[str, Any]:
    if not results:
        return {"status": "empty"}
    if strategy == AggregationStrategy.MERGE:
        merged: Dict[str, Any] = {"merged_from": [r.task_id for r in results]}
        for r in results:
            for key, value in r.output.items():
                if key not in merged:
                    merged[key] = value
                elif merged[key] != value:
                    merged.setdefault("_conflicts", []).append(
                        {"key": key, "task": r.task_id, "value": value}
                    )
        return merged
    if strategy == AggregationStrategy.SELECT:
        best = max(results, key=lambda r: r.confidence)
        return {"selected_task": best.task_id, "output": best.output}
    if strategy == AggregationStrategy.VALIDATE:
        conflicts = detect_conflicts(results)
        return {
            "valid": not conflicts,
            "results": [r.output for r in results],
            "conflicts": len(conflicts),
        }
    if strategy == AggregationStrategy.RECONCILE:
        conflicts = detect_conflicts(results)
        return {
            "reconciled": len(conflicts) == 0,
            "results": [r.output for r in results],
            "needs_review": bool(conflicts),
        }
    # SUMMARIZE default
    return {
        "summary_of": [r.task_id for r in results],
        "count": len(results),
        "outputs": [r.output for r in results],
    }
