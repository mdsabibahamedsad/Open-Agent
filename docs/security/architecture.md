# Security Architecture

Defense in depth across identity (8 categories, validated lifecycle),
authentication (password/SSO/MFA/WebAuthn/recovery, AAL step-up),
authorization (RBAC + ABAC, precedence, deny-by-default), zero-trust
(device/session/risk, workload leases, network policy, micro-
segmentation zones A–F), AI security (untrusted-content hooks,
delegation subsets, tool/MCP/memory gates), data protection
(classification incl. SECRET, DLP, redaction, retention), and
compliance (controls + evidence + drift, no certification claims).
Self-hosted works with local auth only; enterprise IdPs are modular.
