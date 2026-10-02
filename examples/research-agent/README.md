# research-agent

TypeScript agent wired to a `web.search` tool with scoped memory.
Permissions used: `tool:execute`, `model:invoke`, `memory:read`, `memory:write`.

```bash
openagent dev --mock
openagent test
openagent validate && openagent package && openagent publish
```
