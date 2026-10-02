"""Add MP28 developer platform tables (additive only, reversible).

Revision ID: 027_add_developer_platform
Revises: 026_add_enterprise_identity
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = '027_add_developer_platform'
down_revision = '026_add_enterprise_identity'
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


TABLES = (
    "developer_projects",
    "developer_project_members",
    "developer_environments",
    "extension_definitions",
    "extension_versions",
    "extension_installations",
    "extension_deployments",
    "developer_webhooks",
    "developer_webhook_deliveries",
    "extension_analytics_daily",
    "extension_trust_records",
)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.create_table(
        "developer_projects", _uuid_pk(), *(_ts()),
        _org_fk(),
        sa.Column('slug', sa.String(128), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=False, server_default=''),
        sa.Column('status', sa.String(16), nullable=False, server_default='ACTIVE'),
        sa.Column('created_by', sa.String(255), nullable=False, server_default=''),
        sa.UniqueConstraint('organization_id', 'slug'),
    )
    op.create_table(
        "developer_project_members", _uuid_pk(), *(_ts()),
        sa.Column('project_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('developer_projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('role', sa.String(32), nullable=False, server_default='developer'),
        sa.UniqueConstraint('project_id', 'user_id'),
    )
    op.create_table(
        "developer_environments", _uuid_pk(), *(_ts()),
        sa.Column('project_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('developer_projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(32), nullable=False),
        sa.Column('api_endpoint', sa.String(1024), nullable=False, server_default=''),
        sa.Column('config', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.UniqueConstraint('project_id', 'name'),
    )
    op.create_table(
        "extension_definitions", _uuid_pk(), *(_ts()),
        _org_fk(nullable=True),
        sa.Column('project_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('developer_projects.id', ondelete='SET NULL'), nullable=True),
        sa.Column('slug', sa.String(160), nullable=False),
        sa.Column('extension_type', sa.String(64), nullable=False),
        sa.Column('display_name', sa.String(255), nullable=False, server_default=''),
        sa.Column('description', sa.Text(), nullable=False, server_default=''),
        sa.Column('lifecycle', sa.String(16), nullable=False, server_default='DRAFT'),
        sa.Column('trust_level', sa.String(16), nullable=False, server_default='UNTRUSTED'),
        sa.Column('publisher', sa.String(255), nullable=False, server_default=''),
        sa.Column('license', sa.String(64), nullable=False, server_default='MIT'),
        sa.Column('repository', sa.String(1024), nullable=False, server_default=''),
        sa.Column('quarantined_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('quarantine_reason', sa.Text(), nullable=False, server_default=''),
        sa.UniqueConstraint('organization_id', 'slug'),
    )
    op.create_table(
        "extension_versions", _uuid_pk(), *(_ts()),
        sa.Column('extension_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('extension_definitions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('version', sa.String(32), nullable=False),
        sa.Column('manifest', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('content_digest', sa.String(64), nullable=False, server_default=''),
        sa.Column('artifact_size', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('signature', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('compatibility', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('scan_report', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('validation_report', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('changelog', sa.Text(), nullable=False, server_default=''),
        sa.Column('deprecated', sa.Boolean(), nullable=False, server_default='false'),
        sa.UniqueConstraint('extension_id', 'version'),
    )
    op.create_table(
        "extension_installations", _uuid_pk(), *(_ts()),
        _org_fk(),
        sa.Column('extension_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('extension_definitions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('version_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('extension_versions.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('environment', sa.String(32), nullable=False, server_default='production'),
        sa.Column('granted_permissions', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('config_values', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('installed_by', sa.String(255), nullable=False, server_default=''),
        sa.UniqueConstraint('organization_id', 'extension_id', 'environment'),
    )
    op.create_table(
        "extension_deployments", _uuid_pk(), *(_ts()),
        _org_fk(),
        sa.Column('extension_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('extension_definitions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('version_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('extension_versions.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('environment', sa.String(32), nullable=False, server_default='staging'),
        sa.Column('status', sa.String(16), nullable=False, server_default='PENDING'),
        sa.Column('stages', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('health', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('deployed_by', sa.String(255), nullable=False, server_default=''),
    )
    op.create_table(
        "developer_webhooks", _uuid_pk(), *(_ts()),
        _org_fk(),
        sa.Column('project_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('developer_projects.id', ondelete='SET NULL'), nullable=True),
        sa.Column('url', sa.String(2048), nullable=False),
        sa.Column('events', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('secret_ref', sa.String(512), nullable=False, server_default=''),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default='true'),
    )
    op.create_table(
        "developer_webhook_deliveries", _uuid_pk(), *(_ts()),
        sa.Column('webhook_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('developer_webhooks.id', ondelete='CASCADE'), nullable=False),
        sa.Column('event', sa.String(128), nullable=False),
        sa.Column('delivery_id', sa.String(128), nullable=False, server_default=''),
        sa.Column('status', sa.String(32), nullable=False, server_default='PENDING'),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
    )
    op.create_table(
        "extension_analytics_daily", _uuid_pk(), *(_ts()),
        sa.Column('extension_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('extension_definitions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('day', sa.String(10), nullable=False),
        sa.Column('installs', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('invocations', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('errors', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('avg_latency_ms', sa.Integer(), nullable=False, server_default='0'),
        sa.UniqueConstraint('extension_id', 'day'),
    )
    op.create_table(
        "extension_trust_records", _uuid_pk(), *(_ts()),
        sa.Column('extension_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('extension_definitions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('key_id', sa.String(128), nullable=False),
        sa.Column('public_key', sa.Text(), nullable=False, server_default=''),
        sa.Column('revoked', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('publisher', sa.String(255), nullable=False, server_default=''),
    )


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_table(table)
