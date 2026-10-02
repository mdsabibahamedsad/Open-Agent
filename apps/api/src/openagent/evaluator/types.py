"""Evaluator, verification & quality-control shared types (MP20).

Pure, dependency-light. DB enums live in db/models/evaluation.py and mirror
these. The evaluated agent's claim ("I succeeded") is never proof: only
observable, traceable evidence feeds decisions.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Optional


class EvaluationType(str, enum.Enum):
    TASK_SUCCESS = "TASK_SUCCESS"
    OUTPUT_QUALITY = "OUTPUT_QUALITY"
    FACTUALITY = "FACTUALITY"
    COMPLETENESS = "COMPLETENESS"
    CORRECTNESS = "CORRECTNESS"
    POLICY_COMPLIANCE = "POLICY_COMPLIANCE"
    TOOL_RESULT = "TOOL_RESULT"
    WORKFLOW_RESULT = "WORKFLOW_RESULT"
    CODE_QUALITY = "CODE_QUALITY"
    TEST_RESULT = "TEST_RESULT"
    BROWSER_RESULT = "BROWSER_RESULT"
    STRUCTURED_OUTPUT = "STRUCTURED_OUTPUT"
    FORMAT_COMPLIANCE = "FORMAT_COMPLIANCE"
    GOAL_COMPLETION = "GOAL_COMPLETION"
    SAFETY = "SAFETY"
    REGRESSION = "REGRESSION"
    CUSTOM = "CUSTOM"


# Registry for future evaluator types (org-defined kinds map onto CUSTOM).
_CUSTOM_EVAL_TYPES: set[str] = set()


def register_evaluation_type(name: str) -> str:
    normalized = (name or "").strip().upper()
    if not normalized or len(normalized) > 64:
        raise ValueError("Invalid evaluation type name")
    if not all(c.isalnum() or c == "_" for c in normalized):
        raise ValueError("Evaluation type must be alphanumeric/underscore")
    if normalized in {t.value for t in EvaluationType} or normalized in _CUSTOM_EVAL_TYPES:
        return normalized
    _CUSTOM_EVAL_TYPES.add(normalized)
    return normalized


def is_known_evaluation_type(name: str) -> bool:
    upper = (name or "").upper()
    return upper in {t.value for t in EvaluationType} or upper in _CUSTOM_EVAL_TYPES


class EvaluationStatus(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    UNCERTAIN = "UNCERTAIN"
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"
    ERROR = "ERROR"


# Strict lifecycle. Any transition not listed is rejected server-side.
# Historical terminal states are immutable: correct via a NEW evaluation.
ALLOWED_TRANSITIONS: dict[EvaluationStatus, frozenset[EvaluationStatus]] = {
    EvaluationStatus.PENDING: frozenset({
        EvaluationStatus.RUNNING, EvaluationStatus.SKIPPED,
        EvaluationStatus.CANCELLED}),
    EvaluationStatus.RUNNING: frozenset({
        EvaluationStatus.PASSED, EvaluationStatus.FAILED,
        EvaluationStatus.UNCERTAIN, EvaluationStatus.ERROR,
        EvaluationStatus.CANCELLED}),
    EvaluationStatus.PASSED: frozenset(),
    EvaluationStatus.FAILED: frozenset(),
    EvaluationStatus.UNCERTAIN: frozenset(),
    EvaluationStatus.SKIPPED: frozenset(),
    EvaluationStatus.CANCELLED: frozenset(),
    EvaluationStatus.ERROR: frozenset(),
}


def can_transition(frm: EvaluationStatus, to: EvaluationStatus) -> bool:
    return to in ALLOWED_TRANSITIONS.get(frm, frozenset())


TERMINAL_STATES = frozenset({
    EvaluationStatus.PASSED, EvaluationStatus.FAILED,
    EvaluationStatus.UNCERTAIN, EvaluationStatus.SKIPPED,
    EvaluationStatus.CANCELLED, EvaluationStatus.ERROR,
})


class EvaluationDecision(str, enum.Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    RETRY = "RETRY"
    CORRECT = "CORRECT"
    ESCALATE = "ESCALATE"
    REQUEST_HUMAN = "REQUEST_HUMAN"
    STOP = "STOP"


class EvidenceType(str, enum.Enum):
    TOOL_RESULT = "TOOL_RESULT"
    HTTP_RESPONSE = "HTTP_RESPONSE"
    DATABASE_STATE = "DATABASE_STATE"
    FILE_STATE = "FILE_STATE"
    GIT_STATE = "GIT_STATE"
    TEST_RESULT = "TEST_RESULT"
    BROWSER_STATE = "BROWSER_STATE"
    SCREENSHOT_REFERENCE = "SCREENSHOT_REFERENCE"
    DOM_STATE = "DOM_STATE"
    WORKFLOW_EVENT = "WORKFLOW_EVENT"
    AGENT_OUTPUT = "AGENT_OUTPUT"
    USER_FEEDBACK = "USER_FEEDBACK"
    APPROVAL_EVENT = "APPROVAL_EVENT"
    MODEL_RESPONSE = "MODEL_RESPONSE"
    STRUCTURED_OUTPUT = "STRUCTURED_OUTPUT"
    METRIC = "METRIC"
    LOG = "LOG"


class EvidenceTrust(str, enum.Enum):
    """Model claims are never equivalent to system-verified evidence."""
    SYSTEM_VERIFIED = "SYSTEM_VERIFIED"
    TOOL_VERIFIED = "TOOL_VERIFIED"
    EXTERNAL_VERIFIED = "EXTERNAL_VERIFIED"
    USER_CONFIRMED = "USER_CONFIRMED"
    MODEL_GENERATED = "MODEL_GENERATED"
    UNVERIFIED = "UNVERIFIED"


# Trust rank: higher wins when evidence conflicts (ties -> conservative).
TRUST_RANK: dict[EvidenceTrust, int] = {
    EvidenceTrust.SYSTEM_VERIFIED: 5,
    EvidenceTrust.TOOL_VERIFIED: 4,
    EvidenceTrust.EXTERNAL_VERIFIED: 4,
    EvidenceTrust.USER_CONFIRMED: 3,
    EvidenceTrust.MODEL_GENERATED: 1,
    EvidenceTrust.UNVERIFIED: 0,
}


class FailureClass(str, enum.Enum):
    TRANSIENT = "TRANSIENT"
    TOOL_ERROR = "TOOL_ERROR"
    NETWORK_ERROR = "NETWORK_ERROR"
    AUTH_ERROR = "AUTH_ERROR"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    MODEL_ERROR = "MODEL_ERROR"
    CONTEXT_ERROR = "CONTEXT_ERROR"
    PLANNING_ERROR = "PLANNING_ERROR"
    EXECUTION_ERROR = "EXECUTION_ERROR"
    DATA_ERROR = "DATA_ERROR"
    POLICY_ERROR = "POLICY_ERROR"
    SECURITY_ERROR = "SECURITY_ERROR"
    REQUIREMENT_MISMATCH = "REQUIREMENT_MISMATCH"
    QUALITY_FAILURE = "QUALITY_FAILURE"
    UNKNOWN = "UNKNOWN"


class CorrectionStrategy(str, enum.Enum):
    RETRY_SAME = "RETRY_SAME"
    RETRY_WITH_BACKOFF = "RETRY_WITH_BACKOFF"
    RETRY_WITH_NEW_MODEL = "RETRY_WITH_NEW_MODEL"
    RETRY_WITH_NEW_TOOL = "RETRY_WITH_NEW_TOOL"
    MODIFY_PARAMETERS = "MODIFY_PARAMETERS"
    REFINE_PROMPT = "REFINE_PROMPT"
    EXPAND_CONTEXT = "EXPAND_CONTEXT"
    REPLAN = "REPLAN"
    ROLLBACK = "ROLLBACK"
    ASK_ANOTHER_AGENT = "ASK_ANOTHER_AGENT"
    REQUEST_HUMAN = "REQUEST_HUMAN"
    STOP = "STOP"


class ConsensusOutcome(str, enum.Enum):
    AGREEMENT = "AGREEMENT"
    DISAGREEMENT = "DISAGREEMENT"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


@dataclass
class Criterion:
    """One checkable requirement. `method`: deterministic kind or 'llm'/'human'."""
    name: str
    description: str = ""
    weight: float = 1.0
    minimum_score: float = 0.0
    required: bool = True
    method: str = "deterministic"  # deterministic|<check-kind>|llm|human
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class EvidenceRecord:
    evidence_type: EvidenceType
    trust: EvidenceTrust
    content: dict[str, Any] = field(default_factory=dict)
    source: str = ""
    source_type: str = ""
    source_id: str = ""
    execution_id: str = ""
    tool_id: str = ""
    agent_id: str = ""
    content_hash: str = ""
    captured_at: str = ""


@dataclass
class CheckResult:
    """Outcome of one deterministic verification check."""
    name: str
    passed: bool
    reason: str = ""
    required: bool = True
    evidence_id: str = ""
    critical_safety: bool = False


@dataclass
class EvalScores:
    score: float  # 0.0..1.0 normalized
    confidence: float  # 0.0..1.0
    reason_codes: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)


@dataclass
class EvalDecision:
    decision: EvaluationDecision
    status: EvaluationStatus
    scores: EvalScores
    failure_class: FailureClass = FailureClass.UNKNOWN
    failure_reason: str = ""
    uncertainty_reason: str = ""
    correction_strategy: Optional[CorrectionStrategy] = None


@dataclass
class CorrectionBudget:
    max_attempts: int = 3
    max_correction_cycles: int = 3
    max_tokens: int = 50_000
    max_cost: float = 5.0
    max_time_seconds: int = 1800
    max_tool_calls: int = 50
    max_browser_actions: int = 30
    max_sandbox_executions: int = 20

    def to_dict(self) -> dict[str, Any]:
        return {"max_attempts": self.max_attempts,
                "max_correction_cycles": self.max_correction_cycles,
                "max_tokens": self.max_tokens, "max_cost": self.max_cost,
                "max_time_seconds": self.max_time_seconds,
                "max_tool_calls": self.max_tool_calls,
                "max_browser_actions": self.max_browser_actions,
                "max_sandbox_executions": self.max_sandbox_executions}
