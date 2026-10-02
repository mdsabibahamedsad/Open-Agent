"""Add multi-agent orchestration tables

Revision ID: 012_add_orchestration
Revises: 011_add_mcp_integration
Create Date: 2026-09-27 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '012_add_orchestration'
down_revision = '011_add_mcp_integration'
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_status = sa.Enum(
        'created', 'planning', 'ready', 'running', 'waiting', 'paused',
        'succeeded', 'partially_succeeded', 'failed', 'cancelled', 'timed_out',
        name='orchestration_run_status',
    )
    run_status.create(op.get_bind(), checkfirst=True)
    task_status = sa.Enum(
        'created', 'ready', 'assigned', 'running', 'waiting', 'paused',
        'succeeded', 'failed', 'skipped', 'cancelled', 'timed_out',
        name='orchestration_task_status',
    )
    task_status.create(op.get_bind(), checkfirst=True)
    rel_type = sa.Enum(
        'manages', 'reports_to', 'collaborates_with', 'can_delegate_to',
        'can_review', 'specializes_in',
        name='agent_relationship_type',
    )
    rel_type.create(op.get_bind(), checkfirst=True)

    op.create_table(
        'orchestration_runs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('objective', sa.Text, nullable=False),
        sa.Column('status', run_status, nullable=False, server_default='created', index=True),
        sa.Column('root_agent_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('agents.id', ondelete='SET NULL'), nullable=True, index=True),
        sa.Column('team_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('teams.id', ondelete='SET NULL'), nullable=True, index=True),
        sa.Column('created_by', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('budget', postgresql.JSONB, nullable=False, server_default='{}'),
        sa.Column('usage', postgresql.JSONB, nullable=False, server_default='{}'),
        sa.Column('final_result', postgresql.JSONB, nullable=True),
        sa.Column('error', sa.Text, nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('idempotency_key', sa.String(255), nullable=True, index=True),
        sa.Column('metadata', postgresql.JSONB, nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_orch_runs_org_status', 'orchestration_runs', ['organization_id', 'status'])
    op.create_index('ix_orch_runs_org_created', 'orchestration_runs', ['organization_id', 'created_at'])

    op.create_table(
        'orchestration_tasks',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('orchestration_run_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('orchestration_runs.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('parent_task_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('orchestration_tasks.id', ondelete='SET NULL'), nullable=True, index=True),
        sa.Column('assigned_agent_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('agents.id', ondelete='SET NULL'), nullable=True, index=True),
        sa.Column('agent_run_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('agent_runs.id', ondelete='SET NULL'), nullable=True, index=True),
        sa.Column('external_task_id', sa.String(128), nullable=False),
        sa.Column('title', sa.String(500), nullable=False),
        sa.Column('description', sa.Text, nullable=False, server_default=''),
        sa.Column('instructions', sa.Text, nullable=False, server_default=''),
        sa.Column('status', task_status, nullable=False, server_default='created', index=True),
        sa.Column('priority', sa.String(20), nullable=False, server_default='normal'),
        sa.Column('dependency_policy', sa.String(20), nullable=False, server_default='all_success'),
        sa.Column('required_capabilities', postgresql.JSONB, nullable=False, server_default='[]'),
        sa.Column('required_permissions', postgresql.JSONB, nullable=False, server_default='[]'),
        sa.Column('risk_level', sa.String(20), nullable=False, server_default='low'),
        sa.Column('requires_approval', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('input', postgresql.JSONB, nullable=False, server_default='{}'),
        sa.Column('output', postgresql.JSONB, nullable=True),
        sa.Column('error', sa.Text, nullable=True),
        sa.Column('retry_count', sa.Integer, nullable=False, server_default='0'),
        sa.Column('max_retries', sa.Integer, nullable=False, server_default='1'),
        sa.Column('retry_strategy', sa.String(30), nullable=False, server_default='fixed'),
        sa.Column('timeout_seconds', sa.Integer, nullable=False, server_default='600'),
        sa.Column('depth', sa.Integer, nullable=False, server_default='1'),
        sa.Column('aggregation_strategy', sa.String(30), nullable=True),
        sa.Column('lease_owner', sa.String(128), nullable=True, index=True),
        sa.Column('lease_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_heartbeat_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('metadata', postgresql.JSONB, nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_orch_tasks_run_status', 'orchestration_tasks', ['orchestration_run_id', 'status'])
    op.create_index('ix_orch_tasks_run_external', 'orchestration_tasks',
                    ['orchestration_run_id', 'external_task_id'], unique=True)
    op.create_index('ix_orch_tasks_org_created', 'orchestration_tasks', ['organization_id', 'created_at'])

    op.create_table(
        'orchestration_task_dependencies',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('orchestration_run_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('orchestration_runs.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('task_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('orchestration_tasks.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('depends_on_task_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('orchestration_tasks.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_orch_task_deps_unique', 'orchestration_task_dependencies',
                    ['task_id', 'depends_on_task_id'], unique=True)
    op.create_index('ix_orch_task_deps_run', 'orchestration_task_dependencies',
                    ['orchestration_run_id', 'task_id'])

    op.create_table(
        'agent_relationships',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('source_agent_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('agents.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('target_agent_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('agents.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('relationship_type', rel_type, nullable=False),
        sa.Column('role', sa.String(64), nullable=False, server_default='worker'),
        sa.Column('metadata', postgresql.JSONB, nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_agent_rel_unique', 'agent_relationships',
                    ['organization_id', 'source_agent_id', 'target_agent_id', 'relationship_type'],
                    unique=True)
    op.create_index('ix_agent_rel_source', 'agent_relationships', ['source_agent_id', 'relationship_type'])

    op.create_table(
        'agent_capabilities',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=True, index=True),
        sa.Column('agent_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('agents.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('name', sa.String(128), nullable=False, index=True),
        sa.Column('description', sa.Text, nullable=False, server_default=''),
        sa.Column('version', sa.String(32), nullable=False, server_default='1.0'),
        sa.Column('required_tools', postgresql.JSONB, nullable=False, server_default='[]'),
        sa.Column('required_permissions', postgresql.JSONB, nullable=False, server_default='[]'),
        sa.Column('risk_level', sa.String(20), nullable=False, server_default='low'),
        sa.Column('available', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_agent_cap_unique', 'agent_capabilities', ['agent_id', 'name'], unique=True)

    op.create_table(
        'agent_messages',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('orchestration_run_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('orchestration_runs.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('sender_agent_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('agents.id', ondelete='SET NULL'), nullable=True, index=True),
        sa.Column('recipient_agent_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('agents.id', ondelete='SET NULL'), nullable=True, index=True),
        sa.Column('task_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('orchestration_tasks.id', ondelete='SET NULL'), nullable=True, index=True),
        sa.Column('message_type', sa.String(64), nullable=False, index=True),
        sa.Column('payload', postgresql.JSONB, nullable=False, server_default='{}'),
        sa.Column('correlation_id', sa.String(128), nullable=True, index=True),
        sa.Column('reply_to', sa.String(128), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_agent_msg_run_created', 'agent_messages', ['orchestration_run_id', 'created_at'])

    op.create_table(
        'agent_handoffs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('orchestration_run_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('orchestration_runs.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('task_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('orchestration_tasks.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('from_agent_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('agents.id', ondelete='SET NULL'), nullable=True),
        sa.Column('to_agent_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('agents.id', ondelete='SET NULL'), nullable=True),
        sa.Column('package', postgresql.JSONB, nullable=False, server_default='{}'),
        sa.Column('status', sa.String(30), nullable=False, server_default='completed'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        'orchestration_task_attempts',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('orchestration_run_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('orchestration_runs.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('task_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('orchestration_tasks.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('agent_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('agents.id', ondelete='SET NULL'), nullable=True),
        sa.Column('agent_run_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('agent_runs.id', ondelete='SET NULL'), nullable=True),
        sa.Column('attempt_number', sa.Integer, nullable=False),
        sa.Column('status', sa.String(30), nullable=False),
        sa.Column('output', postgresql.JSONB, nullable=True),
        sa.Column('error', sa.Text, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_orch_attempts_task', 'orchestration_task_attempts',
                    ['task_id', 'attempt_number'], unique=True)

    op.create_table(
        'orchestration_budget_ledgers',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('orchestration_run_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('orchestration_runs.id', ondelete='CASCADE'), nullable=False,
                  unique=True, index=True),
        sa.Column('limits', postgresql.JSONB, nullable=False, server_default='{}'),
        sa.Column('consumed_tokens', sa.Integer, nullable=False, server_default='0'),
        sa.Column('consumed_cost', sa.Numeric(14, 6), nullable=False, server_default='0'),
        sa.Column('consumed_tool_calls', sa.Integer, nullable=False, server_default='0'),
        sa.Column('consumed_steps', sa.Integer, nullable=False, server_default='0'),
        sa.Column('consumed_tasks', sa.Integer, nullable=False, server_default='0'),
        sa.Column('consumed_agents', sa.Integer, nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        'orchestration_events',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('orchestration_run_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('orchestration_runs.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('task_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('orchestration_tasks.id', ondelete='SET NULL'), nullable=True, index=True),
        sa.Column('agent_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('agents.id', ondelete='SET NULL'), nullable=True),
        sa.Column('event_type', sa.String(64), nullable=False, index=True),
        sa.Column('payload', postgresql.JSONB, nullable=False, server_default='{}'),
        sa.Column('trace_id', sa.String(64), nullable=True, index=True),
        sa.Column('span_id', sa.String(64), nullable=True),
        sa.Column('parent_span_id', sa.String(64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_orch_events_run_created', 'orchestration_events',
                    ['orchestration_run_id', 'created_at'])
    op.create_index('ix_orch_events_run_type', 'orchestration_events',
                    ['orchestration_run_id', 'event_type'])

    op.create_table(
        'agent_conflicts',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('orchestration_run_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('orchestration_runs.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('task_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('orchestration_tasks.id', ondelete='SET NULL'), nullable=True, index=True),
        sa.Column('sources', postgresql.JSONB, nullable=False, server_default='[]'),
        sa.Column('claims', postgresql.JSONB, nullable=False, server_default='[]'),
        sa.Column('evidence', postgresql.JSONB, nullable=False, server_default='[]'),
        sa.Column('confidence', postgresql.JSONB, nullable=False, server_default='{}'),
        sa.Column('resolution_status', sa.String(30), nullable=False, server_default='open'),
        sa.Column('resolution', postgresql.JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    for table in (
        'agent_conflicts', 'orchestration_events', 'orchestration_budget_ledgers',
        'orchestration_task_attempts', 'agent_handoffs', 'agent_messages',
        'agent_capabilities', 'agent_relationships', 'orchestration_task_dependencies',
        'orchestration_tasks', 'orchestration_runs',
    ):
        op.drop_table(table)
    sa.Enum(name='agent_relationship_type').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='orchestration_task_status').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='orchestration_run_status').drop(op.get_bind(), checkfirst=True)
