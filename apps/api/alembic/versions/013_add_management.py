"""Add management-layer tables (MP14)

Revision ID: 013_add_management
Revises: 012_add_orchestration
Create Date: 2026-09-27 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '013_add_management'
down_revision = '012_add_orchestration'
branch_labels = None
depends_on = None


def _org_fk(nullable=False):
    return sa.Column(
        'organization_id', postgresql.UUID(as_uuid=True),
        sa.ForeignKey('organizations.id', ondelete='CASCADE'),
        nullable=nullable, index=True,
    )


def _agent_fk(name, nullable=True):
    return sa.Column(
        name, postgresql.UUID(as_uuid=True),
        sa.ForeignKey('agents.id', ondelete='SET NULL'),
        nullable=nullable, index=True,
    )


def _ts():
    return [
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    for name, values in [
        ('manager_profile_status', ['active', 'suspended', 'archived']),
        ('delegation_request_status', ['pending', 'accepted', 'rejected', 'expired', 'cancelled', 'completed']),
        ('handoff_package_status', ['preparing', 'pending_acceptance', 'accepted', 'executing', 'completed', 'rejected', 'expired', 'cancelled']),
        ('review_result_status', ['approved', 'revision_required', 'rejected', 'escalate']),
        ('escalation_status', ['open', 'acknowledged', 'in_progress', 'resolved', 'escalated', 'closed']),
        ('dynamic_team_status', ['created', 'forming', 'active', 'winding_down', 'completed', 'cancelled']),
    ]:
        sa.Enum(*values, name=name).create(op.get_bind(), checkfirst=True)

    op.create_table(
        'agent_departments',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        _org_fk(), sa.Column('name', sa.String(128), nullable=False),
        sa.Column('slug', sa.String(128), nullable=False),
        sa.Column('description', sa.Text, nullable=False, server_default=''),
        *_ts(),
    )
    op.create_index('ix_agent_departments_org_slug', 'agent_departments',
                    ['organization_id', 'slug'], unique=True)

    op.create_table(
        'dynamic_teams',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        _org_fk(),
        sa.Column('orchestration_run_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('orchestration_runs.id', ondelete='CASCADE'), nullable=True, index=True),
        sa.Column('task_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('orchestration_tasks.id', ondelete='SET NULL'), nullable=True, index=True),
        _agent_fk('manager_agent_id'),
        sa.Column('department_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('agent_departments.id', ondelete='SET NULL'), nullable=True, index=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('team_type', sa.String(30), nullable=False, server_default='temporary'),
        sa.Column('status', sa.Enum('created', 'forming', 'active', 'winding_down', 'completed', 'cancelled',
                                    name='dynamic_team_status'),
                  nullable=False, server_default='created', index=True),
        sa.Column('budget', postgresql.JSONB, nullable=False, server_default='{}'),
        sa.Column('idempotency_key', sa.String(255), nullable=True, index=True),
        *_ts(),
    )
    op.create_index('ix_dynamic_teams_org_status', 'dynamic_teams', ['organization_id', 'status'])

    op.create_table(
        'manager_profiles',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        _org_fk(),
        sa.Column('agent_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('agents.id', ondelete='CASCADE'), nullable=False, unique=True, index=True),
        sa.Column('label', sa.String(64), nullable=False, server_default='manager'),
        sa.Column('status', sa.Enum('active', 'suspended', 'archived', name='manager_profile_status'),
                  nullable=False, server_default='active'),
        sa.Column('managed_capabilities', postgresql.JSONB, nullable=False, server_default='[]'),
        sa.Column('delegation_policy', sa.String(30), nullable=False, server_default='hybrid'),
        sa.Column('review_required', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('escalation_policy', sa.String(64), nullable=False, server_default='default'),
        sa.Column('team_policy', sa.String(30), nullable=False, server_default='allow'),
        sa.Column('budget_share', sa.Float, nullable=False, server_default='1.0'),
        sa.Column('max_workers', sa.Integer, nullable=False, server_default='20'),
        sa.Column('max_depth', sa.Integer, nullable=False, server_default='5'),
        sa.Column('max_direct_reports', sa.Integer, nullable=False, server_default='10'),
        sa.Column('max_active_tasks', sa.Integer, nullable=False, server_default='30'),
        sa.Column('max_delegations', sa.Integer, nullable=False, server_default='100'),
        sa.Column('max_replans', sa.Integer, nullable=False, server_default='3'),
        sa.Column('max_team_size', sa.Integer, nullable=False, server_default='12'),
        sa.Column('allowed_actions', postgresql.JSONB, nullable=False, server_default='[]'),
        sa.Column('scope', sa.String(20), nullable=False, server_default='organization'),
        sa.Column('department_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('agent_departments.id', ondelete='SET NULL'), nullable=True, index=True),
        sa.Column('team_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('dynamic_teams.id', ondelete='SET NULL'), nullable=True, index=True),
        sa.Column('metadata', postgresql.JSONB, nullable=False, server_default='{}'),
        *_ts(),
    )
    op.create_index('ix_manager_profiles_org_status', 'manager_profiles', ['organization_id', 'status'])

    op.create_table(
        'agent_contracts',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        _org_fk(),
        sa.Column('orchestration_run_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('orchestration_runs.id', ondelete='CASCADE'), nullable=True, index=True),
        sa.Column('task_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('orchestration_tasks.id', ondelete='SET NULL'), nullable=True, index=True),
        _agent_fk('agent_id'), _agent_fk('manager_agent_id'),
        sa.Column('objective', sa.Text, nullable=False),
        sa.Column('responsibilities', postgresql.JSONB, nullable=False, server_default='[]'),
        sa.Column('inputs', postgresql.JSONB, nullable=False, server_default='{}'),
        sa.Column('expected_outputs', postgresql.JSONB, nullable=False, server_default='{}'),
        sa.Column('capabilities', postgresql.JSONB, nullable=False, server_default='[]'),
        sa.Column('constraints', postgresql.JSONB, nullable=False, server_default='[]'),
        sa.Column('permissions', postgresql.JSONB, nullable=False, server_default='[]'),
        sa.Column('budget', postgresql.JSONB, nullable=False, server_default='{}'),
        sa.Column('deadline', sa.DateTime(timezone=True), nullable=True),
        sa.Column('quality_requirements', postgresql.JSONB, nullable=False, server_default='[]'),
        sa.Column('acceptance_criteria', postgresql.JSONB, nullable=False, server_default='[]'),
        sa.Column('escalation_conditions', postgresql.JSONB, nullable=False, server_default='[]'),
        sa.Column('max_revisions', sa.Integer, nullable=False, server_default='3'),
        sa.Column('idempotency_key', sa.String(255), nullable=True, index=True),
        *_ts(),
    )
    op.create_index('ix_agent_contracts_org_run', 'agent_contracts', ['organization_id', 'orchestration_run_id'])

    op.create_table(
        'delegation_requests',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        _org_fk(),
        sa.Column('orchestration_run_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('orchestration_runs.id', ondelete='CASCADE'), nullable=True, index=True),
        sa.Column('task_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('orchestration_tasks.id', ondelete='SET NULL'), nullable=True, index=True),
        sa.Column('contract_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('agent_contracts.id', ondelete='SET NULL'), nullable=True, index=True),
        _agent_fk('source_agent_id'), _agent_fk('target_agent_id'),
        sa.Column('reason', sa.Text, nullable=False, server_default=''),
        sa.Column('required_capabilities', postgresql.JSONB, nullable=False, server_default='[]'),
        sa.Column('constraints', postgresql.JSONB, nullable=False, server_default='[]'),
        sa.Column('budget', postgresql.JSONB, nullable=False, server_default='{}'),
        sa.Column('deadline', sa.DateTime(timezone=True), nullable=True),
        sa.Column('policy', sa.String(30), nullable=False, server_default='hybrid'),
        sa.Column('status', sa.Enum('pending', 'accepted', 'rejected', 'expired', 'cancelled', 'completed',
                                    name='delegation_request_status'),
                  nullable=False, server_default='pending', index=True),
        sa.Column('decision_reason', sa.Text, nullable=True),
        _agent_fk('decided_by'),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True, index=True),
        sa.Column('idempotency_key', sa.String(255), nullable=True, index=True),
        *_ts(),
    )
    op.create_index('ix_delegations_org_status', 'delegation_requests', ['organization_id', 'status'])

    op.create_table(
        'agent_commitments',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        _org_fk(),
        sa.Column('orchestration_run_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('orchestration_runs.id', ondelete='CASCADE'), nullable=True, index=True),
        sa.Column('delegation_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('delegation_requests.id', ondelete='SET NULL'), nullable=True, index=True),
        sa.Column('task_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('orchestration_tasks.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('agent_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('agents.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('deadline', sa.DateTime(timezone=True), nullable=True),
        sa.Column('budget', postgresql.JSONB, nullable=False, server_default='{}'),
        sa.Column('expected_output', sa.Text, nullable=False, server_default=''),
        sa.Column('status', sa.String(30), nullable=False, server_default='accepted', index=True),
        sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('released_at', sa.DateTime(timezone=True), nullable=True),
        *_ts(),
    )
    op.create_index('ix_commitments_task_agent', 'agent_commitments', ['task_id', 'agent_id'])

    op.create_table(
        'handoff_packages',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        _org_fk(),
        sa.Column('orchestration_run_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('orchestration_runs.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('task_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('orchestration_tasks.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('contract_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('agent_contracts.id', ondelete='SET NULL'), nullable=True, index=True),
        _agent_fk('source_agent_id'), _agent_fk('target_agent_id'),
        sa.Column('mode', sa.String(30), nullable=False, server_default='full_handoff'),
        sa.Column('package', postgresql.JSONB, nullable=False, server_default='{}'),
        sa.Column('context_manifest', postgresql.JSONB, nullable=False, server_default='{}'),
        sa.Column('status', sa.Enum('preparing', 'pending_acceptance', 'accepted', 'executing', 'completed',
                                    'rejected', 'expired', 'cancelled', name='handoff_package_status'),
                  nullable=False, server_default='preparing', index=True),
        sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True, index=True),
        sa.Column('idempotency_key', sa.String(255), nullable=True, index=True),
        *_ts(),
    )
    op.create_index('ix_handoff_packages_run_status', 'handoff_packages', ['orchestration_run_id', 'status'])

    op.create_table(
        'review_results',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        _org_fk(),
        sa.Column('orchestration_run_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('orchestration_runs.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('task_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('orchestration_tasks.id', ondelete='CASCADE'), nullable=False, index=True),
        _agent_fk('reviewer_agent_id'),
        sa.Column('status', sa.Enum('approved', 'revision_required', 'rejected', 'escalate',
                                    name='review_result_status'),
                  nullable=False, index=True),
        sa.Column('criteria_results', postgresql.JSONB, nullable=False, server_default='[]'),
        sa.Column('issues', postgresql.JSONB, nullable=False, server_default='[]'),
        sa.Column('required_changes', postgresql.JSONB, nullable=False, server_default='[]'),
        sa.Column('evidence', postgresql.JSONB, nullable=False, server_default='[]'),
        sa.Column('revision_number', sa.Integer, nullable=False, server_default='0'),
        sa.Column('gate_result', sa.String(20), nullable=True),
        *_ts(),
    )
    op.create_index('ix_review_results_task_rev', 'review_results', ['task_id', 'revision_number'])

    op.create_table(
        'escalations',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        _org_fk(),
        sa.Column('orchestration_run_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('orchestration_runs.id', ondelete='CASCADE'), nullable=True, index=True),
        sa.Column('task_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('orchestration_tasks.id', ondelete='SET NULL'), nullable=True, index=True),
        _agent_fk('source_agent_id'), _agent_fk('current_holder_agent_id'),
        sa.Column('trigger', sa.String(40), nullable=False),
        sa.Column('reason', sa.Text, nullable=False),
        sa.Column('severity', sa.String(20), nullable=False, server_default='warning', index=True),
        sa.Column('status', sa.Enum('open', 'acknowledged', 'in_progress', 'resolved', 'escalated', 'closed',
                                    name='escalation_status'),
                  nullable=False, server_default='open', index=True),
        sa.Column('chain', postgresql.JSONB, nullable=False, server_default='[]'),
        sa.Column('chain_level', sa.Integer, nullable=False, server_default='0'),
        sa.Column('recommended_action', sa.Text, nullable=False, server_default=''),
        sa.Column('history', postgresql.JSONB, nullable=False, server_default='[]'),
        sa.Column('human_approval_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('approvals.id', ondelete='SET NULL'), nullable=True, index=True),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('idempotency_key', sa.String(255), nullable=True, index=True),
        *_ts(),
    )
    op.create_index('ix_escalations_org_status', 'escalations', ['organization_id', 'status'])

    op.create_table(
        'team_charters',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        _org_fk(),
        sa.Column('team_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('dynamic_teams.id', ondelete='CASCADE'), nullable=False, unique=True, index=True),
        sa.Column('objective', sa.Text, nullable=False),
        sa.Column('scope', sa.Text, nullable=False, server_default=''),
        sa.Column('responsibilities', postgresql.JSONB, nullable=False, server_default='{}'),
        sa.Column('communication_rules', postgresql.JSONB, nullable=False, server_default='[]'),
        sa.Column('completion_criteria', postgresql.JSONB, nullable=False, server_default='[]'),
        sa.Column('deadline', sa.DateTime(timezone=True), nullable=True),
        sa.Column('budget', postgresql.JSONB, nullable=False, server_default='{}'),
        *_ts(),
    )

    op.create_table(
        'dynamic_team_memberships',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        _org_fk(),
        sa.Column('team_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('dynamic_teams.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('agent_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('agents.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('role', sa.String(64), nullable=False, server_default='worker'),
        sa.Column('responsibilities', postgresql.JSONB, nullable=False, server_default='[]'),
        sa.Column('permissions', postgresql.JSONB, nullable=False, server_default='[]'),
        sa.Column('task_scope', postgresql.JSONB, nullable=False, server_default='[]'),
        sa.Column('status', sa.String(20), nullable=False, server_default='active', index=True),
        *_ts(),
    )
    op.create_index('ix_dyn_team_member_unique', 'dynamic_team_memberships',
                    ['team_id', 'agent_id'], unique=True)

    op.create_table(
        'agent_availability',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        _org_fk(),
        sa.Column('agent_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('agents.id', ondelete='CASCADE'), nullable=False, unique=True, index=True),
        sa.Column('state', sa.String(20), nullable=False, server_default='available', index=True),
        sa.Column('active_tasks', sa.Integer, nullable=False, server_default='0'),
        sa.Column('active_runs', sa.Integer, nullable=False, server_default='0'),
        sa.Column('last_heartbeat_at', sa.DateTime(timezone=True), nullable=True),
        *_ts(),
    )

    op.create_table(
        'agent_capacity',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        _org_fk(),
        sa.Column('agent_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('agents.id', ondelete='CASCADE'), nullable=False, unique=True, index=True),
        sa.Column('max_concurrent_tasks', sa.Integer, nullable=False, server_default='5'),
        sa.Column('max_concurrent_runs', sa.Integer, nullable=False, server_default='2'),
        sa.Column('max_daily_cost', sa.Float, nullable=False, server_default='50.0'),
        sa.Column('max_token_budget', sa.Integer, nullable=False, server_default='500000'),
        sa.Column('daily_cost_used', sa.Float, nullable=False, server_default='0.0'),
        sa.Column('tokens_used', sa.Integer, nullable=False, server_default='0'),
        *_ts(),
    )

    op.create_table(
        'plan_versions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        _org_fk(),
        sa.Column('orchestration_run_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('orchestration_runs.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('version', sa.Integer, nullable=False),
        sa.Column('reason', sa.Text, nullable=False, server_default=''),
        sa.Column('created_by_agent_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('agents.id', ondelete='SET NULL'), nullable=True),
        sa.Column('changes', postgresql.JSONB, nullable=False, server_default='[]'),
        sa.Column('parent_version', sa.Integer, nullable=True),
        sa.Column('plan_snapshot', postgresql.JSONB, nullable=False, server_default='{}'),
        *_ts(),
    )
    op.create_index('ix_plan_versions_run_version', 'plan_versions',
                    ['orchestration_run_id', 'version'], unique=True)

    op.create_table(
        'collaboration_requests',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        _org_fk(),
        sa.Column('orchestration_run_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('orchestration_runs.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('task_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('orchestration_tasks.id', ondelete='SET NULL'), nullable=True, index=True),
        _agent_fk('from_agent_id'), _agent_fk('to_agent_id'),
        sa.Column('action', sa.String(40), nullable=False),
        sa.Column('payload', postgresql.JSONB, nullable=False, server_default='{}'),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending', index=True),
        *_ts(),
    )
    op.create_index('ix_collab_run_status', 'collaboration_requests', ['orchestration_run_id', 'status'])

    op.create_table(
        'manager_decisions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        _org_fk(),
        sa.Column('orchestration_run_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('orchestration_runs.id', ondelete='CASCADE'), nullable=True, index=True),
        _agent_fk('manager_agent_id'),
        sa.Column('task_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('orchestration_tasks.id', ondelete='SET NULL'), nullable=True, index=True),
        sa.Column('decision_type', sa.String(64), nullable=False, index=True),
        sa.Column('selected_action', sa.String(128), nullable=False),
        sa.Column('alternatives', postgresql.JSONB, nullable=False, server_default='[]'),
        sa.Column('policy_basis', sa.Text, nullable=False, server_default=''),
        sa.Column('rationale', sa.Text, nullable=False, server_default=''),
        *_ts(),
    )
    op.create_index('ix_manager_decisions_run', 'manager_decisions', ['orchestration_run_id', 'created_at'])


def downgrade() -> None:
    for table in (
        'manager_decisions', 'collaboration_requests', 'plan_versions',
        'agent_capacity', 'agent_availability', 'dynamic_team_memberships',
        'team_charters', 'manager_profiles', 'dynamic_teams', 'escalations',
        'review_results', 'handoff_packages', 'agent_commitments',
        'delegation_requests', 'agent_contracts', 'agent_departments',
    ):
        op.drop_table(table)
    for enum_name in (
        'dynamic_team_status', 'escalation_status', 'review_result_status',
        'handoff_package_status', 'delegation_request_status', 'manager_profile_status',
    ):
        sa.Enum(name=enum_name).drop(op.get_bind(), checkfirst=True)
