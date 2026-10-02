# Incident Response

Security events flow event → audit → alerting → incident → analytics
on existing infrastructure. Kinds: auth spikes, MFA disablement, SSO/
SCIM changes, escalation attempts, suspicious API use, secret
exposure, bypass attempts, worker anomalies. Response uses scoped
containment APIs (disable/drain/revoke/block) with step-up + audit;
runbook at `docs/operations/runbooks/security-incident.md`. Account
takeover defenses: rate limits, stuffing protection, MFA, session
risk, prompt revocation, protected reset/verify/invite flows (signed,
expiring, single-use, org-bound).
