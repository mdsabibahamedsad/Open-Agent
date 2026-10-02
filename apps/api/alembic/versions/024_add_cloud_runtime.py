"""Add MP25 cloud runtime tables (control plane + execution plane state).

Revision ID: 024_add_cloud_runtime
Revises: 023_add_commerce
Create Date: 2026-10-01 00:00:00.000000

Additive only: new tables. Reuses workflow_executions, execution_events,
commerce usage/entitlement tables, and core scheduled_jobs. Reversible.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '024_add_cloud_runtime'
down_revision = '023_add_commerce'
branch_labels = None
depends_on = None


def _uuid_pk():
    return sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                     server_default=sa.text('gen_random_uuid()'))


def _ts():
    return (sa.Column('created_at', sa.DateTime(timezone=True),
                      server_default=sa.func.now(), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True),
                      server_default=sa.func.now(), nullable=False))


def _org_fk(nullable=False):
    return sa.Column('organization_id', postgresql.UUID(as_uuid=True),
                     sa.ForeignKey('organizations.id', ondelete='CASCADE'),
                     nullable=nullable)


def _meta(name='metadata'):
    return sa.Column(name, sa.JSON(), nullable=False, server_default='{}')


TABLES = (
    "cloud_regions", "worker_pools", "cloud_workers", "worker_heartbeats",
    "execution_leases", "execution_placements", "execution_attempts",
    "cloud_queues", "dead_letter_messages", "scheduler_leases",
    "schedule_dedup", "cloud_artifacts", "cloud_execution_events",
    "cloud_usage_events", "runtime_policies",
)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # -- cloud_regions -----------------------------------------------------
    op.create_table(
        "cloud_regions", _uuid_pk(), *(_ts()),
        sa.Column('slug', sa.String(100), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('status', sa.String(32), nullable=False, server_default='ACTIVE'),
        sa.Column('capabilities', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('residency_tags', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('cost_weight', sa.Float(), nullable=False, server_default='1.0'),
        sa.Column('max_workers', sa.Integer(), nullable=False, server_default='100'),
        sa.Column('is_private', sa.Boolean(), nullable=False, server_default='false'),
        _meta(),
        sa.UniqueConstraint('slug', name='uq_cloud_regions_slug'),
    )
    op.create_index("ix_cloud_regions_slug", "cloud_regions", ["slug"])
    op.create_index("ix_cloud_regions_status", "cloud_regions", ["status"])

    # -- worker_pools ------------------------------------------------------
    op.create_table(
        "worker_pools", _uuid_pk(), *(_ts()),
        sa.Column('slug', sa.String(100), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('region_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('cloud_regions.id', ondelete='SET NULL'), nullable=True),
        sa.Column('capabilities', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('min_workers', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('max_workers', sa.Integer(), nullable=False, server_default='20'),
        sa.Column('labels', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.UniqueConstraint('slug', name='uq_worker_pools_slug'),
    )
    op.create_index("ix_worker_pools_slug", "worker_pools", ["slug"])

    # -- cloud_workers -----------------------------------------------------
    op.create_table(
        "cloud_workers", _uuid_pk(), *(_ts()),
        sa.Column('worker_id', sa.String(128), nullable=False),
        sa.Column('service_identity', sa.String(255), nullable=False),
        sa.Column('region_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('cloud_regions.id', ondelete='SET NULL'), nullable=True),
        sa.Column('region_slug', sa.String(100), nullable=False, server_default='local-1'),
        sa.Column('pool_slug', sa.String(100), nullable=False, server_default='default'),
        sa.Column('capabilities', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('labels', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('state', sa.String(32), nullable=False, server_default='REGISTERING'),
        sa.Column('version', sa.String(50), nullable=False, server_default='0.1.0'),
        sa.Column('max_concurrency', sa.Integer(), nullable=False, server_default='4'),
        sa.Column('active_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('cpu_millicores_total', sa.Integer(), nullable=False, server_default='2000'),
        sa.Column('memory_mb_total', sa.Integer(), nullable=False, server_default='4096'),
        sa.Column('supports_gpu', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('tenant_restriction', sa.String(255), nullable=False, server_default=''),
        sa.Column('last_heartbeat_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('drained_at', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('worker_id', name='uq_cloud_workers_worker_id'),
    )
    op.create_index("ix_cloud_workers_worker_id", "cloud_workers", ["worker_id"])
    op.create_index("ix_cloud_workers_state", "cloud_workers", ["state"])
    op.create_index("ix_cloud_workers_region_state", "cloud_workers", ["region_slug", "state"])
    op.create_index("ix_cloud_workers_pool_state", "cloud_workers", ["pool_slug", "state"])
    op.create_index("ix_cloud_workers_heartbeat", "cloud_workers", ["last_heartbeat_at"])

    # -- worker_heartbeats (append-only, retention-cleaned) -----------------
    op.create_table(
        "worker_heartbeats", _uuid_pk(), *(_ts()),
        sa.Column('worker_id', sa.String(128), nullable=False),
        sa.Column('state', sa.String(32), nullable=False),
        sa.Column('active_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('cpu_millicores_used', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('memory_mb_used', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('detail', postgresql.JSONB(), nullable=False, server_default='{}'),
    )
    op.create_index("ix_worker_heartbeats_worker", "worker_heartbeats", ["worker_id"])
    op.create_index("ix_worker_heartbeats_created", "worker_heartbeats", ["created_at"])

    # -- execution_leases ---------------------------------------------------
    op.create_table(
        "execution_leases", _uuid_pk(), *(_ts()),
        sa.Column('execution_id', sa.String(64), nullable=False),
        _org_fk(),
        sa.Column('lease_id', sa.String(64), nullable=False),
        sa.Column('owner_id', sa.String(128), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('renewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('released_at', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('lease_id', name='uq_execution_leases_lease_id'),
    )
    op.create_index("ix_execution_leases_exec", "execution_leases", ["execution_id"])
    op.create_index("ix_execution_leases_owner", "execution_leases", ["owner_id"])
    op.create_index("ix_execution_leases_expires", "execution_leases", ["expires_at"])
    op.create_index("ix_execution_leases_exec_owner", "execution_leases",
                    ["execution_id", "owner_id"])

    # -- execution_placements -----------------------------------------------
    op.create_table(
        "execution_placements", _uuid_pk(), *(_ts()),
        sa.Column('execution_id', sa.String(64), nullable=False),
        _org_fk(),
        sa.Column('region_slug', sa.String(100), nullable=False),
        sa.Column('pool_slug', sa.String(100), nullable=False),
        sa.Column('queue', sa.String(100), nullable=False),
        sa.Column('priority', sa.String(16), nullable=False, server_default='NORMAL'),
        sa.Column('failover_from', sa.String(100), nullable=False, server_default=''),
        sa.Column('residency', sa.String(32), nullable=False, server_default='ANY_REGION'),
        sa.UniqueConstraint('execution_id', name='uq_execution_placements_exec'),
    )
    op.create_index("ix_execution_placements_region", "execution_placements", ["region_slug"])
    op.create_index("ix_execution_placements_queue", "execution_placements", ["queue"])

    # -- execution_attempts --------------------------------------------------
    op.create_table(
        "execution_attempts", _uuid_pk(), *(_ts()),
        sa.Column('execution_id', sa.String(64), nullable=False),
        _org_fk(),
        sa.Column('attempt', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('worker_id', sa.String(128), nullable=False, server_default=''),
        sa.Column('status', sa.String(32), nullable=False),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_execution_attempts_exec", "execution_attempts", ["execution_id"])
    op.create_index("ix_execution_attempts_exec_attempt", "execution_attempts",
                    ["execution_id", "attempt"])

    # -- cloud_queues (cached stats) -----------------------------------------
    op.create_table(
        "cloud_queues", _uuid_pk(), *(_ts()),
        sa.Column('queue', sa.String(100), nullable=False),
        sa.Column('depth', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('oldest_age_seconds', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('processing', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('dead_letter_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('paused', sa.Boolean(), nullable=False, server_default='false'),
        sa.UniqueConstraint('queue', name='uq_cloud_queues_queue'),
    )

    # -- dead_letter_messages --------------------------------------------------
    op.create_table(
        "dead_letter_messages", _uuid_pk(), *(_ts()),
        sa.Column('message_id', sa.String(64), nullable=False),
        sa.Column('queue', sa.String(100), nullable=False),
        sa.Column('execution_id', sa.String(64), nullable=False),
        _org_fk(),
        sa.Column('reason', sa.Text(), nullable=False, server_default=''),
        sa.Column('payload', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('status', sa.String(32), nullable=False, server_default='PENDING'),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('message_id', name='uq_dlq_message_id'),
    )
    op.create_index("ix_dlq_queue", "dead_letter_messages", ["queue"])
    op.create_index("ix_dlq_exec", "dead_letter_messages", ["execution_id"])
    op.create_index("ix_dlq_status", "dead_letter_messages", ["status"])

    # -- scheduler_leases ------------------------------------------------------
    op.create_table(
        "scheduler_leases", _uuid_pk(), *(_ts()),
        sa.Column('resource', sa.String(128), nullable=False),
        sa.Column('owner_id', sa.String(128), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('resource', name='uq_scheduler_leases_resource'),
    )

    # -- schedule_dedup ----------------------------------------------------------
    op.create_table(
        "schedule_dedup", _uuid_pk(), *(_ts()),
        sa.Column('schedule_id', sa.String(64), nullable=False),
        sa.Column('execution_key', sa.String(64), nullable=False),
        sa.Column('execution_id', sa.String(64), nullable=False),
        sa.Column('scheduled_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('execution_key', name='uq_schedule_dedup_key'),
    )
    op.create_index("ix_schedule_dedup_schedule", "schedule_dedup", ["schedule_id"])

    # -- cloud_artifacts -----------------------------------------------------------
    op.create_table(
        "cloud_artifacts", _uuid_pk(), *(_ts()),
        sa.Column('artifact_id', sa.String(64), nullable=False),
        _org_fk(),
        sa.Column('execution_id', sa.String(64), nullable=False),
        sa.Column('task_id', sa.String(64), nullable=False, server_default=''),
        sa.Column('workspace_id', sa.String(64), nullable=False, server_default=''),
        sa.Column('name', sa.String(500), nullable=False),
        sa.Column('mime_type', sa.String(255), nullable=False,
                  server_default='application/octet-stream'),
        sa.Column('size', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('storage_key', sa.Text(), nullable=False),
        sa.Column('checksum', sa.String(128), nullable=False, server_default=''),
        sa.Column('category', sa.String(64), nullable=False,
                  server_default='execution-artifacts'),
        sa.Column('state', sa.String(32), nullable=False, server_default='ACTIVE'),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('download_count', sa.Integer(), nullable=False, server_default='0'),
        _meta(),
        sa.UniqueConstraint('artifact_id', name='uq_cloud_artifacts_artifact_id'),
    )
    op.create_index("ix_cloud_artifacts_artifact", "cloud_artifacts", ["artifact_id"])
    op.create_index("ix_cloud_artifacts_org", "cloud_artifacts", ["organization_id"])
    op.create_index("ix_cloud_artifacts_org_state", "cloud_artifacts",
                    ["organization_id", "state"])
    op.create_index("ix_cloud_artifacts_exec", "cloud_artifacts", ["execution_id"])
    op.create_index("ix_cloud_artifacts_expires", "cloud_artifacts", ["expires_at"])

    # -- cloud_execution_events -------------------------------------------------------
    op.create_table(
        "cloud_execution_events", _uuid_pk(), *(_ts()),
        sa.Column('execution_id', sa.String(64), nullable=False),
        _org_fk(),
        sa.Column('sequence', sa.Integer(), nullable=False),
        sa.Column('type', sa.String(64), nullable=False),
        sa.Column('payload', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.UniqueConstraint('execution_id', 'sequence',
                            name='uq_cloud_execution_events_exec_seq'),
    )
    op.create_index("ix_cloud_execution_events_exec", "cloud_execution_events",
                    ["execution_id"])
    op.create_index("ix_cloud_execution_events_org", "cloud_execution_events",
                    ["organization_id"])
    op.create_index("ix_cloud_execution_events_type", "cloud_execution_events", ["type"])

    # -- cloud_usage_events (staged for commerce aggregation) ---------------------------
    op.create_table(
        "cloud_usage_events", _uuid_pk(), *(_ts()),
        _org_fk(),
        sa.Column('execution_id', sa.String(64), nullable=False),
        sa.Column('meter', sa.String(100), nullable=False),
        sa.Column('quantity', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('dedup_key', sa.String(255), nullable=False),
        sa.Column('exported', sa.Boolean(), nullable=False, server_default='false'),
        sa.UniqueConstraint('dedup_key', name='uq_cloud_usage_dedup'),
    )
    op.create_index("ix_cloud_usage_exec", "cloud_usage_events", ["execution_id"])
    op.create_index("ix_cloud_usage_org_meter", "cloud_usage_events",
                    ["organization_id", "meter"])
    op.create_index("ix_cloud_usage_exported", "cloud_usage_events", ["exported"])

    # -- runtime_policies ---------------------------------------------------------------
    op.create_table(
        "runtime_policies", _uuid_pk(), *(_ts()),
        sa.Column('scope', sa.String(32), nullable=False),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=True),
        sa.Column('residency', sa.String(32), nullable=False, server_default='ANY_REGION'),
        sa.Column('allowed_regions', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('pool_preference', sa.String(100), nullable=False, server_default='default'),
        sa.Column('max_concurrent_executions', sa.Integer(), nullable=False, server_default='10'),
        sa.Column('artifact_retention_seconds', sa.Integer(), nullable=False,
                  server_default='2592000'),
        sa.Column('webhook_limit_per_minute', sa.Integer(), nullable=False,
                  server_default='120'),
        sa.Column('policy', postgresql.JSONB(), nullable=False, server_default='{}'),
    )
    op.create_index("ix_runtime_policies_scope", "runtime_policies", ["scope"])
    op.create_index("ix_runtime_policies_org", "runtime_policies", ["organization_id"])

    # Seed the default local region + default pool (idempotent).
    op.execute(sa.text(
        "INSERT INTO cloud_regions (id, slug, name, status, capabilities, "
        "residency_tags, cost_weight, max_workers, is_private, metadata, "
        "created_at, updated_at) "
        "SELECT gen_random_uuid(), 'local-1', 'Local Region', 'ACTIVE', "
        "'[\"exec\", \"code\"]', '[]', 1.0, 100, false, '{}', now(), now() "
        "WHERE NOT EXISTS (SELECT 1 FROM cloud_regions WHERE slug = 'local-1')"))
    op.execute(sa.text(
        "INSERT INTO worker_pools (id, slug, name, capabilities, min_workers, "
        "max_workers, labels, created_at, updated_at) "
        "SELECT gen_random_uuid(), 'default', 'Default Pool', '[\"exec\"]', "
        "1, 20, '{}', now(), now() "
        "WHERE NOT EXISTS (SELECT 1 FROM worker_pools WHERE slug = 'default')"))


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_table(table)
