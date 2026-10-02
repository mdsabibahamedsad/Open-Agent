# Queues

Durable `QueueProvider` abstraction (Redis baseline, in-memory fake,
Postgres-capable; Kafka/RabbitMQ/NATS/SQS later without logic changes).
Logical queues route by policy (`route_queue`): workflow/agent
default vs priority, browser, code, sandbox, scheduled, webhook,
long-running, high-memory, high-cpu. Priority is entitlement-clamped so
no tenant starves others. Backpressure: full queues reject with
`QUEUE_FULL`/`429`; streams bound buffers with drop policies. Retries
use backoff and only for retryable errors; exhausted jobs land in the
DLQ with metadata + inspect/retry/cancel/delete ops.
