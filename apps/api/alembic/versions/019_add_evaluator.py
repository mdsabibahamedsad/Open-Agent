"""Add MP20 evaluator / verification / self-correction tables + extend evaluations.

Revision ID: 019_add_evaluator
Revises: 018_add_approvals
Create Date: 2026-09-29 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '019_add_evaluator'
down_revision = '018_add_approvals'
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


def _eval_fk():
    return sa.Column('evaluation_id', postgresql.UUID(as_uuid=True),
                     sa.ForeignKey('evaluations.id', ondelete='CASCADE'),
                     nullable=False)


def upgrade() -> None:
    # Extend evaluation_status enum with MP20 lifecycle values (additive).
    for value in ('passed', 'uncertain', 'skipped', 'cancelled', 'error'):
        op.execute(f"ALTER TYPE evaluation_status ADD VALUE IF NOT EXISTS '{value}'")

    # Threat telemetry for the evaluator layer (additive).
    for value in ('evaluator.manipulation_attempt', 'evidence.tamper_attempt',
                  'evaluation.cross_tenant_attempt',
                  'evaluation.self_evaluation_abuse',
                  'evaluation.score_manipulation',
                  'correction.policy_bypass_attempt', 'correction.loop_abuse'):
        op.execute(f"ALTER TYPE security_event_type ADD VALUE IF NOT EXISTS '{value}'")

    # Extend evaluations with MP20 quality-control columns (all nullable/safe).
    op.add_column('evaluations', sa.Column('evaluation_type', sa.String(64),
                                           nullable=False, server_default='TASK_SUCCESS'))
    op.add_column('evaluations', sa.Column('task_id', sa.String(255), nullable=True))
    op.add_column('evaluations', sa.Column('agent_id', postgresql.UUID(as_uuid=True),
                                           sa.ForeignKey('agents.id', ondelete='SET NULL'),
                                           nullable=True))
    op.add_column('evaluations', sa.Column('workflow_id', postgresql.UUID(as_uuid=True),
                                           sa.ForeignKey('workflows.id', ondelete='SET NULL'),
                                           nullable=True))
    op.add_column('evaluations', sa.Column('parent_evaluation_id',
                                           postgresql.UUID(as_uuid=True),
                                           sa.ForeignKey('evaluations.id', ondelete='SET NULL'),
                                           nullable=True))
    op.add_column('evaluations', sa.Column('attempt_number', sa.Integer(),
                                           nullable=False, server_default='0'))
    op.add_column('evaluations', sa.Column('decision', sa.String(30), nullable=True))
    op.add_column('evaluations', sa.Column('confidence', sa.Float(), nullable=True))
    op.add_column('evaluations', sa.Column('failure_class', sa.String(40), nullable=True))
    op.add_column('evaluations', sa.Column('failure_reason', sa.Text(), nullable=True))
    op.add_column('evaluations', sa.Column('uncertainty_reason', sa.Text(), nullable=True))
    op.add_column('evaluations', sa.Column('input_hash', sa.String(64), nullable=True))
    op.add_column('evaluations', sa.Column('output_hash', sa.String(64), nullable=True))
    op.add_column('evaluations', sa.Column('evaluator_version', sa.String(64),
                                           nullable=False, server_default='evaluator-v1'))
    op.add_column('evaluations', sa.Column('rubric_version', sa.String(64), nullable=True))
    op.add_column('evaluations', sa.Column('policy_version', sa.String(64), nullable=True))
    op.add_column('evaluations', sa.Column('model_version', sa.String(255), nullable=True))
    op.add_column('evaluations', sa.Column('verification_version', sa.String(64),
                                           nullable=False, server_default='verification-v1'))
    op.create_index('ix_evaluations_org_type', 'evaluations',
                    ['organization_id', 'evaluation_type'])
    op.create_index('ix_evaluations_org_decision', 'evaluations',
                    ['organization_id', 'decision'])
    op.create_index('ix_evaluations_task', 'evaluations', ['task_id'])
    op.create_index('ix_evaluations_parent', 'evaluations', ['parent_evaluation_id'])

    op.create_table(
        'evaluation_evidence', _uuid_pk(), _eval_fk(), _org_fk(),
        sa.Column('evidence_type', sa.String(64), nullable=False),
        sa.Column('trust', sa.String(32), nullable=False, server_default='UNVERIFIED'),
        sa.Column('content', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('source', sa.String(256), nullable=False, server_default=''),
        sa.Column('source_type', sa.String(64), nullable=False, server_default=''),
        sa.Column('source_id', sa.String(256), nullable=False, server_default=''),
        sa.Column('content_hash', sa.String(64), nullable=False, server_default=''),
        sa.Column('captured_at', sa.DateTime(timezone=True), nullable=True),
        *_ts(),
    )
    op.create_index('ix_evaluation_evidence_eval', 'evaluation_evidence', ['evaluation_id'])
    op.create_index('ix_evaluation_evidence_org_trust', 'evaluation_evidence',
                    ['organization_id', 'trust'])

    op.create_table(
        'evaluation_results', _uuid_pk(), _eval_fk(), _org_fk(),
        sa.Column('source', sa.String(128), nullable=False, server_default=''),
        sa.Column('decision', sa.String(30), nullable=False),
        sa.Column('score', sa.Float(), nullable=False, server_default='0'),
        sa.Column('confidence', sa.Float(), nullable=False, server_default='0'),
        sa.Column('reason_codes', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('weight', sa.Float(), nullable=False, server_default='1'),
        sa.Column('model', sa.String(255), nullable=False, server_default=''),
        *_ts(),
    )
    op.create_index('ix_evaluation_results_eval', 'evaluation_results', ['evaluation_id'])
    op.create_index('ix_evaluation_results_org_decision', 'evaluation_results',
                    ['organization_id', 'decision'])

    op.create_table(
        'verification_checks', _uuid_pk(), _eval_fk(), _org_fk(),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('kind', sa.String(64), nullable=False, server_default=''),
        sa.Column('passed', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('reason', sa.Text(), nullable=False, server_default=''),
        sa.Column('required', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('critical_safety', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('evidence_id', sa.String(64), nullable=False, server_default=''),
        *_ts(),
    )
    op.create_index('ix_verification_checks_eval', 'verification_checks', ['evaluation_id'])

    op.create_table(
        'evaluation_disagreements', _uuid_pk(), _eval_fk(), _org_fk(),
        sa.Column('votes', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('policy', sa.String(64), nullable=False, server_default='CONSERVATIVE_FAIL'),
        sa.Column('resolution', sa.String(64), nullable=False, server_default=''),
        *_ts(),
    )
    op.create_index('ix_evaluation_disagreements_eval', 'evaluation_disagreements',
                    ['evaluation_id'])

    op.create_table(
        'evaluation_rubrics', _uuid_pk(), _org_fk(),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('criteria', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('quality_threshold', sa.Float(), nullable=False, server_default='0.7'),
        sa.Column('confidence_threshold', sa.Float(), nullable=False, server_default='0.6'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        *_ts(),
    )
    op.create_index('ix_evaluation_rubrics_org_active', 'evaluation_rubrics',
                    ['organization_id', 'is_active'])
    op.create_index('ix_evaluation_rubrics_org_name', 'evaluation_rubrics',
                    ['organization_id', 'name'])

    op.create_table(
        'evaluation_rubric_versions', _uuid_pk(),
        sa.Column('rubric_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('evaluation_rubrics.id', ondelete='CASCADE'), nullable=False),
        _org_fk(),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('criteria', sa.JSON(), nullable=False, server_default='[]'),
        *_ts(),
    )
    op.create_index('ix_evaluation_rubric_versions_rubric', 'evaluation_rubric_versions',
                    ['rubric_id'])

    op.create_table(
        'correction_plans', _uuid_pk(), _eval_fk(), _org_fk(),
        sa.Column('attempt_number', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('failure_class', sa.String(40), nullable=False, server_default='UNKNOWN'),
        sa.Column('root_cause', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('proposed_strategy', sa.String(40), nullable=False),
        sa.Column('changes', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('risk_level', sa.String(20), nullable=False, server_default='LOW'),
        sa.Column('approval_required', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('approval_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('approvals.id', ondelete='SET NULL'), nullable=True),
        sa.Column('status', sa.String(30), nullable=False, server_default='proposed'),
        sa.Column('result', sa.JSON(), nullable=False, server_default='{}'),
        *_ts(),
    )
    op.create_index('ix_correction_plans_eval', 'correction_plans', ['evaluation_id'])
    op.create_index('ix_correction_plans_org_status', 'correction_plans',
                    ['organization_id', 'status'])

    op.create_table(
        'correction_attempts', _uuid_pk(),
        sa.Column('plan_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('correction_plans.id', ondelete='CASCADE'), nullable=False),
        _eval_fk(), _org_fk(),
        sa.Column('attempt_number', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('action', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('outcome', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('status', sa.String(30), nullable=False, server_default='pending'),
        sa.Column('failure_signature', sa.String(64), nullable=False, server_default=''),
        *_ts(),
    )
    op.create_index('ix_correction_attempts_plan', 'correction_attempts', ['plan_id'])

    op.create_table(
        'evaluation_feedback', _uuid_pk(), _eval_fk(), _org_fk(),
        sa.Column('reviewer_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('verdict', sa.String(30), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False, server_default=''),
        sa.Column('feedback', sa.Text(), nullable=False, server_default=''),
        *_ts(),
    )
    op.create_index('ix_evaluation_feedback_eval', 'evaluation_feedback', ['evaluation_id'])

    op.create_table(
        'quality_gates', _uuid_pk(), _org_fk(),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('required_checks', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('thresholds', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('failure_behavior', sa.String(30), nullable=False, server_default='FAIL'),
        sa.Column('approval_required', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        *_ts(),
    )
    op.create_index('ix_quality_gates_org_active', 'quality_gates',
                    ['organization_id', 'is_active'])
    op.create_index('ix_quality_gates_org_name', 'quality_gates',
                    ['organization_id', 'name'])

    op.create_table(
        'benchmarks', _uuid_pk(), _org_fk(),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('dataset', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('criteria', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        *_ts(),
    )
    op.create_index('ix_benchmarks_org_active', 'benchmarks',
                    ['organization_id', 'is_active'])

    op.create_table(
        'benchmark_runs', _uuid_pk(),
        sa.Column('benchmark_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('benchmarks.id', ondelete='CASCADE'), nullable=False),
        _org_fk(),
        sa.Column('status', sa.String(30), nullable=False, server_default='running'),
        sa.Column('scores', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('items', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('baseline_run_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('benchmark_runs.id', ondelete='SET NULL'), nullable=True),
        sa.Column('regression', sa.JSON(), nullable=False, server_default='{}'),
        *_ts(),
    )
    op.create_index('ix_benchmark_runs_benchmark', 'benchmark_runs', ['benchmark_id'])


def downgrade() -> None:
    for table in ('benchmark_runs', 'benchmarks', 'quality_gates',
                  'evaluation_feedback', 'correction_attempts', 'correction_plans',
                  'evaluation_rubric_versions', 'evaluation_rubrics',
                  'evaluation_disagreements', 'verification_checks',
                  'evaluation_results', 'evaluation_evidence'):
        op.drop_table(table)
    for column in ('verification_version', 'model_version', 'policy_version',
                   'rubric_version', 'evaluator_version', 'output_hash', 'input_hash',
                   'uncertainty_reason', 'failure_reason', 'failure_class',
                   'confidence', 'decision', 'attempt_number', 'parent_evaluation_id',
                   'workflow_id', 'agent_id', 'task_id', 'evaluation_type'):
        op.drop_column('evaluations', column)
    for index in ('ix_evaluations_parent', 'ix_evaluations_task',
                  'ix_evaluations_org_decision', 'ix_evaluations_org_type'):
        op.drop_index(index, table_name='evaluations')
    # Enum values are left in place (Postgres cannot drop enum values safely).
