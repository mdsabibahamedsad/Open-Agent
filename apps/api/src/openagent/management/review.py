"""Manager review: structured results, acceptance verification, revision loop.

Quality evaluation stays extensible — the full Evaluator/Self-Correction
subsystem (MP20) plugs in via ReviewProvider / QualityGate / EvaluationHook.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from openagent.management.types import (
    AcceptanceCriterion,
    QualityGateResult,
    ReviewStatus,
)


@dataclass
class CriterionResult:
    description: str
    satisfied: bool
    evidence: str = ""


@dataclass
class ReviewResult:
    status: ReviewStatus
    criteria_results: List[CriterionResult] = field(default_factory=list)
    issues: List[str] = field(default_factory=list)
    required_changes: List[str] = field(default_factory=list)
    evidence: List[str] = field(default_factory=list)
    reviewer_agent_id: Optional[str] = None
    revision_number: int = 0


def verify_acceptance(
    criteria: List[AcceptanceCriterion],
    output: Dict[str, Any],
    *,
    reviewer_agent_id: Optional[str] = None,
    revision_number: int = 0,
) -> ReviewResult:
    """Verify output against acceptance criteria. Never rely on
    'agent says it is done': each criterion needs output evidence."""
    results: List[CriterionResult] = []
    issues: List[str] = []
    required_changes: List[str] = []
    blob = str(output)
    for criterion in criteria:
        verification = (criterion.verification or "").strip().lower()
        satisfied = False
        evidence = ""
        if verification.startswith("output_contains:"):
            needle = verification.split(":", 1)[1].strip()
            satisfied = needle in blob.lower()
            evidence = f"output_contains '{needle}': {satisfied}"
        elif verification in ("", "manual"):
            # No automatic check available: mark unsatisfied so a reviewer
            # (manager agent or human) must explicitly approve.
            satisfied = False
            evidence = "requires explicit reviewer approval"
        elif verification.startswith("field_present:"):
            needle = verification.split(":", 1)[1].strip()
            satisfied = needle in output
            evidence = f"field_present '{needle}': {satisfied}"
        else:
            satisfied = False
            evidence = f"unknown verification '{criterion.verification}'"
        results.append(
            CriterionResult(description=criterion.description, satisfied=satisfied, evidence=evidence)
        )
        if not satisfied:
            issues.append(f"unmet criterion: {criterion.description}")
            required_changes.append(criterion.description)
    if all(r.satisfied for r in results):
        status = ReviewStatus.APPROVED
    else:
        # Never auto-reject on first pass: the worker gets a bounded revision
        # loop; explicit rejection is a reviewer decision (status_override).
        status = ReviewStatus.REVISION_REQUIRED
    return ReviewResult(
        status=status,
        criteria_results=results,
        issues=issues,
        required_changes=required_changes,
        evidence=[r.evidence for r in results],
        reviewer_agent_id=reviewer_agent_id,
        revision_number=revision_number,
    )


@dataclass
class RevisionState:
    revision_number: int = 0
    max_revisions: int = 3

    def can_revise(self) -> bool:
        return self.revision_number < self.max_revisions

    def next(self) -> "RevisionState":
        return RevisionState(revision_number=self.revision_number + 1, max_revisions=self.max_revisions)


class ReviewProvider(ABC):
    """MP20 boundary: advanced quality evaluation plugs in here."""

    @abstractmethod
    async def review(
        self, *, output: Dict[str, Any], criteria: List[AcceptanceCriterion],
        context: Optional[Dict[str, Any]] = None,
    ) -> ReviewResult:
        ...


class QualityGate(ABC):
    """MP20 boundary: pass/revision/fail gate around task output."""

    @abstractmethod
    async def evaluate(
        self, *, output: Dict[str, Any], review: ReviewResult,
    ) -> QualityGateResult:
        ...


class EvaluationHook(ABC):
    """MP20 boundary: called after gate evaluation for learning signals."""

    @abstractmethod
    async def on_evaluation(
        self, *, output: Dict[str, Any], review: ReviewResult, gate: QualityGateResult,
    ) -> None:
        ...


class RuleBasedQualityGate(QualityGate):
    """Default gate: pass when approved, revision when changes requested,
    fail when rejected."""

    async def evaluate(self, *, output: Dict[str, Any], review: ReviewResult) -> QualityGateResult:
        if review.status == ReviewStatus.APPROVED:
            return QualityGateResult.PASS
        if review.status == ReviewStatus.REJECTED:
            return QualityGateResult.FAIL
        return QualityGateResult.REVISION
