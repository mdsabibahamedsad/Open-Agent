# AI Security

External content (pages, docs, mail, MCP, connectors, memory, tool
output, browser) is tagged untrusted data: high-confidence override
markers escalate to human approval, never silent action, and can never
override system policy, authorization, approvals, or limits. Agents
carry explicit identity and delegate permission subsets only. Tool
calls require full caller/agent/org/resource/action/risk/environment
context through the Tool Runtime; MCP servers need verified trust +
granted scopes; browser sessions use workload identity with secret
hygiene; code runs only via Tool Runtime → Sandbox; memory writes are
policy-gated.
