# sandbox-code-tool

Sandbox-backed tool: code runs only inside the `CODE_DEFAULT` profile
(non-root, no network, argv-structured, audited). Never on the host.

```bash
openagent test
openagent validate && openagent package && openagent publish
```
