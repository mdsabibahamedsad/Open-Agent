"""Add MP19 approval satellite tables + extended approval states.

Revision ID: 018_add_approvals
Revises: 017_add_sandbox
Create Date: 2026-09-29 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '018_add_approvals'
down_revision = '017_add_sandbox'
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
    # Extend approval_status enum with execution lifecycle values (additive).
    for value in ('executing', 'executed', 'execution_failed', 'invalidated'):
        op.execute(f"ALTER TYPE approval_status ADD VALUE IF NOT EXISTS '{value}'")

    # Threat telemetry for the approval layer (additive).
    for value in ('approval.self_approval_attempt', 'approval.replay_attempt',
                  'approval.expired_execution_attempt', 'approval.modified_payload',
                  'approval.cross_tenant_attempt', 'approval.policy_bypass_attempt',
                  'approval.privilege_escalation_attempt'):
        op.execute(f"ALTER TYPE security_event_type ADD VALUE IF NOT EXISTS '{value}'")

    op.create_table(
        'approval_steps', _uuid_pk(),
        sa.Column('approval_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('approvals.id', ondelete='CASCADE'), nullable=False),
        _org_fk(),
        sa.Column('step_index', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('required_role', sa.String(100), nullable=True),
        sa.Column('status', sa.String(30), nullable=False, server_default='pending'),
        sa.Column('decided_by', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
        *_ts(),
    )
    op.create_index('ix_approval_steps_approval', 'approval_steps', ['approval_id'])
    op.create_index('ix_approval_steps_org_status', 'approval_steps',
                    ['organization_id', 'status'])

    op.create_table(
        'approval_decisions', _uuid_pk(),
        sa.Column('approval_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('approvals.id', ondelete='CASCADE'), nullable=False),
        _org_fk(),
        sa.Column('actor_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('decision', sa.String(30), nullable=False),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('idempotency_key', sa.String(100), nullable=True),
        *_ts(),
    )
    op.create_index('ix_approval_decisions_approval', 'approval_decisions', ['approval_id'])
    op.create_index('ix_approval_decisions_actor', 'approval_decisions', ['actor_id'])

    op.create_table(
        'approval_policies', _uuid_pk(), _org_fk(),
        sa.Column('team_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('agent_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('level', sa.String(30), nullable=False, server_default='organization'),
        sa.Column('rules', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        *_ts(),
    )
    op.create_index('ix_approval_policies_org_active', 'approval_policies',
                    ['organization_id', 'is_active'])
    op.create_index('ix_approval_policies_team', 'approval_policies', ['team_id'])
    op.create_index('ix_approval_policies_agent', 'approval_policies', ['agent_id'])

    op.create_table(
        'approval_policy_versions', _uuid_pk(),
        sa.Column('policy_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('approval_policies.id', ondelete='CASCADE'), nullable=False),
        _org_fk(),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('rules', sa.JSON(), nullable=False, server_default='[]'),
        *_ts(),
    )
    op.create_index('ix_approval_policy_versions_policy', 'approval_policy_versions',
                    ['policy_id'])

    op.create_table(
        'approval_escalations', _uuid_pk(),
        sa.Column('approval_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('approvals.id', ondelete='CASCADE'), nullable=False),
        _org_fk(),
        sa.Column('escalated_by', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('escalate_to', sa.String(100), nullable=False),
        sa.Column('reason', sa.Text(), nullable=True),
        *_ts(),
    )
    op.create_index('ix_approval_escalations_approval', 'approval_escalations',
                    ['approval_id'])

    op.create_table(
        'approval_action_snapshots', _uuid_pk(),
        sa.Column('approval_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('approvals.id', ondelete='CASCADE'), nullable=False),
        _org_fk(),
        sa.Column('action_hash', sa.String(64), nullable=False),
        sa.Column('snapshot', sa.JSON(), nullable=False, server_default='{}'),
        *_ts(),
    )
    op.create_index('ix_approval_snapshots_hash', 'approval_action_snapshots',
                    ['action_hash'])

    op.create_table(
        'approval_events', _uuid_pk(),
        sa.Column('approval_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('approvals.id', ondelete='CASCADE'), nullable=False),
        _org_fk(),
        sa.Column('event_type', sa.String(100), nullable=False),
        sa.Column('actor_type', sa.String(50), nullable=True),
        sa.Column('actor_id', sa.String(100), nullable=True),
        sa.Column('event_data', sa.JSON(), nullable=False, server_default='{}'),
        *_ts(),
    )
    op.create_index('ix_approval_events_approval', 'approval_events', ['approval_id'])
    op.create_index('ix_approval_events_org_created', 'approval_events',
                    ['organization_id', 'created_at'])

    op.create_table(
        'approval_delegations', _uuid_pk(), _org_fk(),
        sa.Column('delegator_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('delegate_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('scope', sa.String(200), nullable=False),
        sa.Column('starts_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        *_ts(),
    )
    op.create_index('ix_approval_delegations_org', 'approval_delegations',
                    ['organization_id'])
    op.create_index('ix_approval_delegations_delegate', 'approval_delegations',
                    ['delegate_id'])


def downgrade() -> None:
    for table in ('approval_delegations', 'approval_events', 'approval_action_snapshots',
                  'approval_escalations', 'approval_policy_versions', 'approval_policies',
                  'approval_decisions', 'approval_steps'):
        op.drop_table(table)
    # Enum values are left in place (Postgres cannot drop enum values safely).
