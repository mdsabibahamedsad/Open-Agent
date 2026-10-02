"""Add MCP integration tables

Revision ID: 011_add_mcp_integration
Revises: 010_add_tool_system
Create Date: 2026-09-26 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '011_add_mcp_integration'
down_revision = '010_add_tool_system'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create MCPTransport enum
    mcp_transport_enum = sa.Enum('stdio', 'streamable_http', 'sse', 'websocket', name='mcp_transport')
    mcp_transport_enum.create(op.get_bind(), checkfirst=True)

    # Create MCPServerScope enum
    mcp_server_scope_enum = sa.Enum('PLATFORM', 'ORGANIZATION', 'TEAM', 'USER', name='mcp_server_scope')
    mcp_server_scope_enum.create(op.get_bind(), checkfirst=True)

    # Create MCPTrustLevel enum
    mcp_trust_level_enum = sa.Enum('CORE', 'VERIFIED', 'ORGANIZATION', 'COMMUNITY', 'UNTRUSTED', name='mcp_trust_level')
    mcp_trust_level_enum.create(op.get_bind(), checkfirst=True)

    # Create MCPServerStatus enum
    mcp_server_status_enum = sa.Enum('ACTIVE', 'INACTIVE', 'CONNECTING', 'ERROR', 'DISCONNECTED', 'DISABLED', name='mcp_server_status')
    mcp_server_status_enum.create(op.get_bind(), checkfirst=True)

    # Create MCPConnectionState enum
    mcp_connection_state_enum = sa.Enum('CONNECTING', 'CONNECTED', 'DEGRADED', 'DISCONNECTED', 'FAILED', name='mcp_connection_state')
    mcp_connection_state_enum.create(op.get_bind(), checkfirst=True)

    # Create mcp_servers table
    op.create_table(
        'mcp_servers',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=sa.text('gen_random_uuid()')),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('display_name', sa.String(255), nullable=True),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('scope', mcp_server_scope_enum, default='ORGANIZATION', nullable=False),
        sa.Column('transport', mcp_transport_enum, default='streamable_http', nullable=False),
        sa.Column('endpoint', sa.String(500), nullable=True),
        sa.Column('command', sa.String(500), nullable=True),
        sa.Column('args', postgresql.JSONB, default=list, nullable=False),
        sa.Column('env', postgresql.JSONB, default=dict, nullable=False),
        sa.Column('working_directory', sa.String(500), nullable=True),
        sa.Column('credential_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('credentials.id', ondelete='SET NULL'), nullable=True, index=True),
        sa.Column('trust_level', mcp_trust_level_enum, default='COMMUNITY', nullable=False),
        sa.Column('status', mcp_server_status_enum, default='DISCONNECTED', nullable=False),
        sa.Column('enabled', sa.Boolean, default=False, nullable=False),
        sa.Column('configuration', postgresql.JSONB, default=dict, nullable=False),
        sa.Column('metadata', postgresql.JSONB, default=dict, nullable=False),
        sa.Column('last_connected_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('connection_error', sa.Text, nullable=True),
        sa.Column('capability_version', sa.Integer, default=0, nullable=False),
        sa.Column('capability_hash', sa.String(64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True, index=True),
        sa.UniqueConstraint('organization_id', 'name', name='uq_mcp_server_org_name'),
    )
    op.create_index('ix_mcp_servers_organization_id', 'mcp_servers', ['organization_id'])
    op.create_index('ix_mcp_servers_transport', 'mcp_servers', ['transport'])
    op.create_index('ix_mcp_servers_status', 'mcp_servers', ['status'])
    op.create_index('ix_mcp_servers_enabled', 'mcp_servers', ['enabled'])
    op.create_index('ix_mcp_servers_trust_level', 'mcp_servers', ['trust_level'])
    op.create_index('ix_mcp_servers_credential_id', 'mcp_servers', ['credential_id'])
    op.create_index('ix_mcp_servers_deleted_at', 'mcp_servers', ['deleted_at'])

    # Create mcp_server_versions table
    op.create_table(
        'mcp_server_versions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=sa.text('gen_random_uuid()')),
        sa.Column('server_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('mcp_servers.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('transport', mcp_transport_enum, nullable=False),
        sa.Column('endpoint', sa.String(500), nullable=True),
        sa.Column('command', sa.String(500), nullable=True),
        sa.Column('args', postgresql.JSONB, default=list, nullable=False),
        sa.Column('env', postgresql.JSONB, default=dict, nullable=False),
        sa.Column('working_directory', sa.String(500), nullable=True),
        sa.Column('credential_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('credentials.id', ondelete='SET NULL'), nullable=True),
        sa.Column('configuration', postgresql.JSONB, default=dict, nullable=False),
        sa.Column('policy', postgresql.JSONB, default=dict, nullable=False),
        sa.Column('protocol_preferences', postgresql.JSONB, default=dict, nullable=False),
        sa.Column('capability_hash', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True, index=True),
    )
    op.create_index('ix_mcp_server_versions_server_id', 'mcp_server_versions', ['server_id'])

    # Create mcp_connections table
    op.create_table(
        'mcp_connections',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=sa.text('gen_random_uuid()')),
        sa.Column('server_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('mcp_servers.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('session_id', sa.String(255), nullable=True),
        sa.Column('protocol_version', sa.String(50), nullable=True),
        sa.Column('state', mcp_connection_state_enum, default='DISCONNECTED', nullable=False),
        sa.Column('capabilities', postgresql.JSONB, default=dict, nullable=False),
        sa.Column('server_info', postgresql.JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('last_activity', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_mcp_connections_server_id', 'mcp_connections', ['server_id'])
    op.create_index('ix_mcp_connections_state', 'mcp_connections', ['state'])
    op.create_index('ix_mcp_connections_session_id', 'mcp_connections', ['session_id'])

    # Create mcp_tools table
    op.create_table(
        'mcp_tools',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=sa.text('gen_random_uuid()')),
        sa.Column('server_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('mcp_servers.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('remote_name', sa.String(255), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('display_name', sa.String(255), nullable=True),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('input_schema', postgresql.JSONB, default=dict, nullable=False),
        sa.Column('output_schema', postgresql.JSONB, nullable=True),
        sa.Column('annotations', postgresql.JSONB, default=dict, nullable=False),
        sa.Column('risk_level', sa.String(20), default='LOW', nullable=False),
        sa.Column('capabilities', postgresql.JSONB, default=list, nullable=False),
        sa.Column('trust_level', mcp_trust_level_enum, default='COMMUNITY', nullable=False),
        sa.Column('status', sa.String(20), default='ACTIVE', nullable=False),
        sa.Column('version', sa.String(50), default='1.0.0', nullable=False),
        sa.Column('schema_hash', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.UniqueConstraint('server_id', 'remote_name', name='uq_mcp_tool_server_remote'),
    )
    op.create_index('ix_mcp_tools_server_id', 'mcp_tools', ['server_id'])
    op.create_index('ix_mcp_tools_remote_name', 'mcp_tools', ['remote_name'])
    op.create_index('ix_mcp_tools_status', 'mcp_tools', ['status'])
    op.create_index('ix_mcp_tools_risk_level', 'mcp_tools', ['risk_level'])

    # Create mcp_resources table
    op.create_table(
        'mcp_resources',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=sa.text('gen_random_uuid()')),
        sa.Column('server_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('mcp_servers.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('uri', sa.String(500), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('title', sa.String(255), nullable=True),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('mime_type', sa.String(100), nullable=True),
        sa.Column('size', sa.Integer, nullable=True),
        sa.Column('metadata', postgresql.JSONB, default=dict, nullable=False),
        sa.Column('status', sa.String(20), default='ACTIVE', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.UniqueConstraint('server_id', 'uri', name='uq_mcp_resource_server_uri'),
    )
    op.create_index('ix_mcp_resources_server_id', 'mcp_resources', ['server_id'])
    op.create_index('ix_mcp_resources_uri', 'mcp_resources', ['uri'])
    op.create_index('ix_mcp_resources_mime_type', 'mcp_resources', ['mime_type'])

    # Create mcp_prompts table
    op.create_table(
        'mcp_prompts',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=sa.text('gen_random_uuid()')),
        sa.Column('server_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('mcp_servers.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('remote_name', sa.String(255), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('title', sa.String(255), nullable=True),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('arguments', postgresql.JSONB, default=list, nullable=False),
        sa.Column('status', sa.String(20), default='ACTIVE', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.UniqueConstraint('server_id', 'remote_name', name='uq_mcp_prompt_server_remote'),
    )
    op.create_index('ix_mcp_prompts_server_id', 'mcp_prompts', ['server_id'])
    op.create_index('ix_mcp_prompts_remote_name', 'mcp_prompts', ['remote_name'])

    # Create mcp_health table
    op.create_table(
        'mcp_health',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=sa.text('gen_random_uuid()')),
        sa.Column('server_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('mcp_servers.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('status', sa.String(20), default='UNKNOWN', nullable=False),
        sa.Column('last_check', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('connection_success', sa.Integer, default=0, nullable=False),
        sa.Column('connection_failure', sa.Integer, default=0, nullable=False),
        sa.Column('tool_success', sa.Integer, default=0, nullable=False),
        sa.Column('tool_failure', sa.Integer, default=0, nullable=False),
        sa.Column('resource_reads', sa.Integer, default=0, nullable=False),
        sa.Column('prompt_reads', sa.Integer, default=0, nullable=False),
        sa.Column('avg_latency_ms', sa.Float, default=0.0, nullable=False),
        sa.Column('timeouts', sa.Integer, default=0, nullable=False),
        sa.Column('protocol_errors', sa.Integer, default=0, nullable=False),
        sa.Column('last_success', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_failure', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_mcp_health_server_id', 'mcp_health', ['server_id'])
    op.create_index('ix_mcp_health_status', 'mcp_health', ['status'])
    op.create_index('ix_mcp_health_last_check', 'mcp_health', ['last_check'])

    # Create mcp_policies table
    op.create_table(
        'mcp_policies',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=sa.text('gen_random_uuid()')),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('team_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('teams.id', ondelete='CASCADE'), nullable=True, index=True),
        sa.Column('agent_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('agents.id', ondelete='CASCADE'), nullable=True, index=True),
        sa.Column('workflow_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('workflows.id', ondelete='CASCADE'), nullable=True, index=True),
        sa.Column('server_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('mcp_servers.id', ondelete='CASCADE'), nullable=True, index=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('allowed_servers', postgresql.JSONB, default=list, nullable=False),
        sa.Column('blocked_servers', postgresql.JSONB, default=list, nullable=False),
        sa.Column('allowed_domains', postgresql.JSONB, default=list, nullable=False),
        sa.Column('blocked_domains', postgresql.JSONB, default=list, nullable=False),
        sa.Column('allowed_trust_levels', mcp_trust_level_enum, default=list, nullable=False),
        sa.Column('max_risk_level', sa.String(20), nullable=True),
        sa.Column('approval_required', postgresql.JSONB, default=dict, nullable=False),
        sa.Column('execution_limits', postgresql.JSONB, default=dict, nullable=False),
        sa.Column('is_active', sa.Boolean, default=True, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )
    op.create_index('ix_mcp_policies_organization_id', 'mcp_policies', ['organization_id'])
    op.create_index('ix_mcp_policies_team_id', 'mcp_policies', ['team_id'])
    op.create_index('ix_mcp_policies_agent_id', 'mcp_policies', ['agent_id'])
    op.create_index('ix_mcp_policies_workflow_id', 'mcp_policies', ['workflow_id'])
    op.create_index('ix_mcp_policies_server_id', 'mcp_policies', ['server_id'])
    op.create_index('ix_mcp_policies_is_active', 'mcp_policies', ['is_active'])

    # Create mcp_tool_executions table
    op.create_table(
        'mcp_tool_executions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=sa.text('gen_random_uuid()')),
        sa.Column('server_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('mcp_servers.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('mcp_tool_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('mcp_tools.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('agent_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('agents.id', ondelete='SET NULL'), nullable=True, index=True),
        sa.Column('workflow_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('workflows.id', ondelete='SET NULL'), nullable=True, index=True),
        sa.Column('tool_execution_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tool_executions.id', ondelete='SET NULL'), nullable=True, index=True),
        sa.Column('status', sa.String(20), default='QUEUED', nullable=False),
        sa.Column('input', postgresql.JSONB, default=dict, nullable=False),
        sa.Column('output', postgresql.JSONB, nullable=True),
        sa.Column('error', postgresql.JSONB, nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('duration_ms', sa.Integer, default=0, nullable=False),
        sa.Column('retry_count', sa.Integer, default=0, nullable=False),
        sa.Column('is_retryable', sa.Boolean, default=False, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_mcp_tool_executions_server_id', 'mcp_tool_executions', ['server_id'])
    op.create_index('ix_mcp_tool_executions_mcp_tool_id', 'mcp_tool_executions', ['mcp_tool_id'])
    op.create_index('ix_mcp_tool_executions_organization_id', 'mcp_tool_executions', ['organization_id'])
    op.create_index('ix_mcp_tool_executions_agent_id', 'mcp_tool_executions', ['agent_id'])
    op.create_index('ix_mcp_tool_executions_workflow_id', 'mcp_tool_executions', ['workflow_id'])
    op.create_index('ix_mcp_tool_executions_status', 'mcp_tool_executions', ['status'])
    op.create_index('ix_mcp_tool_executions_started_at', 'mcp_tool_executions', ['started_at'])


def downgrade() -> None:
    op.drop_table('mcp_tool_executions')
    op.drop_table('mcp_policies')
    op.drop_table('mcp_health')
    op.drop_table('mcp_prompts')
    op.drop_table('mcp_resources')
    op.drop_table('mcp_tools')
    op.drop_table('mcp_connections')
    op.drop_table('mcp_server_versions')
    op.drop_table('mcp_servers')

    mcp_connection_state_enum = sa.Enum(name='mcp_connection_state')
    mcp_connection_state_enum.drop(op.get_bind(), checkfirst=True)

    mcp_server_status_enum = sa.Enum(name='mcp_server_status')
    mcp_server_status_enum.drop(op.get_bind(), checkfirst=True)

    mcp_trust_level_enum = sa.Enum(name='mcp_trust_level')
    mcp_trust_level_enum.drop(op.get_bind(), checkfirst=True)

    mcp_server_scope_enum = sa.Enum(name='mcp_server_scope')
    mcp_server_scope_enum.drop(op.get_bind(), checkfirst=True)

    mcp_transport_enum = sa.Enum(name='mcp_transport')
    mcp_transport_enum.drop(op.get_bind(), checkfirst=True)