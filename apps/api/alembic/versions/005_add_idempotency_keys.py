"""Add idempotency keys table

Revision ID: 005
Revises: 004
Create Date: 2024-01-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '005'
down_revision = '004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create ENUM type
    op.execute("CREATE TYPE idempotency_status AS ENUM ('processing', 'completed', 'failed')")

    # Idempotency Keys table
    op.create_table(
        'idempotency_keys',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='SET NULL'), nullable=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('key', sa.String(255), nullable=False),
        sa.Column('key_hash', sa.String(64), unique=True, nullable=False),
        sa.Column('endpoint', sa.String(255), nullable=False),
        sa.Column('method', sa.String(10), nullable=False),
        sa.Column('request_hash', sa.String(64), nullable=False),
        sa.Column('request_body', postgresql.JSONB(), nullable=True),
        sa.Column('status', postgresql.ENUM('processing', 'completed', 'failed', name='idempotency_status', create_constraint=True), default='processing', nullable=False),
        sa.Column('response_status_code', sa.Integer(), nullable=True),
        sa.Column('response_body', postgresql.JSONB(), nullable=True),
        sa.Column('response_headers', postgresql.JSONB(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_idempotency_keys_key_hash', 'idempotency_keys', ['key_hash'])
    op.create_index('ix_idempotency_keys_organization_endpoint', 'idempotency_keys', ['organization_id', 'endpoint'])
    op.create_index('ix_idempotency_keys_user_endpoint', 'idempotency_keys', ['user_id', 'endpoint'])
    op.create_index('ix_idempotency_keys_expires_at', 'idempotency_keys', ['expires_at'])
    op.create_index('ix_idempotency_keys_status', 'idempotency_keys', ['status'])


def downgrade() -> None:
    op.drop_table('idempotency_keys')
    op.execute("DROP TYPE IF EXISTS idempotency_status")