# Verification (MP20)

Verification (observable condition true?) is separate from evaluation
(quality/correctness judgment). Prefer deterministic verification whenever
evidence exists; use LLM judges only for what cannot be checked.

## Deterministic check kinds

| Kind | Verifies |
|---|---|
| `http_response` | status, required fields, latency, body schema |
| `json_schema` | types, required, enum, ranges, lengths (built-in subset validator) |
| `file_state` | existence, hash, size, markers, JSON content |
| `test_summary` | passed/failed counts |
| `workflow_nodes` | required nodes succeeded, no failures |
| `browser_state` | URL, selector, success text, no unresolved challenge |
| `git_state` | commit exists, branch, files in diff |
| `side_effect` | provider success **plus** independent verification |
| `secret_scan` | no secret-like findings (safety-critical) |
| `output_contains` | required markers present, forbidden absent |

Unknown kinds fail closed. Crashing checks fail closed.

## Evidence trust

`SYSTEM_VERIFIED > TOOL_VERIFIED ≈ EXTERNAL_VERIFIED > USER_CONFIRMED >
MODEL_GENERATED > UNVERIFIED`. Agent output is always `MODEL_GENERATED`,
even if the agent claims otherwise. Conflicts resolve toward higher trust;
ties resolve conservatively.

## Immutability

Evidence rows carry `content_hash` captured at write time and are
re-verified on read. Tampering raises `EVIDENCE_TAMPERED` (fails safely)
and emits a security event. Post-terminal evaluations reject new evidence.

## Workflow nodes

`verify` (checks), `evaluate` (score+threshold), `assert` (hard condition),
`quality_gate` (built-in or literal gate), `retry` (bounded counter),
`correct` (plan descriptor). Human review reuses the `approval` node.
See `docs/ai/self-correction.md` for the retry/correct loop.
