# Production Deployment Checklist

Complete every item before serving real traffic. Items marked (verify) have
a command to prove them.

- [ ] Domain configured (DNS resolves to proxy/host)
- [ ] HTTPS configured (valid certificate, HTTP→HTTPS redirect)
- [ ] Secrets configured (fresh `openssl rand -hex 32` values; no dev secrets)
- [ ] `.env` (or secret store) is NOT committed, NOT world-readable
- [ ] Database backed up (and a restore was actually tested once)
- [ ] Migrations validated: `alembic heads` shows exactly one head (verify)
- [ ] Migration applied against a copy first where the release changes schema
- [ ] Redis AUTH enabled; Redis not reachable from the internet (verify: only `internal` network in production compose)
- [ ] PostgreSQL not reachable from the internet (verify: no published DB ports in production compose)
- [ ] Object storage configured (`s3`/`r2`/MinIO — not `filesystem`)
- [ ] CORS set to exact production origins (verify: no `localhost`, no `*`)
- [ ] `OPENAGENT_ENV=production` (verify: `/docs` returns 404)
- [ ] Rate limits sane for auth endpoints
- [ ] Readiness probe on `/api/v1/health/ready`, liveness on `/api/v1/health`
- [ ] Monitoring + log aggregation configured; alert webhooks set
- [ ] Sandbox image digest pinned (`SANDBOX_IMAGE_DIGEST`), provider `docker`
- [ ] Default credentials absent (DB, Redis, MinIO, admin accounts all rotated)
- [ ] Debug disabled (`LOG_LEVEL=info` or `warning`, no `--reload` in runtime)
- [ ] Firewall configured (only 80/443 inbound; 8000/3000 on loopback only)
- [ ] Billing mode intentional (`disabled` unless paid flows are live with webhook secret)
- [ ] Deployment smoke-tested end-to-end (login → agent run → artifact)
