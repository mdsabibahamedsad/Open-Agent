"""Add sandbox + secure execution tables (MP18)

Revision ID: 017_add_sandbox
Revises: 016_add_code_agent
Create Date: 2026-09-28 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '017_add_sandbox'
down_revision = '016_add_code_agent'
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
    provider = sa.Enum('docker', 'local', 'kubernetes', name='sandbox_provider')
    sb_status = sa.Enum('CREATING', 'CREATED', 'STARTING', 'READY', 'RUNNING',
                        'WAITING', 'STOPPING', 'STOPPED', 'FAILED', 'EXPIRED',
                        'DESTROYING', 'DESTROYED', name='sandbox_status')
    exec_status = sa.Enum('QUEUED', 'RUNNING', 'WAITING', 'SUCCEEDED', 'FAILED', 'TIMED_OUT',
                          'CANCELLED', 'KILLED', 'RESOURCE_LIMIT', 'POLICY_DENIED',
                          'SANDBOX_ERROR', name='sandbox_execution_status')
    trust = sa.Enum('CORE', 'VERIFIED', 'ORGANIZATION', 'CUSTOM', 'UNTRUSTED',
                    name='image_trust_tier')

    for enum in (provider, sb_status, exec_status, trust):
        enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        'sandboxes',
        _uuid_pk(), _org_fk(),
        sa.Column('sandbox_id', sa.String(100), nullable=False),
        sa.Column('owner_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('task_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('workspace_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('provider', provider, nullable=False, server_default='docker'),
        sa.Column('profile', sa.String(50), nullable=False, server_default='TEST'),
        sa.Column('status', sb_status, nullable=False, server_default='CREATING'),
        sa.Column('provider_handle', sa.String(255), nullable=True),
        sa.Column('image', sa.String(500), nullable=False, server_default=''),
        sa.Column('image_digest', sa.String(255), nullable=False, server_default=''),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('destroyed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resource_config', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('mounts', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('metadata', postgresql.JSONB(), nullable=False, server_default='{}'),
        *_ts(),
    )
    op.create_index('ix_sandboxes_sandbox_id', 'sandboxes', ['sandbox_id'], unique=True)
    op.create_index('ix_sandboxes_org', 'sandboxes', ['organization_id'])
    op.create_index('ix_sandboxes_status', 'sandboxes', ['status'])

    op.create_table(
        'sandbox_profiles',
        _uuid_pk(), _org_fk(nullable=True),
        sa.Column('profile_id', sa.String(50), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('config', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('is_default', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('metadata', postgresql.JSONB(), nullable=False, server_default='{}'),
        *_ts(),
    )
    op.create_index('ix_sandbox_profiles_org', 'sandbox_profiles', ['organization_id'])
    op.create_index('ix_sandbox_profiles_profile_id', 'sandbox_profiles', ['profile_id'])

    op.create_table(
        'sandbox_executions',
        _uuid_pk(), _org_fk(),
        sa.Column('execution_id', sa.String(100), nullable=False),
        sa.Column('sandbox_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('sandboxes.id', ondelete='CASCADE'), nullable=False),
        sa.Column('task_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('command', sa.Text(), nullable=False),
        sa.Column('workdir', sa.String(1024), nullable=False, server_default='/workspace'),
        sa.Column('profile', sa.String(50), nullable=False, server_default='TEST'),
        sa.Column('status', exec_status, nullable=False, server_default='QUEUED'),
        sa.Column('exit_code', sa.Integer(), nullable=True),
        sa.Column('signal', sa.String(50), nullable=True),
        sa.Column('duration_ms', sa.BigInteger(), nullable=True),
        sa.Column('timed_out', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('oom_killed', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('peak_memory_mb', sa.Integer(), nullable=True),
        sa.Column('risk_level', sa.String(20), nullable=False, server_default='MEDIUM'),
        sa.Column('risk_reasons', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('policy_decision', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('stdout_tail', sa.Text(), nullable=True),
        sa.Column('stdout_ref', sa.String(1024), nullable=True),
        sa.Column('stderr_ref', sa.String(1024), nullable=True),
        sa.Column('artifacts', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('metadata', postgresql.JSONB(), nullable=False, server_default='{}'),
        *_ts(),
    )
    op.create_index('ix_sandbox_executions_execution_id', 'sandbox_executions',
                    ['execution_id'], unique=True)
    op.create_index('ix_sandbox_executions_org', 'sandbox_executions', ['organization_id'])
    op.create_index('ix_sandbox_executions_sandbox', 'sandbox_executions', ['sandbox_id'])
    op.create_index('ix_sandbox_executions_status', 'sandbox_executions', ['status'])

    op.create_table(
        'sandbox_leases',
        _uuid_pk(), _org_fk(),
        sa.Column('sandbox_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('sandboxes.id', ondelete='CASCADE'), nullable=False),
        sa.Column('owner', sa.String(255), nullable=False),
        sa.Column('task_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('acquired_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_heartbeat_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('released_at', sa.DateTime(timezone=True), nullable=True),
        *_ts(),
    )
    op.create_index('ix_sandbox_leases_sandbox', 'sandbox_leases', ['sandbox_id'])
    op.create_index('ix_sandbox_leases_expires', 'sandbox_leases', ['expires_at'])

    op.create_table(
        'sandbox_artifacts',
        _uuid_pk(), _org_fk(),
        sa.Column('sandbox_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('sandboxes.id', ondelete='SET NULL'), nullable=True),
        sa.Column('execution_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('sandbox_executions.id', ondelete='SET NULL'), nullable=True),
        sa.Column('name', sa.String(500), nullable=False),
        sa.Column('kind', sa.String(50), nullable=False, server_default='file'),
        sa.Column('storage_ref', sa.String(1024), nullable=False),
        sa.Column('size_bytes', sa.BigInteger(), nullable=True),
        sa.Column('mime_type', sa.String(255), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('metadata', postgresql.JSONB(), nullable=False, server_default='{}'),
        *_ts(),
    )
    op.create_index('ix_sandbox_artifacts_org', 'sandbox_artifacts', ['organization_id'])

    op.create_table(
        'sandbox_events',
        _uuid_pk(), _org_fk(),
        sa.Column('event_id', sa.String(100), nullable=False),
        sa.Column('sandbox_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('sandboxes.id', ondelete='SET NULL'), nullable=True),
        sa.Column('execution_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('sandbox_executions.id', ondelete='SET NULL'), nullable=True),
        sa.Column('type', sa.String(100), nullable=False),
        sa.Column('payload', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('metadata', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_sandbox_events_event_id', 'sandbox_events', ['event_id'], unique=True)
    op.create_index('ix_sandbox_events_org', 'sandbox_events', ['organization_id'])
    op.create_index('ix_sandbox_events_type', 'sandbox_events', ['type'])

    op.create_table(
        'sandbox_image_policies',
        _uuid_pk(), _org_fk(nullable=True),
        sa.Column('image', sa.String(500), nullable=False),
        sa.Column('trust_tier', trust, nullable=False, server_default='CUSTOM'),
        sa.Column('allowed', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('require_digest', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('metadata', postgresql.JSONB(), nullable=False, server_default='{}'),
        *_ts(),
    )
    op.create_index('ix_sandbox_image_policies_org', 'sandbox_image_policies',
                    ['organization_id'])


def downgrade() -> None:
    for table in ('sandbox_image_policies', 'sandbox_events', 'sandbox_artifacts',
                  'sandbox_leases', 'sandbox_executions', 'sandbox_profiles',
                  'sandboxes'):
        op.drop_table(table)
    for name in ('image_trust_tier', 'sandbox_execution_status', 'sandbox_status',
                 'sandbox_provider'):
        sa.Enum(name=name).drop(op.get_bind(), checkfirst=True)
