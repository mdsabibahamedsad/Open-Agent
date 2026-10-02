"""MP20 evaluator & quality-control public surface."""

from openagent.evaluator.benchmarks import (
    REGRESSION_FLOOR,
    BenchmarkError,
    detect_regression,
    run_benchmark,
)
from openagent.evaluator.config import EvaluatorSettings
from openagent.evaluator.correction import (
    APPROVAL_STRATEGIES,
    CorrectionError,
    SelfCorrectionEngine,
    check_budget,
    classify_exception,
    default_strategy_for,
    failure_signature,
)
from openagent.evaluator.criteria import (
    BUILTIN_RUBRICS,
    RUBRIC_VERSION,
    Rubric,
    get_rubric,
    list_rubrics,
    parse_criteria,
    parse_goal_block,
    weighted_score,
)
from openagent.evaluator.deterministic import (
    VERIFIERS,
    run_check,
    validate_json_schema,
    verify_browser_state,
    verify_file_state,
    verify_git_state,
    verify_http,
    verify_output_contains,
    verify_secret_scan,
    verify_side_effect,
    verify_test_summary,
    verify_workflow_nodes,
)
from openagent.evaluator.engine import (
    EVALUATOR_VERSION,
    VERIFICATION_VERSION,
    CreateEvaluation,
    EvaluatorEngine,
    EvaluatorError,
)
from openagent.evaluator.evidence import (
    EvidenceCollector,
    classify_trust,
    content_hash,
    verify_content_hash,
)
from openagent.evaluator.gates import (
    BUILTIN_GATES,
    evaluate_gate,
    get_builtin_gate,
    list_builtin_gates,
    load_org_gates,
)
from openagent.evaluator.llm import (
    build_evaluation_prompt,
    check_evaluator_separation,
    frame_untrusted,
    parse_evaluator_output,
    run_llm_evaluation,
)
from openagent.evaluator.metrics import inc as metrics_inc
from openagent.evaluator.metrics import snapshot as metrics_snapshot
from openagent.evaluator.scoring import (
    combine_consensus,
    decide,
    normalize_score,
)
from openagent.evaluator.types import (
    ALLOWED_TRANSITIONS,
    TERMINAL_STATES,
    TRUST_RANK,
    CheckResult,
    ConsensusOutcome,
    CorrectionBudget,
    CorrectionStrategy,
    Criterion,
    EvalDecision,
    EvalScores,
    EvaluationDecision,
    EvaluationStatus,
    EvaluationType,
    EvidenceRecord,
    EvidenceTrust,
    EvidenceType,
    FailureClass,
    can_transition,
    is_known_evaluation_type,
    register_evaluation_type,
)

__all__ = [
    "EvaluationType", "EvaluationStatus", "EvaluationDecision",
    "EvidenceType", "EvidenceTrust", "FailureClass", "CorrectionStrategy",
    "ConsensusOutcome", "Criterion", "EvidenceRecord", "CheckResult",
    "EvalScores", "EvalDecision", "CorrectionBudget", "TRUST_RANK",
    "TERMINAL_STATES", "can_transition", "ALLOWED_TRANSITIONS",
    "register_evaluation_type", "is_known_evaluation_type",
    "Rubric", "RUBRIC_VERSION", "BUILTIN_RUBRICS", "parse_criteria",
    "parse_goal_block", "get_rubric", "list_rubrics", "weighted_score",
    "EvidenceCollector", "content_hash", "classify_trust",
    "verify_content_hash", "VERIFIERS", "run_check", "validate_json_schema",
    "verify_http", "verify_file_state", "verify_test_summary",
    "verify_workflow_nodes", "verify_browser_state", "verify_git_state",
    "verify_side_effect", "verify_secret_scan", "verify_output_contains",
    "run_llm_evaluation", "parse_evaluator_output", "build_evaluation_prompt",
    "frame_untrusted", "check_evaluator_separation",
    "normalize_score", "combine_consensus", "decide",
    "EvaluatorEngine", "EvaluatorError", "CreateEvaluation",
    "EVALUATOR_VERSION", "VERIFICATION_VERSION",
    "SelfCorrectionEngine", "CorrectionError", "failure_signature",
    "classify_exception", "default_strategy_for", "check_budget",
    "APPROVAL_STRATEGIES", "BUILTIN_GATES", "get_builtin_gate",
    "list_builtin_gates", "evaluate_gate", "load_org_gates",
    "run_benchmark", "detect_regression", "BenchmarkError",
    "REGRESSION_FLOOR", "metrics_inc", "metrics_snapshot",
    "EvaluatorSettings",
]
