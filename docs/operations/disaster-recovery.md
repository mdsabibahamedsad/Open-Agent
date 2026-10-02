# Disaster recovery

`backup_reports` track database/object/config backups with status,
**measured** RPO/RTO (only displayed when measured — never claimed),
and restore-test timestamps. DR dashboard shows backup health, region
health, replication, last restore test. Restore testing runs
backup → isolated restore → integrity + app verification → report,
never against production. Runbooks in `docs/operations/runbooks/`.
