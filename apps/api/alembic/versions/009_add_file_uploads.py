"""Add file uploads table

Revision ID: 009
Revises: 008
Create Date: 2024-01-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '009'
down_revision = '008'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create ENUM type
    op.execute("CREATE TYPE file_upload_status AS ENUM ('pending', 'uploading', 'completed', 'failed', 'expired')")

    # File Uploads table
    op.create_table(
        'file_uploads',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('filename', sa.String(255), nullable=False),
        sa.Column('original_filename', sa.String(255), nullable=False),
        sa.Column('content_type', sa.String(100), nullable=False),
        sa.Column('size', sa.Integer(), nullable=False),
        sa.Column('checksum', sa.String(64), nullable=False),
        sa.Column('storage_provider', sa.String(50), nullable=False),
        sa.Column('storage_key', sa.String(500), nullable=False),
        sa.Column('storage_bucket', sa.String(255), nullable=True),
        sa.Column('status', postgresql.ENUM('pending', 'uploading', 'completed', 'failed', 'expired', name='file_upload_status', create_constraint=True), default='pending', nullable=False),
        sa.Column('progress', sa.Integer(), default=0, nullable=False),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('metadata', postgresql.JSONB(), default={}, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_file_uploads_organization_id', 'file_uploads', ['organization_id'])
    op.create_index('ix_file_uploads_user_id', 'file_uploads', ['user_id'])
    op.create_index('ix_file_uploads_status', 'file_uploads', ['status'])
    op.create_index('ix_file_uploads_expires_at', 'file_uploads', ['expires_at'])
    op.create_index('ix_file_uploads_checksum', 'file_uploads', ['checksum'])


def downgrade() -> None:
    op.drop_table('file_uploads')
    op.execute("DROP TYPE IF EXISTS file_upload_status")