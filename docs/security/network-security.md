# Network Security

Workload → policy → destination → allow/deny: domain allowlists, CIDR
rules on resolved IPs, ports, protocols, environment, workload type;
denies win; cross-zone flows default-deny outside the listed
east-west set. SSRF floor (loopback/private/metadata) always applies;
full connector netsec engine (DNS rebinding, redirects) enforced on
HTTP paths. Private networking (endpoints/VPN/proxy, outbound-only
workers) is configuration, not a fork. Headers: CSP/HSTS/nosniff/
frame-DENY/Referrer-Policy/COOP-CORP via middleware; CORS uses
explicit per-environment origins with credentials (no wildcards);
browser state changes reuse the CSRF architecture.
