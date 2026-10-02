"""Add tool system tables

Revision ID: 010_add_tool_system
Revises: 009
Create Date: 2026-09-26 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '010_add_tool_system'
down_revision = '009'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create tool_type enum
    tool_type_enum = sa.Enum('builtin', 'custom', 'mcp', 'api', 'community', name='tool_type')
    tool_type_enum.create(op.get_bind(), checkfirst=True)

    # Create tool_category enum
    tool_category_enum = sa.Enum(
        'communication', 'web', 'browser', 'http', 'database', 'filesystem', 'code', 'shell',
        'search', 'documents', 'media', 'calendar', 'email', 'messaging', 'crm', 'analytics',
        'finance', 'developer', 'system', 'ai', 'utility', 'custom',
        name='tool_category'
    )
    tool_category_enum.create(op.get_bind(), checkfirst=True)

    # Create tool_capability enum
    tool_capability_enum = sa.Enum(
        'read', 'write', 'delete', 'network', 'filesystem', 'process_execution',
        'browser_control', 'database_access', 'credential_access', 'external_api',
        'message_send', 'email_send', 'code_execution', 'system_control', 'financial_action',
        name='tool_capability'
    )
    tool_capability_enum.create(op.get_bind(), checkfirst=True)

    # Create tool_risk_level enum
    tool_risk_level_enum = sa.Enum('LOW', 'MEDIUM', 'HIGH', 'CRITICAL', name='tool_risk_level')
    tool_risk_level_enum.create(op.get_bind(), checkfirst=True)

    # Create tool_execution_mode enum
    tool_execution_mode_enum = sa.Enum('SYNC', 'ASYNC', 'STREAMING', 'BACKGROUND', 'WAITING', name='tool_execution_mode')
    tool_execution_mode_enum.create(op.get_bind(), checkfirst=True)

    # Create tool_lifecycle_status enum
    tool_lifecycle_status_enum = sa.Enum('DRAFT', 'ACTIVE', 'DISABLED', 'DEPRECATED', 'REVOKED', name='tool_lifecycle_status')
    tool_lifecycle_status_enum.create(op.get_bind(), checkfirst=True)

    # Create tool_trust_level enum
    tool_trust_level_enum = sa.Enum('CORE', 'VERIFIED', 'ORGANIZATION', 'COMMUNITY', 'UNTRUSTED', name='tool_trust_level')
    tool_trust_level_enum.create(op.get_bind(), checkfirst=True)

    # Create tool_provider_type enum
    tool_provider_type_enum = sa.Enum(
        'BUILTIN', 'HTTP_API', 'PYTHON_PACKAGE', 'JAVASCRIPT_PACKAGE', 'EXTERNAL_SERVICE',
        'MCP', 'MARKETPLACE', 'BROWSER', 'CODING_RUNTIME', 'CUSTOM',
        name='tool_provider_type'
    )
    tool_provider_type_enum.create(op.get_bind(), checkfirst=True)

    # Create tools table
    op.create_table(
        'tools',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=sa.text('gen_random_uuid()')),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=True, index=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('slug', sa.String(100), nullable=False, index=True),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('tool_type', tool_type_enum, default='custom', nullable=False),
        sa.Column('category', tool_category_enum, default='custom', nullable=False),
        sa.Column('status', tool_lifecycle_status_enum, default='DRAFT', nullable=False),
        sa.Column('display_name', sa.String(255), nullable=True),
        sa.Column('icon', sa.String(100), nullable=True),
        sa.Column('documentation_url', sa.Text, nullable=True),
        sa.Column('provider', sa.String(100), default='builtin', nullable=False),
        sa.Column('provider_type', tool_provider_type_enum, default='BUILTIN', nullable=False),
        sa.Column('version', sa.String(50), default='1.0.0', nullable=False),
        sa.Column('capabilities', postgresql.JSONB, default=list, nullable=False),
        sa.Column('risk_level', tool_risk_level_enum, default='LOW', nullable=False),
        sa.Column('execution_mode', tool_execution_mode_enum, default='SYNC', nullable=False),
        sa.Column('timeout', sa.Integer, default=30000, nullable=False),
        sa.Column('retry_policy', postgresql.JSONB, default={}, nullable=False),
        sa.Column('supports_streaming', sa.Boolean, default=False, nullable=False),
        sa.Column('supports_cancellation', sa.Boolean, default=True, nullable=False),
        sa.Column('supports_idempotency', sa.Boolean, default=False, nullable=False),
        sa.Column('trust_level', tool_trust_level_enum, default='ORGANIZATION', nullable=False),
        sa.Column('input_schema', postgresql.JSONB, default={}, nullable=False),
        sa.Column('output_schema', postgresql.JSONB, nullable=True),
        sa.Column('configuration', postgresql.JSONB, default={}, nullable=False),
        sa.Column('metadata', postgresql.JSONB, default={}, nullable=False),
        sa.Column('tags', postgresql.JSONB, default=list, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True, index=True),
        sa.UniqueConstraint('organization_id', 'slug', 'version', name='uq_tool_org_slug_version'),
    )
    op.create_index('ix_tools_organization_id', 'tools', ['organization_id'])
    op.create_index('ix_tools_tool_type', 'tools', ['tool_type'])
    op.create_index('ix_tools_category', 'tools', ['category'])
    op.create_index('ix_tools_status', 'tools', ['status'])
    op.create_index('ix_tools_risk_level', 'tools', ['risk_level'])
    op.create_index('ix_tools_trust_level', 'tools', ['trust_level'])
    op.create_index('ix_tools_provider', 'tools', ['provider'])
    op.create_index('ix_tools_deleted_at', 'tools', ['deleted_at'])

    # Create tool_versions table
    op.create_table(
        'tool_versions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=sa.text('gen_random_uuid()')),
        sa.Column('tool_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tools.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('version', sa.String(50), nullable=False),
        sa.Column('display_name', sa.String(255), nullable=True),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('capabilities', postgresql.JSONB, default=list, nullable=False),
        sa.Column('risk_level', tool_risk_level_enum, default='LOW', nullable=False),
        sa.Column('execution_mode', tool_execution_mode_enum, default='SYNC', nullable=False),
        sa.Column('timeout', sa.Integer, default=30000, nullable=False),
        sa.Column('retry_policy', postgresql.JSONB, default={}, nullable=False),
        sa.Column('supports_streaming', sa.Boolean, default=False, nullable=False),
        sa.Column('supports_cancellation', sa.Boolean, default=True, nullable=False),
        sa.Column('supports_idempotency', sa.Boolean, default=False, nullable=False),
        sa.Column('trust_level', tool_trust_level_enum, default='ORGANIZATION', nullable=False),
        sa.Column('input_schema', postgresql.JSONB, default={}, nullable=False),
        sa.Column('output_schema', postgresql.JSONB, nullable=True),
        sa.Column('configuration', postgresql.JSONB, default={}, nullable=False),
        sa.Column('metadata', postgresql.JSONB, default={}, nullable=False),
        sa.Column('status', tool_lifecycle_status_enum, default='DRAFT', nullable=False),
        sa.Column('checksum', sa.String(64), nullable=False),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deprecated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True, index=True),
        sa.UniqueConstraint('tool_id', 'version', name='uq_tool_version_tool_version'),
    )
    op.create_index('ix_tool_versions_tool_id', 'tool_versions', ['tool_id'])
    op.create_index('ix_tool_versions_status', 'tool_versions', ['status'])
    op.create_index('ix_tool_versions_published_at', 'tool_versions', ['published_at'])

    # Create tool_providers table
    op.create_table(
        'tool_providers',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=sa.text('gen_random_uuid()')),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=True, index=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('provider_type', tool_provider_type_enum, nullable=False),
        sa.Column('configuration', postgresql.JSONB, default={}, nullable=False),
        sa.Column('supported_tool_types', postgresql.JSONB, default=list, nullable=False),
        sa.Column('health_status', sa.String(20), default='UNKNOWN', nullable=False),
        sa.Column('last_health_check', sa.DateTime(timezone=True), nullable=True),
        sa.Column('is_active', sa.Boolean, default=True, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True, index=True),
    )
    op.create_index('ix_tool_providers_organization_id', 'tool_providers', ['organization_id'])
    op.create_index('ix_tool_providers_provider_type', 'tool_providers', ['provider_type'])
    op.create_index('ix_tool_providers_health_status', 'tool_providers', ['health_status'])

    # Create tool_policies table
    op.create_table(
        'tool_policies',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=sa.text('gen_random_uuid()')),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=True, index=True),
        sa.Column('team_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('teams.id', ondelete='CASCADE'), nullable=True, index=True),
        sa.Column('agent_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('agents.id', ondelete='CASCADE'), nullable=True, index=True),
        sa.Column('workflow_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('workflows.id', ondelete='CASCADE'), nullable=True, index=True),
        sa.Column('tool_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tools.id', ondelete='CASCADE'), nullable=True, index=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('priority', sa.Integer, default=0, nullable=False),
        sa.Column('allowed_tools', postgresql.JSONB, default=list, nullable=False),
        sa.Column('blocked_tools', postgresql.JSONB, default=list, nullable=False),
        sa.Column('allowed_categories', postgresql.JSONB, default=list, nullable=False),
        sa.Column('blocked_categories', postgresql.JSONB, default=list, nullable=False),
        sa.Column('allowed_risk_levels', postgresql.JSONB, default=list, nullable=False),
        sa.Column('max_risk_level', tool_risk_level_enum, nullable=True),
        sa.Column('allowed_capabilities', postgresql.JSONB, default=list, nullable=False),
        sa.Column('blocked_capabilities', postgresql.JSONB, default=list, nullable=False),
        sa.Column('allowed_domains', postgresql.JSONB, default=list, nullable=False),
        sa.Column('blocked_domains', postgresql.JSONB, default=list, nullable=False),
        sa.Column('allowed_organizations', postgresql.JSONB, default=list, nullable=False),
        sa.Column('approval_required', postgresql.JSONB, default={}, nullable=False),
        sa.Column('execution_limits', postgresql.JSONB, default={}, nullable=False),
        sa.Column('is_active', sa.Boolean, default=True, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )
    op.create_index('ix_tool_policies_organization_id', 'tool_policies', ['organization_id'])
    op.create_index('ix_tool_policies_team_id', 'tool_policies', ['team_id'])
    op.create_index('ix_tool_policies_agent_id', 'tool_policies', ['agent_id'])
    op.create_index('ix_tool_policies_workflow_id', 'tool_policies', ['workflow_id'])
    op.create_index('ix_tool_policies_tool_id', 'tool_policies', ['tool_id'])
    op.create_index('ix_tool_policies_priority', 'tool_policies', ['priority'])
    op.create_index('ix_tool_policies_is_active', 'tool_policies', ['is_active'])

    # Create tool_executions table
    op.create_table(
        'tool_executions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=sa.text('gen_random_uuid()')),
        sa.Column('tool_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tools.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('tool_version_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tool_versions.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('agent_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('agents.id', ondelete='SET NULL'), nullable=True, index=True),
        sa.Column('workflow_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('workflows.id', ondelete='SET NULL'), nullable=True, index=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True),
        sa.Column('node_execution_id', postgresql.UUID(as_uuid=True), nullable=True, index=True),
        sa.Column('status', sa.String(30), default='QUEUED', nullable=False),
        sa.Column('input', postgresql.JSONB, default={}, nullable=False),
        sa.Column('output', postgresql.JSONB, nullable=True),
        sa.Column('error', postgresql.JSONB, nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('duration_ms', sa.Integer, default=0, nullable=False),
        sa.Column('retry_count', sa.Integer, default=0, nullable=False),
        sa.Column('estimated_cost', sa.Float, nullable=True),
        sa.Column('actual_cost', sa.Float, nullable=True),
        sa.Column('metadata', postgresql.JSONB, default={}, nullable=False),
        sa.Column('idempotency_key', sa.String(100), nullable=True, index=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_tool_executions_organization_id', 'tool_executions', ['organization_id'])
    op.create_index('ix_tool_executions_tool_id', 'tool_executions', ['tool_id'])
    op.create_index('ix_tool_executions_agent_id', 'tool_executions', ['agent_id'])
    op.create_index('ix_tool_executions_workflow_id', 'tool_executions', ['workflow_id'])
    op.create_index('ix_tool_executions_user_id', 'tool_executions', ['user_id'])
    op.create_index('ix_tool_executions_status', 'tool_executions', ['status'])
    op.create_index('ix_tool_executions_started_at', 'tool_executions', ['started_at'])
    op.create_index('ix_tool_executions_idempotency_key', 'tool_executions', ['idempotency_key'])

    # Create tool_execution_events table
    op.create_table(
        'tool_execution_events',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=sa.text('gen_random_uuid()')),
        sa.Column('execution_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tool_executions.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('event_type', sa.String(50), nullable=False),
        sa.Column('payload', postgresql.JSONB, default={}, nullable=False),
        sa.Column('sequence', sa.Integer, default=0, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_tool_execution_events_execution_id', 'tool_execution_events', ['execution_id'])
    op.create_index('ix_tool_execution_events_event_type', 'tool_execution_events', ['event_type'])
    op.create_index('ix_tool_execution_events_sequence', 'tool_execution_events', ['sequence'])

    # Create tool_health table
    op.create_table(
        'tool_health',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=sa.text('gen_random_uuid()')),
        sa.Column('tool_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tools.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('status', sa.String(20), default='UNKNOWN', nullable=False),
        sa.Column('last_check', sa.DateTime(timezone=True), nullable=False),
        sa.Column('success_count', sa.Integer, default=0, nullable=False),
        sa.Column('failure_count', sa.Integer, default=0, nullable=False),
        sa.Column('avg_latency_ms', sa.Float, default=0.0, nullable=False),
        sa.Column('last_success', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_failure', sa.DateTime(timezone=True), nullable=True),
        sa.Column('error_rate', sa.Float, default=0.0, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_tool_health_tool_id', 'tool_health', ['tool_id'])
    op.create_index('ix_tool_health_status', 'tool_health', ['status'])
    op.create_index('ix_tool_health_last_check', 'tool_health', ['last_check'])

    # Create tool_usage table
    op.create_table(
        'tool_usage',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=sa.text('gen_random_uuid()')),
        sa.Column('tool_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tools.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('execution_count', sa.Integer, default=0, nullable=False),
        sa.Column('success_count', sa.Integer, default=0, nullable=False),
        sa.Column('failure_count', sa.Integer, default=0, nullable=False),
        sa.Column('total_duration_ms', sa.Integer, default=0, nullable=False),
        sa.Column('total_cost', sa.Float, default=0.0, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('tool_id', 'organization_id', 'date', name='uq_tool_usage_tool_org_date'),
    )
    op.create_index('ix_tool_usage_tool_id', 'tool_usage', ['tool_id'])
    op.create_index('ix_tool_usage_organization_id', 'tool_usage', ['organization_id'])
    op.create_index('ix_tool_usage_date', 'tool_usage', ['date'])


def downgrade() -> None:
    op.drop_table('tool_usage')
    op.drop_table('tool_health')
    op.drop_table('tool_execution_events')
    op.drop_table('tool_executions')
    op.drop_table('tool_policies')
    op.drop_table('tool_providers')
    op.drop_table('tool_versions')
    op.drop_table('tools')

    tool_provider_type_enum = sa.Enum(name='tool_provider_type')
    tool_provider_type_enum.drop(op.get_bind(), checkfirst=True)

    tool_trust_level_enum = sa.Enum(name='tool_trust_level')
    tool_trust_level_enum.drop(op.get_bind(), checkfirst=True)

    tool_lifecycle_status_enum = sa.Enum(name='tool_lifecycle_status')
    tool_lifecycle_status_enum.drop(op.get_bind(), checkfirst=True)

    tool_execution_mode_enum = sa.Enum(name='tool_execution_mode')
    tool_execution_mode_enum.drop(op.get_bind(), checkfirst=True)

    tool_risk_level_enum = sa.Enum(name='tool_risk_level')
    tool_risk_level_enum.drop(op.get_bind(), checkfirst=True)

    tool_capability_enum = sa.Enum(name='tool_capability')
    tool_capability_enum.drop(op.get_bind(), checkfirst=True)

    tool_category_enum = sa.Enum(name='tool_category')
    tool_category_enum.drop(op.get_bind(), checkfirst=True)

    tool_type_enum = sa.Enum(name='tool_type')
    tool_type_enum.drop(op.get_bind(), checkfirst=True)