"""Add scheduled jobs tables

Revision ID: 008
Revises: 007
Create Date: 2024-01-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '008'
down_revision = '007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create ENUM types
    op.execute("CREATE TYPE schedule_status AS ENUM ('active', 'paused', 'completed', 'failed', 'deleted')")
    op.execute("CREATE TYPE schedule_trigger_type AS ENUM ('cron', 'interval', 'one_time', 'event')")
    op.execute("CREATE TYPE schedule_run_status AS ENUM ('pending', 'running', 'completed', 'failed', 'cancelled')")

    # Scheduled Jobs table
    op.create_table(
        'scheduled_jobs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('job_type', sa.String(100), nullable=False),
        sa.Column('payload', postgresql.JSONB(), nullable=False, default='{}'),
        sa.Column('trigger_type', postgresql.ENUM('cron', 'interval', 'one_time', 'event', name='schedule_trigger_type', create_constraint=True), nullable=False),
        sa.Column('cron_expression', sa.String(100), nullable=True),
        sa.Column('interval_seconds', sa.Integer(), nullable=True),
        sa.Column('run_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('timezone', sa.String(50), default='UTC', nullable=False),
        sa.Column('status', postgresql.ENUM('active', 'paused', 'completed', 'failed', 'deleted', name='schedule_status', create_constraint=True), default='active', nullable=False),
        sa.Column('max_concurrent', sa.Integer(), default=1, nullable=False),
        sa.Column('timeout_seconds', sa.Integer(), default=300, nullable=False),
        sa.Column('max_retries', sa.Integer(), default=3, nullable=False),
        sa.Column('retry_delay_seconds', sa.Integer(), default=60, nullable=False),
        sa.Column('last_run_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('next_run_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('run_count', sa.Integer(), default=0, nullable=False),
        sa.Column('failure_count', sa.Integer(), default=0, nullable=False),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('metadata', postgresql.JSONB(), default={}, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_scheduled_jobs_org_status', 'scheduled_jobs', ['organization_id', 'status'])
    op.create_index('ix_scheduled_jobs_next_run', 'scheduled_jobs', ['next_run_at'])
    op.create_index('ix_scheduled_jobs_status_type', 'scheduled_jobs', ['status', 'job_type'])
    op.create_index('ix_scheduled_jobs_org_type', 'scheduled_jobs', ['organization_id', 'job_type'])

    # Scheduled Job Runs table
    op.create_table(
        'scheduled_job_runs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('job_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('scheduled_jobs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('status', postgresql.ENUM('pending', 'running', 'completed', 'failed', 'cancelled', name='schedule_run_status', create_constraint=True), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('result', postgresql.JSONB(), nullable=True),
        sa.Column('attempt', sa.Integer(), default=1, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_scheduled_job_runs_job_status', 'scheduled_job_runs', ['job_id', 'status'])
    op.create_index('ix_scheduled_job_runs_started', 'scheduled_job_runs', ['started_at'])


def downgrade() -> None:
    op.drop_table('scheduled_job_runs')
    op.drop_table('scheduled_jobs')

    op.execute("DROP TYPE IF EXISTS schedule_run_status")
    op.execute("DROP TYPE IF EXISTS schedule_trigger_type")
    op.execute("DROP TYPE IF EXISTS schedule_status")