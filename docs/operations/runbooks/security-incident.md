# Runbook: security incident

1. Open incident (CRITICAL as warranted); restrict responders.
2. Contain via security-response API only: disable connector/MCP
   server/provider/class, drain region, revoke identity, block domain.
   No arbitrary commands, no shell via UI.
3. Preserve audit chain; verify integrity (`/master/control/audit`).
4. Rotate affected secrets (staged, no downtime); force logout orgs.
5. Postmortem ref required before CLOSED. Never claim certification
   impact beyond measured facts.
