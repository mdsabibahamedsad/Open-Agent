# Model Evaluation Notes (MP20)

LLM judges run through the existing Model Router (`model_provider_registry`
resolution server-side). Rules:

- Generator ≠ evaluator for high-stakes work unless `ALLOW_SELF_EVALUATION`
  is explicitly enabled (production startup refuses silent enable).
- Self-evaluation attempts are rejected AND logged as security events.
- Budgets (`MAX_EVALUATION_TOKENS`, `MAX_EVALUATION_COST`) bound judge calls;
  deterministic checks run first so LLM evaluation is the exception.
- Unavailable providers → 501; evaluations finalize UNCERTAIN, never PASS.
- Judge crashes → bounded retries → UNCERTAIN. Never silent PASS.
- Deterministic evaluations are cacheable by
  (input hash, output hash, criteria version, evaluator version); LLM
  judgments are not cached as truth (contextual only).
- Async evaluation: create (PENDING) → verify/vote → finalize, without
  blocking the requesting flow.
