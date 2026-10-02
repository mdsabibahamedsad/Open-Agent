# Observability

One correlation context (`request_id`, `trace_id`, `span_id`,
`execution_id`, `task_id`, `organization_id`) flows API → workflow →
agent → tool → sandbox → worker → model provider, shared by logs,
metrics, traces, events, audit, alerts, and incidents. Chain view:
`trace_chain()`.
