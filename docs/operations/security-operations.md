# Security operations

Privileged actions classify NORMAL/SENSITIVE/HIGH_RISK/CRITICAL with
step-up (recent-auth windows, re-auth, MFA, confirmation phrase for
CRITICAL). Containment actions (disable connector/provider/class, drain
region, revoke identity, block domain) run through controlled backend
APIs — never arbitrary commands — and are audited with actor/action/
resource/before/after/IP/request_id/reason/result (never secrets).
Platform audit is a tamper-evident hash chain. Abuse detection emits
risk scores from correlated signals only (no single-signal accusations).
Security events stay separate from ordinary audit.
