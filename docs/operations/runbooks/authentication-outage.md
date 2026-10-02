# Runbook: authentication outage

1. Check auth error spike alerts + security events (attack vs outage).
2. Session policy: shorten lifetimes temporarily if tokens leak;
   forced logout is available per org.
3. Master Account: step-up still required for critical ops — do not
   bypass under pressure.
4. Rotate compromised credentials via staged rotation (no downtime).
