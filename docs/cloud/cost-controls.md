# Cost controls

Infrastructure cost hooks track worker/cpu/memory/sandbox/browser time,
storage bytes and `storage_gb_hours`, network bytes, executions, agent
steps, model tokens, tool calls — staged as `cloud_usage_events` and
exported into the existing commerce usage pipeline (no second billing
system, no fake provider pricing; provider pricing is configurable).
Budgets (`max seconds/CPU/memory/storage/sessions`) reject oversized
requests at dispatch; live usage can terminate over-limit executions.
Global safety limits (`GLOBAL_MAX_*`) are Master-Account configurable.
