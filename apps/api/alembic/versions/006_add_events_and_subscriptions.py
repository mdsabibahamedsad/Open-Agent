"""Add events and event subscriptions tables

Revision ID: 006
Revises: 005
Create Date: 2024-01-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '006'
down_revision = '005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create ENUM types
    op.execute("CREATE TYPE event_status AS ENUM ('pending', 'published', 'failed', 'archived')")
    op.execute("CREATE TYPE event_priority AS ENUM ('low', 'normal', 'high', 'critical')")

    # Events table
    op.create_table(
        'events',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('event_type', sa.String(255), nullable=False),
        sa.Column('aggregate_type', sa.String(100), nullable=False),
        sa.Column('aggregate_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('payload', postgresql.JSONB(), nullable=False, default='{}'),
        sa.Column('metadata', postgresql.JSONB(), nullable=False, default='{}'),
        sa.Column('status', postgresql.ENUM('pending', 'published', 'failed', 'archived', name='event_status', create_constraint=True), default='pending', nullable=False),
        sa.Column('priority', postgresql.ENUM('low', 'normal', 'high', 'critical', name='event_priority', create_constraint=True), default='normal', nullable=False),
        sa.Column('retry_count', sa.Integer(), default=0, nullable=False),
        sa.Column('max_retries', sa.Integer(), default=3, nullable=False),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('scheduled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_events_status_priority', 'events', ['status', 'priority'])
    op.create_index('ix_events_aggregate', 'events', ['aggregate_type', 'aggregate_id'])
    op.create_index('ix_events_scheduled', 'events', ['scheduled_at'])
    op.create_index('ix_events_org_status', 'events', ['organization_id', 'status'])
    op.create_index('ix_events_aggregate_type', 'events', ['aggregate_type'])
    op.create_index('ix_events_organization_id', 'events', ['organization_id'])
    op.create_index('ix_events_user_id', 'events', ['user_id'])

    # Event Subscriptions table
    op.create_table(
        'event_subscriptions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('event_types', postgresql.JSONB(), nullable=False, default='[]'),
        sa.Column('callback_url', sa.String(500), nullable=False),
        sa.Column('secret_hash', sa.String(255), nullable=False),
        sa.Column('secret_prefix', sa.String(20), nullable=False),
        sa.Column('is_active', sa.Boolean(), default=True, nullable=False),
        sa.Column('retry_count', sa.Integer(), default=3, nullable=False),
        sa.Column('timeout_seconds', sa.Integer(), default=30, nullable=False),
        sa.Column('last_delivery_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_delivery_status', sa.Integer(), nullable=True),
        sa.Column('last_delivery_error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_event_subscriptions_org_active', 'event_subscriptions', ['organization_id', 'is_active'])


def downgrade() -> None:
    op.drop_table('event_subscriptions')
    op.drop_table('events')
    op.execute("DROP TYPE IF EXISTS event_priority")
    op.execute("DROP TYPE IF EXISTS event_status")