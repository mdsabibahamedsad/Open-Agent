"""Evaluation criteria + versioned rubric engine (MP20).

Criteria are declarative data (never executable code). Rubrics group weighted
criteria; rubric versions make historical results reproducible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from openagent.evaluator.types import Criterion

RUBRIC_VERSION = "rubric-v1"


@dataclass
class Rubric:
    name: str
    criteria: list[Criterion] = field(default_factory=list)
    quality_threshold: float = 0.7
    confidence_threshold: float = 0.6
    version: str = RUBRIC_VERSION

    def required(self) -> list[Criterion]:
        return [c for c in self.criteria if c.required]


def parse_criteria(raw: Any) -> list[Criterion]:
    """Validate raw criteria payloads into Criterion objects."""
    if raw is None:
        return []
    if isinstance(raw, dict):
        raw = raw.get("criteria", raw.get("requirements", []))
    if isinstance(raw, list) and raw and isinstance(raw[0], str):
        return [Criterion(name=f"requirement-{i}", description=text)
                for i, text in enumerate(raw)]
    if not isinstance(raw, list):
        raise ValueError("criteria must be a list")
    out: list[Criterion] = []
    for i, item in enumerate(raw):
        if isinstance(item, str):
            out.append(Criterion(name=f"requirement-{i}",
                                 description=item[:2000]))
            continue
        if not isinstance(item, dict):
            raise ValueError(f"criteria[{i}] must be an object")
        name = str(item.get("name") or item.get("description") or f"criterion-{i}")[:200]
        try:
            weight = float(item.get("weight", 1.0))
            minimum = float(item.get("minimum_score", 0.0))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"criteria[{i}] has non-numeric weight/minimum") from exc
        if weight < 0 or minimum < 0 or minimum > 1:
            raise ValueError(f"criteria[{i}] has out-of-range weight/minimum")
        out.append(Criterion(
            name=name, description=str(item.get("description", ""))[:2000],
            weight=weight, minimum_score=minimum,
            required=bool(item.get("required", True)),
            method=str(item.get("method", "deterministic"))[:100],
            params=dict(item.get("params", {}) or {})))
    return out


def parse_goal_block(raw: Any) -> dict[str, Any]:
    """Normalize {goal, requirements, constraints, success/failure conditions...}."""
    if not isinstance(raw, dict):
        return {"goal": str(raw or "")}
    out = {"goal": str(raw.get("goal", ""))[:4000],
           "requirements": [str(r)[:1000] for r in (raw.get("requirements") or [])],
           "constraints": [str(c)[:1000] for c in (raw.get("constraints") or [])],
           "success_conditions": [str(s)[:1000] for s in (raw.get("success_conditions") or [])],
           "failure_conditions": [str(f)[:1000] for f in (raw.get("failure_conditions") or [])],
           "expected_output_schema": raw.get("expected_output_schema") or {},
           "quality_threshold": float(raw.get("quality_threshold", 0.7)),
           "safety_requirements": [str(s)[:1000] for s in (raw.get("safety_requirements") or [])],
           "format_requirements": [str(s)[:1000] for s in (raw.get("format_requirements") or [])]}
    try:
        out["quality_threshold"] = min(1.0, max(0.0, float(out["quality_threshold"])))
    except (TypeError, ValueError):
        out["quality_threshold"] = 0.7
    return out


# Built-in rubric library (versioned; org rubrics live in DB).
BUILTIN_RUBRICS: dict[str, Rubric] = {
    "research_quality": Rubric(
        name="Research Quality",
        criteria=[
            Criterion("accuracy", "Claims supported by cited evidence",
                      weight=3.0, minimum_score=0.6, method="llm"),
            Criterion("completeness", "All requirements addressed",
                      weight=2.0, minimum_score=0.5, method="llm"),
            Criterion("source_quality", "Sources credible and traceable",
                      weight=2.0, minimum_score=0.5, method="llm"),
            Criterion("relevance", "Answer relevant to the goal",
                      weight=2.0, minimum_score=0.6, method="llm"),
            Criterion("instruction_adherence", "Output follows instructions/format",
                      weight=1.0, minimum_score=0.5, method="llm"),
        ],
        quality_threshold=0.7),
    "code_quality": Rubric(
        name="Code Quality",
        criteria=[
            Criterion("build_passes", "Build/lint/typecheck green",
                      weight=3.0, minimum_score=1.0, method="test_summary"),
            Criterion("tests_pass", "Unit + integration tests pass",
                      weight=3.0, minimum_score=1.0, method="test_summary"),
            Criterion("no_secrets", "No secret-like content in diff",
                      weight=3.0, minimum_score=1.0, method="secret_scan",
                      params={}),
            Criterion("diff_reviewed", "Diff reviewed against requirements",
                      weight=1.0, minimum_score=0.5, method="llm"),
        ],
        quality_threshold=0.8),
    "browser_completion": Rubric(
        name="Browser Completion",
        criteria=[
            Criterion("expected_url", "Reached expected URL/state",
                      weight=3.0, minimum_score=1.0, method="browser_state"),
            Criterion("success_indicator", "Page shows success indicator",
                      weight=2.0, minimum_score=0.6, method="browser_state"),
            Criterion("no_challenge", "No unresolved CAPTCHA/login wall",
                      weight=2.0, minimum_score=1.0, method="browser_state"),
        ],
        quality_threshold=0.75),
    "structured_output": Rubric(
        name="Structured Output",
        criteria=[
            Criterion("schema_valid", "Output validates against schema",
                      weight=3.0, minimum_score=1.0, method="json_schema"),
            Criterion("required_fields", "All required fields present",
                      weight=2.0, minimum_score=1.0, method="json_schema"),
        ],
        quality_threshold=0.9),
    "tool_side_effect": Rubric(
        name="Tool Side Effect",
        criteria=[
            Criterion("provider_success", "Provider returned success",
                      weight=2.0, minimum_score=1.0, method="http_response"),
            Criterion("side_effect_verified", "Side effect independently verified",
                      weight=3.0, minimum_score=1.0, method="side_effect"),
        ],
        quality_threshold=0.8),
}


def get_rubric(name: str) -> Optional[Rubric]:
    return BUILTIN_RUBRICS.get((name or "").lower())


def list_rubrics() -> list[str]:
    return sorted(BUILTIN_RUBRICS)


def weighted_score(criterion_scores: dict[str, float], rubric: Rubric) -> float:
    """Weighted mean over criteria that reported scores (missing = 0)."""
    total_w = 0.0
    total = 0.0
    for criterion in rubric.criteria:
        total_w += criterion.weight
        total += criterion.weight * min(1.0, max(0.0, criterion_scores.get(criterion.name, 0.0)))
    if total_w <= 0:
        return 0.0
    return round(total / total_w, 4)
