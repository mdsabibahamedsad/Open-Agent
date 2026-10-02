# Scheduler

Distributed scheduler: replicas compete for the `cloud-scheduler-tick`
lease; only the holder enqueues due jobs. Dedup keys
`(schedule_id, scheduled_at, execution_key)` prevent duplicate fires
across replicas, restarts, clock drift and retries. Supports cron,
one-time, delayed (`run_at`), recurring and timezone-aware schedules
with misfire grace handling. Delayed jobs persist in Postgres (never
in-memory timers alone). Scheduler never executes workflows in the API
process — it enqueues to the execution queue.
