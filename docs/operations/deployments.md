# Deployments

Deployments record service/version/commit/build/environment/deployer/
status (`PENDING → DEPLOYING → ACTIVE|FAILED`, `ROLLED_BACK`).
Releases track environments (development/staging/production) and state
(`CREATED → DEPLOYING → ACTIVE|FAILED → ROLLED_BACK`). Rollback is
**requested, never automatic**: `rollback_plan` blocks on destructive
migrations, requires HIGH_RISK step-up, confirmation, audit, and health
verification steps.
