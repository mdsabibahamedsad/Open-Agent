"""Add MP21 universal connector tables + migrate legacy integrations.

Revision ID: 020_add_connectors
Revises: 019_add_evaluator
Create Date: 2026-09-30 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '020_add_connectors'
down_revision = '019_add_evaluator'
branch_labels = None
depends_on = None


def _uuid_pk():
    return sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                     server_default=sa.text('gen_random_uuid()'))


def _org_fk(nullable=False):
    return sa.Column('organization_id', postgresql.UUID(as_uuid=True),
                     sa.ForeignKey('organizations.id', ondelete='CASCADE'),
                     nullable=nullable)


def _ts():
    return (sa.Column('created_at', sa.DateTime(timezone=True),
                      server_default=sa.func.now(), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True),
                      server_default=sa.func.now(), nullable=False))


def upgrade() -> None:
    for name, values in (
        ("connector_type", ("official", "community", "custom", "internal",
                            "mcp_backed", "http_generic", "database",
                            "webhook_only")),
        ("connector_trust", ("core", "verified", "organization", "community",
                             "custom", "untrusted")),
        ("connector_status", ("draft", "active", "disabled", "deprecated",
                              "suspended", "error")),
        ("connection_status", ("unconnected", "connecting", "connected",
                               "degraded", "auth_expired", "error",
                               "disconnected")),
        ("connection_scope", ("platform", "organization", "team", "user",
                              "workflow", "agent")),
        ("sharing_policy", ("private", "team", "organization", "workflow_only")),
        ("connector_health", ("healthy", "degraded", "auth_expired",
                              "rate_limited", "error", "unknown")),
    ):
        op.execute(
            sa.text("DO $$ BEGIN CREATE TYPE %s AS ENUM (%s); "
                    "EXCEPTION WHEN duplicate_object THEN NULL; END $$;"
                    % (name, ", ".join(f"'{v}'" for v in values))))

    # Threat telemetry for the connector layer (additive).
    for value in ('connector.cross_tenant_attempt', 'connector.credential_failure',
                  'connector.webhook_forgery', 'connector.webhook_replay',
                  'connector.signature_invalid',
                  'connector.policy_bypass_attempt', 'connector.oauth_csrf',
                  'connector.token_replay',
                  'connector.privilege_escalation_attempt',
                  'connector.exfiltration_attempt', 'connector.unusual_usage'):
        op.execute(f"ALTER TYPE security_event_type ADD VALUE IF NOT EXISTS '{value}'")

    op.create_table(
        'connectors', _uuid_pk(),
        sa.Column('slug', sa.String(100), nullable=False, unique=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('category', sa.String(64), nullable=False, server_default='automation'),
        sa.Column('connector_type', postgresql.ENUM('official', 'community', 'custom',
                                                    'internal', 'mcp_backed', 'http_generic',
                                                    'database', 'webhook_only',
                                                    name='connector_type',
                                                    create_type=False),
                  nullable=False, server_default='official'),
        sa.Column('trust', postgresql.ENUM('core', 'verified', 'organization',
                                           'community', 'custom', 'untrusted',
                                           name='connector_trust', create_type=False),
                  nullable=False, server_default='untrusted'),
        sa.Column('status', postgresql.ENUM('draft', 'active', 'disabled',
                                            'deprecated', 'suspended', 'error',
                                            name='connector_status', create_type=False),
                  nullable=False, server_default='draft'),
        sa.Column('description', sa.Text(), nullable=False, server_default=''),
        sa.Column('publisher', sa.String(120), nullable=False, server_default=''),
        sa.Column('license', sa.String(64), nullable=False, server_default=''),
        sa.Column('documentation_url', sa.String(500), nullable=False, server_default=''),
        sa.Column('current_version', sa.String(32), nullable=False,
                  server_default='1.0.0'),
        sa.Column('signature', sa.String(2000), nullable=False, server_default=''),
        sa.Column('content_hash', sa.String(64), nullable=False, server_default=''),
        *_ts(),
    )
    op.create_index('ix_connectors_category', 'connectors', ['category'])
    op.create_index('ix_connectors_trust', 'connectors', ['trust'])
    op.create_index('ix_connectors_status', 'connectors', ['status'])

    op.create_table(
        'connector_versions', _uuid_pk(),
        sa.Column('connector_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('connectors.id', ondelete='CASCADE'), nullable=False),
        sa.Column('version', sa.String(32), nullable=False),
        sa.Column('manifest', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('content_hash', sa.String(64), nullable=False, server_default=''),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        *_ts(),
    )
    op.create_index('ix_connector_versions_connector', 'connector_versions',
                    ['connector_id'])

    op.create_table(
        'connector_capabilities', _uuid_pk(),
        sa.Column('version_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('connector_versions.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('capability_id', sa.String(160), nullable=False),
        sa.Column('description', sa.Text(), nullable=False, server_default=''),
        sa.Column('risk_level', sa.String(20), nullable=False,
                  server_default='LOW'),
        *_ts(),
    )
    op.create_index('ix_connector_capabilities_version', 'connector_capabilities',
                    ['version_id'])
    op.create_index('ix_connector_capabilities_capability', 'connector_capabilities',
                    ['capability_id'])

    op.create_table(
        'connector_actions', _uuid_pk(),
        sa.Column('version_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('connector_versions.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('action_id', sa.String(160), nullable=False),
        sa.Column('name', sa.String(120), nullable=False, server_default=''),
        sa.Column('description', sa.Text(), nullable=False, server_default=''),
        sa.Column('input_schema', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('output_schema', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('required_capabilities', sa.JSON(), nullable=False,
                  server_default='[]'),
        sa.Column('risk_level', sa.String(20), nullable=False,
                  server_default='MEDIUM'),
        sa.Column('supports_idempotency', sa.Boolean(), nullable=False,
                  server_default='false'),
        sa.Column('timeout_seconds', sa.Integer(), nullable=False,
                  server_default='30'),
        sa.Column('mutation', sa.Boolean(), nullable=False, server_default='true'),
        *_ts(),
    )
    op.create_index('ix_connector_actions_version', 'connector_actions',
                    ['version_id'])
    op.create_index('ix_connector_actions_action', 'connector_actions',
                    ['action_id'])

    op.create_table(
        'connector_triggers', _uuid_pk(),
        sa.Column('version_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('connector_versions.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('trigger_id', sa.String(160), nullable=False),
        sa.Column('name', sa.String(120), nullable=False, server_default=''),
        sa.Column('description', sa.Text(), nullable=False, server_default=''),
        sa.Column('kind', sa.String(32), nullable=False,
                  server_default='webhook'),
        sa.Column('event_types', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('payload_schema', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('poll_config', sa.JSON(), nullable=False, server_default='{}'),
        *_ts(),
    )
    op.create_index('ix_connector_triggers_version', 'connector_triggers',
                    ['version_id'])
    op.create_index('ix_connector_triggers_trigger', 'connector_triggers',
                    ['trigger_id'])

    op.create_table(
        'connector_resources', _uuid_pk(),
        sa.Column('version_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('connector_versions.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('kind', sa.String(64), nullable=False),
        sa.Column('provider_kind', sa.String(128), nullable=False, server_default=''),
        sa.Column('schema', sa.JSON(), nullable=False, server_default='{}'),
        *_ts(),
    )
    op.create_index('ix_connector_resources_version', 'connector_resources',
                    ['version_id'])

    op.create_table(
        'connector_connections', _uuid_pk(), _org_fk(),
        sa.Column('connector_id', sa.String(100), nullable=False),
        sa.Column('connector_version', sa.String(32), nullable=False,
                  server_default='1.0.0'),
        sa.Column('name', sa.String(255), nullable=False, server_default=''),
        sa.Column('status', postgresql.ENUM('unconnected', 'connecting', 'connected',
                                            'degraded', 'auth_expired', 'error',
                                            'disconnected', name='connection_status',
                                            create_type=False),
                  nullable=False, server_default='unconnected'),
        sa.Column('scope', postgresql.ENUM('platform', 'organization', 'team',
                                           'user', 'workflow', 'agent',
                                           name='connection_scope', create_type=False),
                  nullable=False, server_default='organization'),
        sa.Column('sharing_policy', postgresql.ENUM('private', 'team', 'organization',
                                                    'workflow_only',
                                                    name='sharing_policy',
                                                    create_type=False),
                  nullable=False, server_default='private'),
        sa.Column('owner_user_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('team_ids', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('workflow_ids', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('credential_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('credentials.id', ondelete='SET NULL'), nullable=True),
        sa.Column('granted_capabilities', sa.JSON(), nullable=False,
                  server_default='[]'),
        sa.Column('policy_config', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('config', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('oauth_state', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('health', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=False, server_default=''),
        *_ts(),
    )
    op.create_index('ix_connector_connections_org', 'connector_connections',
                    ['organization_id'])
    op.create_index('ix_connector_connections_connector', 'connector_connections',
                    ['connector_id'])
    op.create_index('ix_connector_connections_status', 'connector_connections',
                    ['status'])
    op.create_index('ix_connector_connections_owner', 'connector_connections',
                    ['owner_user_id'])
    op.create_index('ix_connector_connections_credential', 'connector_connections',
                    ['credential_id'])

    op.create_table(
        'connector_permissions', _uuid_pk(),
        sa.Column('connection_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('connector_connections.id', ondelete='CASCADE'),
                  nullable=False),
        _org_fk(),
        sa.Column('grantee_type', sa.String(32), nullable=False, server_default='user'),
        sa.Column('grantee_id', sa.String(100), nullable=False, server_default=''),
        sa.Column('capabilities', sa.JSON(), nullable=False, server_default='[]'),
        *_ts(),
    )
    op.create_index('ix_connector_permissions_connection', 'connector_permissions',
                    ['connection_id'])
    op.create_index('ix_connector_permissions_grantee', 'connector_permissions',
                    ['grantee_type', 'grantee_id'])

    op.create_table(
        'connector_webhooks', _uuid_pk(),
        sa.Column('connection_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('connector_connections.id', ondelete='CASCADE'),
                  nullable=False),
        _org_fk(),
        sa.Column('connector_id', sa.String(100), nullable=False),
        sa.Column('endpoint', sa.String(200), nullable=False),
        sa.Column('event_types', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('verify_mode', sa.String(32), nullable=False,
                  server_default='hmac_sha256'),
        sa.Column('secret_hash', sa.String(64), nullable=False, server_default=''),
        sa.Column('secret_prefix', sa.String(16), nullable=False, server_default=''),
        sa.Column('secret_cipher', sa.Text(), nullable=False, server_default=''),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('failure_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_delivery_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_signature_ok', sa.Boolean(), nullable=True),
        *_ts(),
    )
    op.create_index('ix_connector_webhooks_connection', 'connector_webhooks',
                    ['connection_id'])
    op.create_index('ix_connector_webhooks_endpoint', 'connector_webhooks',
                    ['connector_id', 'endpoint'])

    op.create_table(
        'connector_events', _uuid_pk(),
        sa.Column('webhook_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('connector_webhooks.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('connection_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('connector_connections.id', ondelete='SET NULL'),
                  nullable=True),
        _org_fk(),
        sa.Column('event_type', sa.String(160), nullable=False),
        sa.Column('provider', sa.String(100), nullable=False),
        sa.Column('resource_id', sa.String(256), nullable=False, server_default=''),
        sa.Column('delivery_id', sa.String(128), nullable=False, server_default=''),
        sa.Column('payload_reference', sa.String(256), nullable=False,
                  server_default=''),
        sa.Column('attributes', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('processed', sa.Boolean(), nullable=False, server_default='false'),
        *_ts(),
    )
    op.create_index('ix_connector_events_org_type', 'connector_events',
                    ['organization_id', 'event_type'])
    op.create_index('ix_connector_events_delivery', 'connector_events',
                    ['delivery_id'])

    op.create_table(
        'connector_health', _uuid_pk(),
        sa.Column('connection_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('connector_connections.id', ondelete='CASCADE'),
                  nullable=False),
        _org_fk(),
        sa.Column('state', postgresql.ENUM('healthy', 'degraded', 'auth_expired',
                                           'rate_limited', 'error', 'unknown',
                                           name='connector_health',
                                           create_type=False),
                  nullable=False, server_default='unknown'),
        sa.Column('latency_ms', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('auth_ok', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('detail', sa.String(500), nullable=False, server_default=''),
        *_ts(),
    )
    op.create_index('ix_connector_health_connection', 'connector_health',
                    ['connection_id'])

    op.create_table(
        'connector_usage', _uuid_pk(),
        sa.Column('connection_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('connector_connections.id', ondelete='CASCADE'),
                  nullable=False),
        _org_fk(),
        sa.Column('period', sa.String(16), nullable=False, server_default=''),
        sa.Column('calls', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('successes', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('failures', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('latency_ms_total', sa.Integer(), nullable=False, server_default='0'),
        *_ts(),
    )
    op.create_index('ix_connector_usage_connection_period', 'connector_usage',
                    ['connection_id', 'period'])

    op.create_table(
        'connector_cursors', _uuid_pk(),
        sa.Column('connection_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('connector_connections.id', ondelete='CASCADE'),
                  nullable=False),
        _org_fk(),
        sa.Column('trigger_id', sa.String(160), nullable=False),
        sa.Column('state', sa.JSON(), nullable=False, server_default='{}'),
        *_ts(),
    )
    op.create_index('ix_connector_cursors_connection_trigger', 'connector_cursors',
                    ['connection_id', 'trigger_id'])

    # Migrate legacy integrations rows into connector_connections (MP21 §109).
    # provider enum -> connector slug; unknown/custom providers become custom.
    op.execute(sa.text("""
        INSERT INTO connector_connections
            (id, organization_id, connector_id, connector_version, name, status,
             scope, sharing_policy, credential_id, granted_capabilities,
             policy_config, config, oauth_state, health, created_at, updated_at)
        SELECT gen_random_uuid(), organization_id,
               CASE provider
                 WHEN 'github' THEN 'github' WHEN 'gitlab' THEN 'gitlab'
                 WHEN 'google' THEN 'google_calendar' WHEN 'microsoft' THEN 'custom'
                 WHEN 'slack' THEN 'slack' WHEN 'discord' THEN 'discord'
                 WHEN 'notion' THEN 'notion' WHEN 'telegram' THEN 'telegram'
                 WHEN 'hubspot' THEN 'hubspot' WHEN 'stripe' THEN 'custom'
                 WHEN 'postgres' THEN 'postgres' WHEN 'mysql' THEN 'custom'
                 WHEN 'custom' THEN 'custom' ELSE 'custom' END,
               '1.0.0', name,
               CASE status WHEN 'active' THEN 'connected'::connection_status
                           WHEN 'error' THEN 'error'::connection_status
                           ELSE 'unconnected'::connection_status END,
               'organization'::connection_scope, 'private'::sharing_policy,
               credential_id, '[]'::json, '{}'::json,
               COALESCE(configuration, '{}'::json), '{}'::json, '{}'::json,
               created_at, updated_at
        FROM integrations WHERE deleted_at IS NULL
    """))


def downgrade() -> None:
    for table in ('connector_cursors', 'connector_usage', 'connector_health',
                  'connector_events', 'connector_webhooks',
                  'connector_permissions', 'connector_connections',
                  'connector_resources', 'connector_triggers', 'connector_actions',
                  'connector_capabilities', 'connector_versions', 'connectors'):
        op.drop_table(table)
    # Enum types and migrated rows are left in place (safe downgrade).
