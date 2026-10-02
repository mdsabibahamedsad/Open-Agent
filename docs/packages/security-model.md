# Security Model

## Scanner

Every manifest, resource payload and skill instruction is scanned as
**untrusted data**. Detections include unrestricted shell/host-filesystem/
docker-socket access, privileged containers, unrestricted networks, internal
or metadata URLs, dangerous connector scopes, destructive tools, missing
approval declarations, unsafe browser/sandbox configuration, excessive
limits, prompt-injection and policy-override phrasing, credential
exfiltration patterns, cross-tenant references and embedded raw secrets.

Aggregate risk: `LOW / MEDIUM / HIGH / CRITICAL` (any `BLOCKER` → CRITICAL).
High-risk packages are flagged and require explicit review — never silently
approved. Scans persist in `package_security_scans` and render in the
package security report UI.

## Trust model

| Level | Install UX | Network | Sandbox | Low-risk auto-approval |
|---|---|---|---|---|
| CORE | silent | standard | standard | yes (+verified signature required) |
| VERIFIED | silent | standard | standard | yes (+verified signature required) |
| ORGANIZATION | silent | restricted | required | yes |
| COMMUNITY | warning | restricted | required | no |
| UNTRUSTED | warning | denied by default | required | no |

## Tenant isolation

All package/skill/preset/installation rows are tenant-scoped
(`organization_id`; `NULL` = global catalog). Cross-tenant reads return
404; cross-tenant credentials, memory, workflows, agents and connector
instances are impossible by construction (references resolve within the
installing org only).

## RBAC

`package:read/create/update/delete/execute/manage`,
`skill:read/create/update/delete`, `preset:read/create/update/delete`,
granted to system roles (owner/admin full, developer create+install,
operator/member install, viewer read). Global/official mutation additionally
requires platform ownership. Every mutating action writes an audit row
(secrets redacted) and an outbox event.

## Prompt-injection defense

Package text lives in `payload`/`instructions`/`description`; policy lives
in platform/org/tool/sandbox/approval layers. The former can never override
the latter: at install and at every execution, the most restrictive
applicable policy wins.
