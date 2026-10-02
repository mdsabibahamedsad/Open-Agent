# Enterprise

Org controls: IP allow/deny (CIDR, trusted-proxy only), session policy
(lifetime/idle/concurrent/forced logout reusing existing sessions),
API-key governance (scopes/expiry/rotation/last-used, raw shown once),
service accounts (minimum privilege + environment binding), staged
secret rotation (create → propagate → verify → retire; failures keep
the old secret live), data classification, retention with unbypassable
platform minimums, presets (Standard/Strict/High Security/Custom).
Private runtime: one-time enrollment tokens (hash stored, single use,
expiring) → short-lived worker identity; outbound-only connectivity,
VPN/proxy-ready, no vendor hard-coding. Compliance: SOC2/ISO27001/GDPR
technical hooks only — **no certification claimed**.
