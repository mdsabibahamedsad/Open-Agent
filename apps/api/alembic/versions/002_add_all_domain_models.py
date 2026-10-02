"""Add all domain models

Revision ID: 002
Revises: 001
Create Date: 2024-01-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '002'
down_revision = '001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Agent types and statuses
    op.execute("CREATE TYPE agent_type AS ENUM ('chat', 'workflow', 'autonomous', 'assistant')")
    op.execute("CREATE TYPE agent_status AS ENUM ('draft', 'active', 'archived', 'deprecated')")
    
    # Workflow types and statuses
    op.execute("CREATE TYPE workflow_status AS ENUM ('draft', 'active', 'archived', 'deprecated')")
    op.execute("CREATE TYPE workflow_execution_status AS ENUM ('queued', 'running', 'paused', 'waiting', 'completed', 'failed', 'cancelled')")
    op.execute("CREATE TYPE workflow_execution_trigger_type AS ENUM ('manual', 'scheduled', 'webhook', 'api', 'event')")
    
    # Task types and statuses
    op.execute("CREATE TYPE task_status AS ENUM ('pending', 'queued', 'running', 'completed', 'failed', 'cancelled', 'retrying')")
    op.execute("CREATE TYPE task_priority AS ENUM ('low', 'normal', 'high', 'critical')")
    
    # Agent run statuses
    op.execute("CREATE TYPE agent_run_status AS ENUM ('queued', 'running', 'paused', 'waiting', 'completed', 'failed', 'cancelled')")
    
    # Tool types and statuses
    op.execute("CREATE TYPE tool_type AS ENUM ('builtin', 'custom', 'mcp', 'api', 'community')")
    op.execute("CREATE TYPE tool_status AS ENUM ('active', 'inactive', 'deprecated', 'development')")
    
    # Credential types and statuses
    op.execute("CREATE TYPE credential_type AS ENUM ('api_key', 'oauth_token', 'basic_auth', 'bearer_token', 'certificate', 'ssh_key', 'database_url', 'custom')")
    op.execute("CREATE TYPE credential_status AS ENUM ('active', 'inactive', 'expired', 'revoked')")
    
    # Integration types and statuses
    op.execute("CREATE TYPE integration_provider AS ENUM ('github', 'gitlab', 'bitbucket', 'google', 'microsoft', 'slack', 'discord', 'notion', 'telegram', 'whatsapp', 'hubspot', 'stripe', 'postgres', 'mysql', 'mongodb', 'redis', 'aws', 'gcp', 'azure', 'custom')")
    op.execute("CREATE TYPE integration_status AS ENUM ('active', 'inactive', 'error', 'pending', 'revoked')")
    
    # MCP transport and statuses
    op.execute("CREATE TYPE mcp_transport AS ENUM ('stdio', 'sse', 'http', 'websocket')")
    op.execute("CREATE TYPE mcp_server_status AS ENUM ('active', 'inactive', 'connecting', 'error', 'disconnected')")
    
    # Memory types
    op.execute("CREATE TYPE memory_type AS ENUM ('short_term', 'long_term', 'semantic', 'episodic', 'procedural', 'working')")
    
    # Conversation and message types
    op.execute("CREATE TYPE conversation_status AS ENUM ('active', 'archived', 'deleted')")
    op.execute("CREATE TYPE message_role AS ENUM ('system', 'user', 'assistant', 'tool', 'developer')")
    
    # Approval types and statuses
    op.execute("CREATE TYPE approval_type AS ENUM ('tool_use', 'resource_access', 'data_sharing', 'workflow_execution', 'agent_action', 'custom')")
    op.execute("CREATE TYPE approval_status AS ENUM ('pending', 'approved', 'rejected', 'expired', 'cancelled')")
    
    # Evaluation types and statuses
    op.execute("CREATE TYPE evaluator_type AS ENUM ('human', 'llm', 'rule_based', 'automated', 'composite')")
    op.execute("CREATE TYPE evaluation_status AS ENUM ('pending', 'running', 'completed', 'failed')")
    
    # Webhook statuses
    op.execute("CREATE TYPE webhook_status AS ENUM ('active', 'inactive', 'failed', 'pending')")
    
    # User status
    op.execute("CREATE TYPE user_status AS ENUM ('active', 'inactive', 'suspended', 'pending_verification')")
    
    # Organization status
    op.execute("CREATE TYPE organization_status AS ENUM ('active', 'inactive', 'suspended', 'deleted')")
    
    # Membership role and status
    op.execute("CREATE TYPE membership_role AS ENUM ('owner', 'admin', 'member', 'viewer')")
    op.execute("CREATE TYPE membership_status AS ENUM ('active', 'pending', 'suspended', 'revoked')")

    # Agents table
    op.create_table(
        'agents',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('slug', sa.String(100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('status', postgresql.ENUM('draft', 'active', 'archived', 'deprecated', name='agent_status', create_constraint=True), default='draft', nullable=False),
        sa.Column('agent_type', postgresql.ENUM('chat', 'workflow', 'autonomous', 'assistant', name='agent_type', create_constraint=True), default='chat', nullable=False),
        sa.Column('metadata', postgresql.JSONB(), default={}, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_agents_organization_id', 'agents', ['organization_id'])
    op.create_index('ix_agents_slug', 'agents', ['slug'])
    op.create_index('ix_agents_status', 'agents', ['status'])
    op.create_index('ix_agents_deleted_at', 'agents', ['deleted_at'])
    op.create_unique_constraint('uq_agent_org_slug', 'agents', ['organization_id', 'slug'])

    # Agent Versions table
    op.create_table(
        'agent_versions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('agent_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('agents.id', ondelete='CASCADE'), nullable=False),
        sa.Column('version', sa.String(50), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('instructions', sa.Text(), nullable=True),
        sa.Column('configuration', postgresql.JSONB(), default={}, nullable=False),
        sa.Column('status', sa.String(50), default='draft', nullable=False),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_agent_versions_agent_id', 'agent_versions', ['agent_id'])
    op.create_index('ix_agent_versions_status', 'agent_versions', ['status'])
    op.create_unique_constraint('uq_agent_version', 'agent_versions', ['agent_id', 'version'])

    # Workflows table
    op.create_table(
        'workflows',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('slug', sa.String(100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('status', postgresql.ENUM('draft', 'active', 'archived', 'deprecated', name='workflow_status', create_constraint=True), default='draft', nullable=False),
        sa.Column('metadata', postgresql.JSONB(), default={}, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_workflows_organization_id', 'workflows', ['organization_id'])
    op.create_index('ix_workflows_slug', 'workflows', ['slug'])
    op.create_index('ix_workflows_status', 'workflows', ['status'])
    op.create_index('ix_workflows_deleted_at', 'workflows', ['deleted_at'])
    op.create_unique_constraint('uq_workflow_org_slug', 'workflows', ['organization_id', 'slug'])

    # Workflow Versions table
    op.create_table(
        'workflow_versions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('workflow_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('workflows.id', ondelete='CASCADE'), nullable=False),
        sa.Column('version', sa.String(50), nullable=False),
        sa.Column('definition', postgresql.JSONB(), default={}, nullable=False),
        sa.Column('status', sa.String(50), default='draft', nullable=False),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_workflow_versions_workflow_id', 'workflow_versions', ['workflow_id'])
    op.create_index('ix_workflow_versions_status', 'workflow_versions', ['status'])
    op.create_unique_constraint('uq_workflow_version', 'workflow_versions', ['workflow_id', 'version'])

    # Workflow Executions table
    op.create_table(
        'workflow_executions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('workflow_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('workflows.id', ondelete='CASCADE'), nullable=False),
        sa.Column('workflow_version_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('workflow_versions.id', ondelete='SET NULL'), nullable=True),
        sa.Column('status', postgresql.ENUM('queued', 'running', 'paused', 'waiting', 'completed', 'failed', 'cancelled', name='workflow_execution_status', create_constraint=True), default='queued', nullable=False),
        sa.Column('trigger_type', postgresql.ENUM('manual', 'scheduled', 'webhook', 'api', 'event', name='workflow_execution_trigger_type', create_constraint=True), default='manual', nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('error_code', sa.String(100), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('metadata', postgresql.JSONB(), default={}, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_workflow_executions_organization_id', 'workflow_executions', ['organization_id'])
    op.create_index('ix_workflow_executions_workflow_id', 'workflow_executions', ['workflow_id'])
    op.create_index('ix_workflow_executions_workflow_version_id', 'workflow_executions', ['workflow_version_id'])
    op.create_index('ix_workflow_executions_status', 'workflow_executions', ['status'])
    op.create_index('ix_workflow_executions_started_at', 'workflow_executions', ['started_at'])
    op.create_index('ix_workflow_executions_organization_status', 'workflow_executions', ['organization_id', 'status'])
    op.create_index('ix_workflow_executions_organization_created', 'workflow_executions', ['organization_id', 'created_at'])

    # Tasks table
    op.create_table(
        'tasks',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('type', sa.String(100), nullable=False),
        sa.Column('status', postgresql.ENUM('pending', 'queued', 'running', 'completed', 'failed', 'cancelled', 'retrying', name='task_status', create_constraint=True), default='pending', nullable=False),
        sa.Column('priority', sa.Integer(), default=5, nullable=False),
        sa.Column('payload', postgresql.JSONB(), default={}, nullable=False),
        sa.Column('result', postgresql.JSONB(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('attempts', sa.Integer(), default=0, nullable=False),
        sa.Column('max_attempts', sa.Integer(), default=3, nullable=False),
        sa.Column('available_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_tasks_organization_id', 'tasks', ['organization_id'])
    op.create_index('ix_tasks_status', 'tasks', ['status'])
    op.create_index('ix_tasks_type', 'tasks', ['type'])
    op.create_index('ix_tasks_available_at', 'tasks', ['available_at'])
    op.create_index('ix_tasks_organization_status', 'tasks', ['organization_id', 'status'])
    op.create_index('ix_tasks_organization_type_status', 'tasks', ['organization_id', 'type', 'status'])

    # Agent Runs table
    op.create_table(
        'agent_runs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('agent_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('agents.id', ondelete='CASCADE'), nullable=False),
        sa.Column('agent_version_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('agent_versions.id', ondelete='SET NULL'), nullable=True),
        sa.Column('workflow_execution_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('workflow_executions.id', ondelete='SET NULL'), nullable=True),
        sa.Column('status', postgresql.ENUM('queued', 'running', 'paused', 'waiting', 'completed', 'failed', 'cancelled', name='agent_run_status', create_constraint=True), default='queued', nullable=False),
        sa.Column('input', postgresql.JSONB(), default={}, nullable=False),
        sa.Column('output', postgresql.JSONB(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('metadata', postgresql.JSONB(), default={}, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_agent_runs_organization_id', 'agent_runs', ['organization_id'])
    op.create_index('ix_agent_runs_agent_id', 'agent_runs', ['agent_id'])
    op.create_index('ix_agent_runs_agent_version_id', 'agent_runs', ['agent_version_id'])
    op.create_index('ix_agent_runs_workflow_execution_id', 'agent_runs', ['workflow_execution_id'])
    op.create_index('ix_agent_runs_status', 'agent_runs', ['status'])
    op.create_index('ix_agent_runs_started_at', 'agent_runs', ['started_at'])
    op.create_index('ix_agent_runs_organization_status', 'agent_runs', ['organization_id', 'status'])
    op.create_index('ix_agent_runs_organization_created', 'agent_runs', ['organization_id', 'created_at'])

    # Execution Events table
    op.create_table(
        'execution_events',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('run_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('agent_runs.id', ondelete='CASCADE'), nullable=True),
        sa.Column('workflow_execution_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('workflow_executions.id', ondelete='CASCADE'), nullable=True),
        sa.Column('event_type', sa.String(100), nullable=False),
        sa.Column('sequence', sa.Integer(), nullable=False),
        sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False),
        sa.Column('payload', postgresql.JSONB(), default={}, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_execution_events_organization_id', 'execution_events', ['organization_id'])
    op.create_index('ix_execution_events_run_id', 'execution_events', ['run_id'])
    op.create_index('ix_execution_events_workflow_execution_id', 'execution_events', ['workflow_execution_id'])
    op.create_index('ix_execution_events_event_type', 'execution_events', ['event_type'])
    op.create_index('ix_execution_events_timestamp', 'execution_events', ['timestamp'])
    op.create_index('ix_execution_events_run_sequence', 'execution_events', ['run_id', 'sequence'])
    op.create_index('ix_execution_events_workflow_sequence', 'execution_events', ['workflow_execution_id', 'sequence'])
    op.create_index('ix_execution_events_organization_created', 'execution_events', ['organization_id', 'created_at'])

    # Tools table
    op.create_table(
        'tools',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('slug', sa.String(100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('tool_type', postgresql.ENUM('builtin', 'custom', 'mcp', 'api', 'community', name='tool_type', create_constraint=True), default='custom', nullable=False),
        sa.Column('status', postgresql.ENUM('active', 'inactive', 'deprecated', 'development', name='tool_status', create_constraint=True), default='development', nullable=False),
        sa.Column('configuration', postgresql.JSONB(), default={}, nullable=False),
        sa.Column('metadata', postgresql.JSONB(), default={}, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_tools_organization_id', 'tools', ['organization_id'])
    op.create_index('ix_tools_slug', 'tools', ['slug'])
    op.create_index('ix_tools_tool_type', 'tools', ['tool_type'])
    op.create_index('ix_tools_status', 'tools', ['status'])
    op.create_index('ix_tools_deleted_at', 'tools', ['deleted_at'])
    op.create_unique_constraint('uq_tool_org_slug', 'tools', ['organization_id', 'slug'])

    # Credentials table
    op.create_table(
        'credentials',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('provider', sa.String(100), nullable=False),
        sa.Column('credential_type', postgresql.ENUM('api_key', 'oauth_token', 'basic_auth', 'bearer_token', 'certificate', 'ssh_key', 'database_url', 'custom', name='credential_type', create_constraint=True), default='api_key', nullable=False),
        sa.Column('encrypted_data', sa.Text(), nullable=False),
        sa.Column('metadata', postgresql.JSONB(), default={}, nullable=False),
        sa.Column('status', postgresql.ENUM('active', 'inactive', 'expired', 'revoked', name='credential_status', create_constraint=True), default='active', nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_credentials_organization_id', 'credentials', ['organization_id'])
    op.create_index('ix_credentials_provider', 'credentials', ['provider'])
    op.create_index('ix_credentials_credential_type', 'credentials', ['credential_type'])
    op.create_index('ix_credentials_status', 'credentials', ['status'])
    op.create_index('ix_credentials_expires_at', 'credentials', ['expires_at'])
    op.create_index('ix_credentials_deleted_at', 'credentials', ['deleted_at'])

    # Integrations table
    op.create_table(
        'integrations',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('provider', postgresql.ENUM('github', 'gitlab', 'bitbucket', 'google', 'microsoft', 'slack', 'discord', 'notion', 'telegram', 'whatsapp', 'hubspot', 'stripe', 'postgres', 'mysql', 'mongodb', 'redis', 'aws', 'gcp', 'azure', 'custom', name='integration_provider', create_constraint=True), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('status', postgresql.ENUM('active', 'inactive', 'error', 'pending', 'revoked', name='integration_status', create_constraint=True), default='pending', nullable=False),
        sa.Column('configuration', postgresql.JSONB(), default={}, nullable=False),
        sa.Column('credential_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('credentials.id', ondelete='SET NULL'), nullable=True),
        sa.Column('metadata', postgresql.JSONB(), default={}, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_integrations_organization_id', 'integrations', ['organization_id'])
    op.create_index('ix_integrations_provider', 'integrations', ['provider'])
    op.create_index('ix_integrations_credential_id', 'integrations', ['credential_id'])
    op.create_index('ix_integrations_status', 'integrations', ['status'])
    op.create_index('ix_integrations_deleted_at', 'integrations', ['deleted_at'])

    # MCP Servers table
    op.create_table(
        'mcp_servers',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('server_url', sa.String(500), nullable=False),
        sa.Column('transport', postgresql.ENUM('stdio', 'sse', 'http', 'websocket', name='mcp_transport', create_constraint=True), default='stdio', nullable=False),
        sa.Column('status', postgresql.ENUM('active', 'inactive', 'connecting', 'error', 'disconnected', name='mcp_server_status', create_constraint=True), default='disconnected', nullable=False),
        sa.Column('configuration', postgresql.JSONB(), default={}, nullable=False),
        sa.Column('credential_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('credentials.id', ondelete='SET NULL'), nullable=True),
        sa.Column('metadata', postgresql.JSONB(), default={}, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_mcp_servers_organization_id', 'mcp_servers', ['organization_id'])
    op.create_index('ix_mcp_servers_transport', 'mcp_servers', ['transport'])
    op.create_index('ix_mcp_servers_status', 'mcp_servers', ['status'])
    op.create_index('ix_mcp_servers_credential_id', 'mcp_servers', ['credential_id'])
    op.create_index('ix_mcp_servers_deleted_at', 'mcp_servers', ['deleted_at'])

    # Memories table
    op.create_table(
        'memories',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('agent_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('agents.id', ondelete='SET NULL'), nullable=True),
        sa.Column('memory_type', postgresql.ENUM('short_term', 'long_term', 'semantic', 'episodic', 'procedural', 'working', name='memory_type', create_constraint=True), default='short_term', nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('metadata', postgresql.JSONB(), default={}, nullable=False),
        sa.Column('embedding', postgresql.ARRAY(sa.Float()), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_memories_organization_id', 'memories', ['organization_id'])
    op.create_index('ix_memories_user_id', 'memories', ['user_id'])
    op.create_index('ix_memories_agent_id', 'memories', ['agent_id'])
    op.create_index('ix_memories_memory_type', 'memories', ['memory_type'])
    op.create_index('ix_memories_expires_at', 'memories', ['expires_at'])
    op.create_index('ix_memories_organization_created', 'memories', ['organization_id', 'created_at'])

    # Conversations table
    op.create_table(
        'conversations',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('agent_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('agents.id', ondelete='SET NULL'), nullable=True),
        sa.Column('title', sa.String(500), nullable=True),
        sa.Column('status', postgresql.ENUM('active', 'archived', 'deleted', name='conversation_status', create_constraint=True), default='active', nullable=False),
        sa.Column('metadata', postgresql.JSONB(), default={}, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_conversations_organization_id', 'conversations', ['organization_id'])
    op.create_index('ix_conversations_user_id', 'conversations', ['user_id'])
    op.create_index('ix_conversations_agent_id', 'conversations', ['agent_id'])
    op.create_index('ix_conversations_status', 'conversations', ['status'])
    op.create_index('ix_conversations_deleted_at', 'conversations', ['deleted_at'])
    op.create_index('ix_conversations_organization_user', 'conversations', ['organization_id', 'user_id'])
    op.create_index('ix_conversations_organization_created', 'conversations', ['organization_id', 'created_at'])

    # Messages table
    op.create_table(
        'messages',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('conversation_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('conversations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('role', postgresql.ENUM('system', 'user', 'assistant', 'tool', 'developer', name='message_role', create_constraint=True), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('metadata', postgresql.JSONB(), default={}, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_messages_conversation_id', 'messages', ['conversation_id'])
    op.create_index('ix_messages_role', 'messages', ['role'])
    op.create_index('ix_messages_created_at', 'messages', ['created_at'])
    op.create_index('ix_messages_conversation_created', 'messages', ['conversation_id', 'created_at'])

    # Approvals table
    op.create_table(
        'approvals',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('run_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('agent_runs.id', ondelete='SET NULL'), nullable=True),
        sa.Column('workflow_execution_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('workflow_executions.id', ondelete='SET NULL'), nullable=True),
        sa.Column('approval_type', postgresql.ENUM('tool_use', 'resource_access', 'data_sharing', 'workflow_execution', 'agent_action', 'custom', name='approval_type', create_constraint=True), default='custom', nullable=False),
        sa.Column('status', postgresql.ENUM('pending', 'approved', 'rejected', 'expired', 'cancelled', name='approval_status', create_constraint=True), default='pending', nullable=False),
        sa.Column('requested_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('approved_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('payload', postgresql.JSONB(), default={}, nullable=False),
        sa.Column('decision', postgresql.JSONB(), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_approvals_organization_id', 'approvals', ['organization_id'])
    op.create_index('ix_approvals_run_id', 'approvals', ['run_id'])
    op.create_index('ix_approvals_workflow_execution_id', 'approvals', ['workflow_execution_id'])
    op.create_index('ix_approvals_status', 'approvals', ['status'])
    op.create_index('ix_approvals_requested_by', 'approvals', ['requested_by'])
    op.create_index('ix_approvals_approved_by', 'approvals', ['approved_by'])
    op.create_index('ix_approvals_expires_at', 'approvals', ['expires_at'])
    op.create_index('ix_approvals_organization_status', 'approvals', ['organization_id', 'status'])

    # Evaluations table
    op.create_table(
        'evaluations',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('run_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('agent_runs.id', ondelete='SET NULL'), nullable=True),
        sa.Column('workflow_execution_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('workflow_executions.id', ondelete='SET NULL'), nullable=True),
        sa.Column('evaluator_type', postgresql.ENUM('human', 'llm', 'rule_based', 'automated', 'composite', name='evaluator_type', create_constraint=True), default='automated', nullable=False),
        sa.Column('status', postgresql.ENUM('pending', 'running', 'completed', 'failed', name='evaluation_status', create_constraint=True), default='pending', nullable=False),
        sa.Column('score', sa.Float(), nullable=True),
        sa.Column('criteria', postgresql.JSONB(), default={}, nullable=False),
        sa.Column('result', postgresql.JSONB(), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_evaluations_organization_id', 'evaluations', ['organization_id'])
    op.create_index('ix_evaluations_run_id', 'evaluations', ['run_id'])
    op.create_index('ix_evaluations_workflow_execution_id', 'evaluations', ['workflow_execution_id'])
    op.create_index('ix_evaluations_evaluator_type', 'evaluations', ['evaluator_type'])
    op.create_index('ix_evaluations_status', 'evaluations', ['status'])
    op.create_index('ix_evaluations_organization_created', 'evaluations', ['organization_id', 'created_at'])

    # Audit Logs table
    op.create_table(
        'audit_logs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('actor_user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('action', sa.String(100), nullable=False),
        sa.Column('resource_type', sa.String(100), nullable=False),
        sa.Column('resource_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('ip_address', sa.String(45), nullable=True),
        sa.Column('user_agent', sa.Text(), nullable=True),
        sa.Column('metadata', postgresql.JSONB(), default={}, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_audit_logs_organization_id', 'audit_logs', ['organization_id'])
    op.create_index('ix_audit_logs_actor_user_id', 'audit_logs', ['actor_user_id'])
    op.create_index('ix_audit_logs_action', 'audit_logs', ['action'])
    op.create_index('ix_audit_logs_resource_type', 'audit_logs', ['resource_type'])
    op.create_index('ix_audit_logs_resource_id', 'audit_logs', ['resource_id'])
    op.create_index('ix_audit_logs_created_at', 'audit_logs', ['created_at'])
    op.create_index('ix_audit_logs_organization_action', 'audit_logs', ['organization_id', 'action'])
    op.create_index('ix_audit_logs_organization_created', 'audit_logs', ['organization_id', 'created_at'])
    op.create_index('ix_audit_logs_resource', 'audit_logs', ['resource_type', 'resource_id'])

    # Webhooks table
    op.create_table(
        'webhooks',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('url', sa.String(500), nullable=False),
        sa.Column('event_types', postgresql.JSONB(), default=[], nullable=False),
        sa.Column('secret_hash', sa.String(255), nullable=False),
        sa.Column('status', postgresql.ENUM('active', 'inactive', 'failed', 'pending', name='webhook_status', create_constraint=True), default='pending', nullable=False),
        sa.Column('metadata', postgresql.JSONB(), default={}, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_webhooks_organization_id', 'webhooks', ['organization_id'])
    op.create_index('ix_webhooks_status', 'webhooks', ['status'])
    op.create_index('ix_webhooks_deleted_at', 'webhooks', ['deleted_at'])


def downgrade() -> None:
    op.drop_table('webhooks')
    op.drop_table('audit_logs')
    op.drop_table('evaluations')
    op.drop_table('approvals')
    op.drop_table('messages')
    op.drop_table('conversations')
    op.drop_table('memories')
    op.drop_table('mcp_servers')
    op.drop_table('integrations')
    op.drop_table('credentials')
    op.drop_table('tools')
    op.drop_table('execution_events')
    op.drop_table('agent_runs')
    op.drop_table('tasks')
    op.drop_table('workflow_executions')
    op.drop_table('workflow_versions')
    op.drop_table('workflows')
    op.drop_table('agent_versions')
    op.drop_table('agents')

    op.execute("DROP TYPE IF EXISTS webhook_status")
    op.execute("DROP TYPE IF EXISTS evaluation_status")
    op.execute("DROP TYPE IF EXISTS evaluator_type")
    op.execute("DROP TYPE IF EXISTS approval_status")
    op.execute("DROP TYPE IF EXISTS approval_type")
    op.execute("DROP TYPE IF EXISTS message_role")
    op.execute("DROP TYPE IF EXISTS conversation_status")
    op.execute("DROP TYPE IF EXISTS memory_type")
    op.execute("DROP TYPE IF EXISTS mcp_server_status")
    op.execute("DROP TYPE IF EXISTS mcp_transport")
    op.execute("DROP TYPE IF EXISTS integration_status")
    op.execute("DROP TYPE IF EXISTS integration_provider")
    op.execute("DROP TYPE IF EXISTS credential_status")
    op.execute("DROP TYPE IF EXISTS credential_type")
    op.execute("DROP TYPE IF EXISTS tool_status")
    op.execute("DROP TYPE IF EXISTS tool_type")
    op.execute("DROP TYPE IF EXISTS agent_run_status")
    op.execute("DROP TYPE IF EXISTS task_priority")
    op.execute("DROP TYPE IF EXISTS task_status")
    op.execute("DROP TYPE IF EXISTS workflow_execution_trigger_type")
    op.execute("DROP TYPE IF EXISTS workflow_execution_status")
    op.execute("DROP TYPE IF EXISTS workflow_status")
    op.execute("DROP TYPE IF EXISTS agent_status")
    op.execute("DROP TYPE IF EXISTS agent_type")
    op.execute("DROP TYPE IF EXISTS membership_status")
    op.execute("DROP TYPE IF EXISTS membership_role")
    op.execute("DROP TYPE IF EXISTS organization_status")
    op.execute("DROP TYPE IF EXISTS user_status")