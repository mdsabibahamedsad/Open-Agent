# Capacity planning

Report current/reserved/used capacity, headroom, and forecast **inputs**
from real utilization (CPU, memory, queue, worker, storage). No
unsupported demand predictions. Reconciliation controllers
(`WorkerPoolController` pattern via `Controller`) converge desired vs
observed state idempotently; operation locks prevent conflicting admin
actions (e.g. double region drain).
