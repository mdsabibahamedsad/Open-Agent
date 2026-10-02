# Runbook: connector outage

1. Check connector health/usage/error-rate + webhook health.
2. Disable the connector (scoped kill switch) for security or outage;
   queued webhook events stay staged for replay.
3. Verify no duplicated connector auth was created during recovery.
4. Re-enable, verify webhook verification passes, resolve incident.
