# Tracing

`Tracer` builds OTel-compatible spans (trace/span/parent ids,
service, operation, duration, redacted attributes) across API, control
plane, dispatcher, queue, worker, execution, agent, tool, MCP, browser,
code agent, sandbox, connector, model provider, storage. Export is a
dict pipeline today; point it at a real OTel exporter without changing
call sites. Secrets never enter spans (attributes are redacted).
