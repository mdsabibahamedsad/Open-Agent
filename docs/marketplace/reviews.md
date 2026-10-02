# Reviews

Reviews always pin the exact version installed/used (`version_id` NOT
NULL). Verified-use reviews link an installation record in the reviewer's
org; unverified reviews require documented usage context and start in
PENDING.

## Anti-abuse

- One review per user per listing version (unique constraint; duplicates
  get `DUPLICATE_REVIEW`, never silent overwrites).
- Publisher self-review detection via publisher membership -> FLAGGED.
- Velocity cap (5 reviews / 24h default) -> flagged for moderation.
- Spam heuristics -> PENDING with signals recorded.
- Report threshold: 3 open reports auto-flag a published review.
- Review writes are rate-limited (10/hour).
- No invasive profiling: signals are account-local counts and content
  patterns only.

## States and moderation

`PUBLISHED / PENDING / FLAGGED / HIDDEN / REMOVED`. Authors can edit while
PUBLISHED/PENDING. HIDE/REMOVE/RESTORE require `review:manage` or platform
ownership **with a recorded reason**; removals write `moderation_actions`
rows — nothing is silently deleted.

## Aggregates

`rating_average`, `rating_count`, `rating_distribution`,
`verified_review_count` recompute from PUBLISHED reviews only, in writers
— publishers have no write path to aggregates.

## Responses and reports

One authenticated publisher response per review (rate-limited, audited,
author notified). Reports accept SPAM/ABUSE/HARASSMENT/FRAUD/IRRELEVANT/
SENSITIVE_INFORMATION/MANIPULATION reasons into a triage queue
(OPEN/INVESTIGATING/ACTION_REQUIRED/RESOLVED/DISMISSED).
