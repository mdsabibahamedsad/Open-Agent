"""Add authentication models

Revision ID: 003
Revises: 002
Create Date: 2024-01-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '003'
down_revision = '002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add columns to users table
    op.add_column('users', sa.Column('password_hash', sa.String(255), nullable=True))
    op.add_column('users', sa.Column('email_verified', sa.Boolean(), default=False, nullable=False))

    # Add columns to sessions table
    op.add_column('sessions', sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('sessions', sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index('ix_sessions_revoked_at', 'sessions', ['revoked_at'])

    # Create ENUM types
    op.execute("CREATE TYPE platform_owner_status AS ENUM ('active', 'inactive', 'suspended')")
    op.execute("CREATE TYPE security_event_type AS ENUM ('login.success', 'login.failed', 'logout', 'logout.all', 'password.changed', 'password.reset.requested', 'password.reset.completed', 'email.verification.completed', 'session.revoked', 'account.suspended', 'account.unsuspended', 'master.login', 'master.session.created', 'master.session.revoked', 'mfa.enabled', 'mfa.disabled', 'registration', 'email.verification.sent', 'password.reset.email.sent')")

    # Email Verification Tokens table
    op.create_table(
        'email_verification_tokens',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('token_hash', sa.String(255), unique=True, nullable=False),
        sa.Column('email', sa.String(255), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_email_verification_tokens_user_id', 'email_verification_tokens', ['user_id'])
    op.create_index('ix_email_verification_tokens_token_hash', 'email_verification_tokens', ['token_hash'])
    op.create_index('ix_email_verification_tokens_expires_at', 'email_verification_tokens', ['expires_at'])

    # Password Reset Tokens table
    op.create_table(
        'password_reset_tokens',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('token_hash', sa.String(255), unique=True, nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_password_reset_tokens_user_id', 'password_reset_tokens', ['user_id'])
    op.create_index('ix_password_reset_tokens_token_hash', 'password_reset_tokens', ['token_hash'])
    op.create_index('ix_password_reset_tokens_expires_at', 'password_reset_tokens', ['expires_at'])

    # Platform Owners table
    op.create_table(
        'platform_owners',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, unique=True),
        sa.Column('status', postgresql.ENUM('active', 'inactive', 'suspended', name='platform_owner_status', create_constraint=True), default='active', nullable=False),
        sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('mfa_enabled', sa.Boolean(), default=False, nullable=False),
        sa.Column('mfa_secret_encrypted', sa.Text(), nullable=True),
        sa.Column('recovery_codes_hash', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_platform_owners_user_id', 'platform_owners', ['user_id'])
    op.create_index('ix_platform_owners_status', 'platform_owners', ['status'])

    # Security Events table
    op.create_table(
        'security_events',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='SET NULL'), nullable=True),
        sa.Column('event_type', postgresql.ENUM('login.success', 'login.failed', 'logout', 'logout.all', 'password.changed', 'password.reset.requested', 'password.reset.completed', 'email.verification.completed', 'session.revoked', 'account.suspended', 'account.unsuspended', 'master.login', 'master.session.created', 'master.session.revoked', 'mfa.enabled', 'mfa.disabled', 'registration', 'email.verification.sent', 'password.reset.email.sent', name='security_event_type', create_constraint=True), nullable=False),
        sa.Column('ip_address', sa.String(45), nullable=True),
        sa.Column('user_agent', sa.Text(), nullable=True),
        sa.Column('metadata', postgresql.JSONB(), default={}, nullable=False),
        sa.Column('request_id', sa.String(100), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_security_events_user_id', 'security_events', ['user_id'])
    op.create_index('ix_security_events_organization_id', 'security_events', ['organization_id'])
    op.create_index('ix_security_events_event_type', 'security_events', ['event_type'])
    op.create_index('ix_security_events_created_at', 'security_events', ['created_at'])
    op.create_index('ix_security_events_request_id', 'security_events', ['request_id'])
    op.create_index('ix_security_events_user_created', 'security_events', ['user_id', 'created_at'])
    op.create_index('ix_security_events_org_created', 'security_events', ['organization_id', 'created_at'])


def downgrade() -> None:
    op.drop_table('security_events')
    op.drop_table('platform_owners')
    op.drop_table('password_reset_tokens')
    op.drop_table('email_verification_tokens')

    op.drop_index('ix_sessions_revoked_at', table_name='sessions')
    op.drop_column('sessions', 'last_seen_at')
    op.drop_column('sessions', 'revoked_at')

    op.drop_column('users', 'email_verified')
    op.drop_column('users', 'password_hash')

    op.execute("DROP TYPE IF EXISTS security_event_type")
    op.execute("DROP TYPE IF EXISTS platform_owner_status")