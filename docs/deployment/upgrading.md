# Upgrading OpenAgent

Standard upgrade flow. Never assume a release is backward-compatible —
always read `CHANGELOG.md` and `docs/release/release-notes.md` first.

```text
backup → pull release → inspect changelog → update env →
migrate database → restart services → health check → verify workflows
```

## Procedure

1. **Back up.** `pg_dump` the production database and snapshot artifact
   storage. OpenAgent never backs these up automatically.
2. **Pull the release.**
   `git fetch origin && git checkout <tag-or-sha>` (detached, deliberate).
3. **Inspect.** Read the `CHANGELOG.md` entry: new required env vars?
   breaking API/SDK changes? migration notes?
4. **Update environment.** Diff your `.env` against the release's
   `.env.production.example`; add new required variables before starting.
5. **Migrate.**
   ```bash
   docker compose -f docker-compose.production.yml up -d postgres redis
   docker compose -f docker-compose.production.yml run --rm api \
     python -m alembic upgrade head
   ```
6. **Restart.** `docker compose -f docker-compose.production.yml up -d --build`
7. **Health-check.** `/api/v1/health` (alive) then `/api/v1/health/ready`
   (200 = DB + Redis OK). Exercise one agent run and one workflow execution.
8. **Watch.** Monitor worker heartbeats and error rates for at least one
   scheduler poll interval ×3.

## Rollback

- **Application/config/containers:** safe — re-deploy the previous
  image/tag and previous `.env` (keep the old `.env` copy until the new
  release is verified).
- **Database:** Alembic `downgrade` is supported only for migrations marked
  reversible, and downgrades can destroy data the new version created.
  **Default to backup restore or forward-fix;** run `alembic downgrade`
  only when the migration's downgrade path was reviewed for that release
  and you have a tested backup taken in step 1.
- **Rule:** if a migration is irreversible, recovery = restore backup or
  roll forward. Never improvise SQL against production.
