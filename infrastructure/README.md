# Infrastructure

This directory contains infrastructure-as-code and deployment configurations for OpenAgent.

## Structure

```
infrastructure/
├── docker/           # Docker configurations
│   ├── docker-compose.yml
│   ├── docker-compose.prod.yml
│   └── Dockerfile.*
├── kubernetes/       # Kubernetes manifests (future)
├── terraform/        # Terraform modules (future)
├── scripts/          # Deployment and utility scripts
└── ansible/          # Ansible playbooks (future)
```

## Docker

### Development

```bash
# Start all services
docker compose up -d

# View logs
docker compose logs -f

# Stop services
docker compose down

# Rebuild and restart
docker compose up -d --build
```

### Production

```bash
# Build production images
docker compose -f docker-compose.yml -f docker-compose.prod.yml build

# Deploy
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

## Scripts

### `scripts/deploy.sh`

Deploys OpenAgent to a target environment.

```bash
./scripts/deploy.sh --environment production --version v0.1.0
```

### `scripts/backup.sh`

Backups PostgreSQL database.

```bash
./scripts/backup.sh --output ./backups
```

### `scripts/restore.sh`

Restores PostgreSQL database from backup.

```bash
./scripts/restore.sh --input ./backups/backup_20240101.sql.gz
```

## Environment-Specific Configs

- `docker-compose.yml` - Base configuration
- `docker-compose.dev.yml` - Development overrides
- `docker-compose.prod.yml` - Production overrides
- `docker-compose.test.yml` - CI/test overrides

## Secrets Management

- Development: `.env` file (gitignored)
- CI/CD: GitHub Actions secrets
- Production: External secret manager (HashiCorp Vault, AWS Secrets Manager, etc.)

## Monitoring

- Prometheus metrics endpoint: `/metrics`
- Health checks: `/health`, `/health/ready`
- Logging: Structured JSON logs to stdout
- Tracing: OpenTelemetry (future)

## Scaling

### Horizontal Scaling

- API: Multiple replicas behind load balancer
- Worker: Multiple workers consuming from Redis queue
- Web: Static files served by CDN, SSR on multiple instances

### Database

- Read replicas for read-heavy workloads
- Connection pooling (PgBouncer)
- Partitioning for large tables (future)

### Cache

- Redis Cluster for high availability
- Separate databases for different cache types

## Backup Strategy

- Daily automated PostgreSQL backups
- Point-in-time recovery (WAL archiving)
- Cross-region replication for disaster recovery
- Regular restore testing

## Security

- Network policies restricting inter-service communication
- TLS termination at load balancer
- Regular security scanning of container images
- Automated dependency updates (Dependabot)

## Future: Kubernetes

```yaml
# Planned structure
kubernetes/
├── base/
│   ├── namespace.yaml
│   ├── configmap.yaml
│   └── secrets.yaml
├── overlays/
│   ├── development/
│   ├── staging/
│   └── production/
└── charts/
    ├── openagent-api/
    ├── openagent-web/
    ├── openagent-worker/
    └── postgresql/
```