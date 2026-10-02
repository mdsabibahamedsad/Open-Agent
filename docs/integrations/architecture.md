# Integration Architecture (MP21)

OpenAgent connects to the external digital world through one Universal
Integration Layer — never through ad-hoc per-service code.

```text
                 OpenAgent Core
                      │
              ┌───────┴────────┐
              │ Integration API │
              └───────┬────────┘
                      │
              Connector Registry
                      │
        ┌─────────────┼─────────────┐
        │             │             │
      OAuth       API/HTTP       Database
        │             │             │
        └─────────────┼─────────────┘
                      │
              Capability Registry
                      │
              Tool / Trigger Layer
                      │
               Policy / RBAC
                      │
                Risk / Approval
                      │
                 Tool Runtime
                      │
          ┌───────────┼───────────┐
          ↓           ↓           ↓
       Execute      Verify      Audit
          │           │
          └──────┬────┘
                 ↓
             Evaluator
```

## Layer responsibilities

| Layer | Owns | Never owns |
|---|---|---|
| Connector definition | manifest, versions, capabilities | secrets, credentials |
| Auth framework | OAuth flows, encrypted storage, masking | raw secret exposure |
| Provider stack | SSRF gate, retries, pooling, errors | business logic |
| Engine | tenancy, policy, approval, audit | provider protocols |
| Providers | protocol details, normalization | HTTP/security primitives |
| Tool Runtime | discovery, agent execution | connector policy |
| Evaluator | post-mutation verification | authorization |

Every privileged action flows: connector → tool runtime → policy → risk →
approval → execution → verification → audit. No exceptions, no shortcuts.
