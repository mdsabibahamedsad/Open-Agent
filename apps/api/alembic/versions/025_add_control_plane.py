"""Add MP26 control-plane tables (additive only, reversible).

Revision ID: 025_add_control_plane
Revises: 024_add_cloud_runtime
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '025_add_control_plane'
down_revision = '024_add_cloud_runtime'
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


def _org_fk_nullable():
    return sa.Column('organization_id', postgresql.UUID(as_uuid=True),
                     sa.ForeignKey('organizations.id', ondelete='CASCADE'),
                     nullable=True)


TABLES = (
    "platform_configs", "config_versions", "feature_flags",
    "alert_rules", "alerts", "incidents", "incident_timeline",
    "maintenance_windows", "deployments", "operation_locks",
    "service_slos", "platform_events", "ip_policies", "rotation_jobs",
    "private_enrollments", "backup_reports",
)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.create_table(
        "platform_configs", _uuid_pk(), *(_ts()),
        sa.Column('scope', sa.String(32), nullable=False),
        sa.Column('scope_id', sa.String(128), nullable=False, server_default=''),
        sa.Column('category', sa.String(64), nullable=False),
        sa.Column('key', sa.String(255), nullable=False),
        sa.Column('value', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_by', sa.String(255), nullable=False, server_default=''),
    )
    op.create_index("ix_platform_configs_scope", "platform_configs", ["scope"])
    op.create_index("ix_platform_configs_scope_key", "platform_configs",
                    ["scope", "scope_id", "category", "key"])

    op.create_table(
        "config_versions", _uuid_pk(), *(_ts()),
        sa.Column('scope', sa.String(32), nullable=False),
        sa.Column('scope_id', sa.String(128), nullable=False, server_default=''),
        sa.Column('category', sa.String(64), nullable=False),
        sa.Column('key', sa.String(255), nullable=False),
        sa.Column('before', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('after', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('created_by', sa.String(255), nullable=False, server_default=''),
        sa.Column('changes', sa.Text(), nullable=False, server_default=''),
        sa.Column('rollback_reference', sa.String(128), nullable=False, server_default=''),
    )
    op.create_index("ix_config_versions_key", "config_versions", ["key"])
    op.create_index("ix_config_versions_created", "config_versions", ["created_at"])

    op.create_table(
        "feature_flags", _uuid_pk(), *(_ts()),
        sa.Column('key', sa.String(255), nullable=False),
        sa.Column('scope', sa.String(32), nullable=False),
        sa.Column('scope_id', sa.String(128), nullable=False, server_default=''),
        sa.Column('strategy', sa.String(32), nullable=False, server_default='boolean'),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('percentage', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('allowlist', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('denylist', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('label', sa.String(255), nullable=False, server_default=''),
        sa.Column('updated_by', sa.String(255), nullable=False, server_default=''),
    )
    op.create_index("ix_feature_flags_key", "feature_flags", ["key"])
    op.create_index("ix_feature_flags_key_scope", "feature_flags",
                    ["key", "scope", "scope_id"])

    op.create_table(
        "alert_rules", _uuid_pk(), *(_ts()),
        _org_fk_nullable(),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('metric', sa.String(255), nullable=False),
        sa.Column('condition', sa.String(8), nullable=False, server_default='gt'),
        sa.Column('threshold', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('duration_seconds', sa.Integer(), nullable=False, server_default='300'),
        sa.Column('severity', sa.String(16), nullable=False, server_default='WARNING'),
        sa.Column('destinations', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_by', sa.String(255), nullable=False, server_default=''),
    )
    op.create_index("ix_alert_rules_metric", "alert_rules", ["metric"])
    op.create_index("ix_alert_rules_org", "alert_rules", ["organization_id"])

    op.create_table(
        "alerts", _uuid_pk(), *(_ts()),
        sa.Column('rule_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('alert_rules.id', ondelete='SET NULL'), nullable=True),
        _org_fk_nullable(),
        sa.Column('severity', sa.String(16), nullable=False),
        sa.Column('source', sa.String(255), nullable=False, server_default=''),
        sa.Column('condition', sa.String(64), nullable=False, server_default=''),
        sa.Column('threshold', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('observed', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('status', sa.String(16), nullable=False, server_default='FIRING'),
        sa.Column('dedup_key', sa.String(64), nullable=False, server_default=''),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('metadata', sa.JSON(), nullable=False, server_default='{}'),
    )
    op.create_index("ix_alerts_status", "alerts", ["status"])
    op.create_index("ix_alerts_severity", "alerts", ["severity"])
    op.create_index("ix_alerts_dedup", "alerts", ["dedup_key"])
    op.create_index("ix_alerts_org_status", "alerts", ["organization_id", "status"])
    op.create_index("ix_alerts_status_severity", "alerts", ["status", "severity"])

    op.create_table(
        "incidents", _uuid_pk(), *(_ts()),
        _org_fk_nullable(),
        sa.Column('title', sa.String(500), nullable=False),
        sa.Column('severity', sa.String(16), nullable=False),
        sa.Column('status', sa.String(16), nullable=False, server_default='DETECTED'),
        sa.Column('affected_services', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('affected_regions', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('responders', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('actions', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('resolution', sa.Text(), nullable=False, server_default=''),
        sa.Column('postmortem_ref', sa.String(255), nullable=False, server_default=''),
        sa.Column('created_by', sa.String(255), nullable=False, server_default=''),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_incidents_status", "incidents", ["status"])
    op.create_index("ix_incidents_org_status", "incidents", ["organization_id", "status"])

    op.create_table(
        "incident_timeline", _uuid_pk(), *(_ts()),
        sa.Column('incident_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('incidents.id', ondelete='CASCADE'), nullable=False),
        sa.Column('actor', sa.String(255), nullable=False, server_default=''),
        sa.Column('message', sa.Text(), nullable=False),
    )
    op.create_index("ix_incident_timeline_incident", "incident_timeline",
                    ["incident_id", "created_at"])

    op.create_table(
        "maintenance_windows", _uuid_pk(), *(_ts()),
        sa.Column('title', sa.String(500), nullable=False, server_default=''),
        sa.Column('starts_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('ends_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('affected', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('expected_behavior', sa.Text(), nullable=False, server_default=''),
        sa.Column('active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_by', sa.String(255), nullable=False, server_default=''),
    )
    op.create_index("ix_maintenance_active", "maintenance_windows", ["active"])
    op.create_index("ix_maintenance_starts", "maintenance_windows", ["starts_at"])

    op.create_table(
        "deployments", _uuid_pk(), *(_ts()),
        sa.Column('service', sa.String(64), nullable=False),
        sa.Column('version', sa.String(64), nullable=False),
        sa.Column('commit', sa.String(128), nullable=False, server_default=''),
        sa.Column('build', sa.String(128), nullable=False, server_default=''),
        sa.Column('environment', sa.String(32), nullable=False, server_default='production'),
        sa.Column('deployer', sa.String(255), nullable=False, server_default=''),
        sa.Column('status', sa.String(32), nullable=False, server_default='PENDING'),
        sa.Column('deployed_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_deployments_service", "deployments", ["service"])
    op.create_index("ix_deployments_service_env", "deployments", ["service", "environment"])
    op.create_index("ix_deployments_status", "deployments", ["status"])

    op.create_table(
        "operation_locks", _uuid_pk(), *(_ts()),
        sa.Column('resource', sa.String(255), nullable=False),
        sa.Column('owner', sa.String(255), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('resource', name='uq_operation_locks_resource'),
    )
    op.create_index("ix_operation_locks_expires", "operation_locks", ["expires_at"])

    op.create_table(
        "service_slos", _uuid_pk(), *(_ts()),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=False, server_default=''),
        sa.Column('unit', sa.String(16), nullable=False, server_default='ratio'),
        sa.Column('target', sa.Float(), nullable=False, server_default='0.99'),
        sa.Column('window', sa.String(16), nullable=False, server_default='30d'),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default='true'),
        sa.UniqueConstraint('name', name='uq_service_slos_name'),
    )

    op.create_table(
        "platform_events", _uuid_pk(), *(_ts()),
        sa.Column('event_type', sa.String(128), nullable=False),
        sa.Column('source', sa.String(255), nullable=False),
        sa.Column('actor', sa.String(255), nullable=False, server_default=''),
        sa.Column('scope', sa.String(128), nullable=False, server_default='platform'),
        sa.Column('payload', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('request_id', sa.String(64), nullable=False, server_default=''),
    )
    op.create_index("ix_platform_events_type", "platform_events", ["event_type"])
    op.create_index("ix_platform_events_type_created", "platform_events",
                    ["event_type", "created_at"])
    op.create_index("ix_platform_events_request", "platform_events", ["request_id"])

    op.create_table(
        "ip_policies", _uuid_pk(), *(_ts()),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('allowlist', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('denylist', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('updated_by', sa.String(255), nullable=False, server_default=''),
    )
    op.create_index("ix_ip_policies_org", "ip_policies", ["organization_id"])

    op.create_table(
        "rotation_jobs", _uuid_pk(), *(_ts()),
        sa.Column('kind', sa.String(64), nullable=False),
        sa.Column('ref', sa.String(255), nullable=False),
        sa.Column('stage', sa.String(32), nullable=False, server_default='created'),
        sa.Column('error', sa.Text(), nullable=False, server_default=''),
        sa.Column('created_by', sa.String(255), nullable=False, server_default=''),
        sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_rotation_jobs_stage", "rotation_jobs", ["stage"])
    op.create_index("ix_rotation_jobs_ref", "rotation_jobs", ["ref"])

    op.create_table(
        "private_enrollments", _uuid_pk(), *(_ts()),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('token_hash', sa.String(128), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('worker_id', sa.String(128), nullable=False, server_default=''),
        sa.UniqueConstraint('token_hash', name='uq_private_enrollments_token'),
    )
    op.create_index("ix_private_enrollments_org", "private_enrollments",
                    ["organization_id"])

    op.create_table(
        "backup_reports", _uuid_pk(), *(_ts()),
        sa.Column('kind', sa.String(64), nullable=False),
        sa.Column('status', sa.String(32), nullable=False),
        sa.Column('detail', sa.Text(), nullable=False, server_default=''),
        sa.Column('measured_rpo_seconds', sa.Float(), nullable=True),
        sa.Column('measured_rto_seconds', sa.Float(), nullable=True),
        sa.Column('restore_tested_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('reported_by', sa.String(255), nullable=False, server_default=''),
    )
    op.create_index("ix_backup_reports_kind", "backup_reports", ["kind"])


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_table(table)
