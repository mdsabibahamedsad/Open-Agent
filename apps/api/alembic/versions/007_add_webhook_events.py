"""Add webhook events table

Revision ID: 007
Revises: 006
Create Date: 2024-01-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '007'
down_revision = '006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create ENUM type
    op.execute("CREATE TYPE webhook_event_status AS ENUM ('pending', 'delivered', 'failed', 'retrying')")

    # Webhook Events table
    op.create_table(
        'webhook_events',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('webhook_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('webhooks.id', ondelete='CASCADE'), nullable=False),
        sa.Column('event_type', sa.String(255), nullable=False),
        sa.Column('payload', postgresql.JSONB(), nullable=False),
        sa.Column('status', postgresql.ENUM('pending', 'delivered', 'failed', 'retrying', name='webhook_event_status', create_constraint=True), default='pending', nullable=False),
        sa.Column('attempt', sa.Integer(), default=0, nullable=False),
        sa.Column('max_attempts', sa.Integer(), default=5, nullable=False),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('response_status', sa.Integer(), nullable=True),
        sa.Column('response_body', sa.Text(), nullable=True),
        sa.Column('response_headers', postgresql.JSONB(), nullable=True),
        sa.Column('next_retry_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('delivered_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_webhook_events_webhook_status', 'webhook_events', ['webhook_id', 'status'])
    op.create_index('ix_webhook_events_next_retry', 'webhook_events', ['next_retry_at'])


def downgrade() -> None:
    op.drop_table('webhook_events')
    op.execute("DROP TYPE IF EXISTS webhook_event_status")