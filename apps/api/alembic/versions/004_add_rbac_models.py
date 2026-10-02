"""Add RBAC models

Revision ID: 004
Revises: 003
Create Date: 2024-01-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '004'
down_revision = '003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create ENUM types
    op.execute("CREATE TYPE permission_action AS ENUM ('create', 'read', 'update', 'delete', 'execute', 'manage', 'invite', 'approve', 'run', 'use')")
    op.execute("CREATE TYPE permission_resource AS ENUM ('organization', 'member', 'role', 'team', 'agent', 'workflow', 'execution', 'tool', 'integration', 'credential', 'api_key', 'audit_log', 'invitation', 'service_account', 'memory', 'conversation', 'approval', 'evaluation', 'webhook', 'mcp_server', 'platform')")
    op.execute("CREATE TYPE permission_scope AS ENUM ('organization', 'team', 'own', 'platform')")
    op.execute("CREATE TYPE role_type AS ENUM ('system', 'custom')")
    op.execute("CREATE TYPE team_membership_role AS ENUM ('lead', 'member')")
    op.execute("CREATE TYPE invitation_status AS ENUM ('pending', 'accepted', 'declined', 'expired', 'revoked')")
    op.execute("CREATE TYPE service_account_status AS ENUM ('active', 'inactive', 'revoked', 'expired')")

    # Permissions table
    op.create_table(
        'permissions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('name', sa.String(100), unique=True, nullable=False),
        sa.Column('resource', postgresql.ENUM('organization', 'member', 'role', 'team', 'agent', 'workflow', 'execution', 'tool', 'integration', 'credential', 'api_key', 'audit_log', 'invitation', 'service_account', 'memory', 'conversation', 'approval', 'evaluation', 'webhook', 'mcp_server', 'platform', name='permission_resource', create_constraint=True), nullable=False),
        sa.Column('action', postgresql.ENUM('create', 'read', 'update', 'delete', 'execute', 'manage', 'invite', 'approve', 'run', 'use', name='permission_action', create_constraint=True), nullable=False),
        sa.Column('scope', postgresql.ENUM('organization', 'team', 'own', 'platform', name='permission_scope', create_constraint=True), default='organization', nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_system', sa.Boolean(), default=False, nullable=False),
        sa.Column('danger_level', sa.Integer(), default=1, nullable=False),
        sa.Column('metadata', postgresql.JSONB(), default={}, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_permissions_name', 'permissions', ['name'])
    op.create_index('ix_permissions_resource', 'permissions', ['resource'])
    op.create_index('ix_permissions_action', 'permissions', ['action'])
    op.create_index('ix_permissions_scope', 'permissions', ['scope'])
    op.create_index('ix_permissions_is_system', 'permissions', ['is_system'])

    # Roles table
    op.create_table(
        'roles',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=True),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('display_name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('role_type', postgresql.ENUM('system', 'custom', name='role_type', create_constraint=True), default='custom', nullable=False),
        sa.Column('is_system', sa.Boolean(), default=False, nullable=False),
        sa.Column('priority', sa.Integer(), default=0, nullable=False),
        sa.Column('metadata', postgresql.JSONB(), default={}, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_unique_constraint('uq_role_org_name', 'roles', ['organization_id', 'name'])
    op.create_index('ix_roles_organization_id', 'roles', ['organization_id'])
    op.create_index('ix_roles_role_type', 'roles', ['role_type'])
    op.create_index('ix_roles_is_system', 'roles', ['is_system'])
    op.create_index('ix_roles_deleted_at', 'roles', ['deleted_at'])

    # Role Permissions table
    op.create_table(
        'role_permissions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('role_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('roles.id', ondelete='CASCADE'), nullable=False),
        sa.Column('permission_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('permissions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_unique_constraint('uq_role_permission', 'role_permissions', ['role_id', 'permission_id'])
    op.create_index('ix_role_permissions_role_id', 'role_permissions', ['role_id'])
    op.create_index('ix_role_permissions_permission_id', 'role_permissions', ['permission_id'])

    # Teams table
    op.create_table(
        'teams',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('slug', sa.String(100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('avatar_url', sa.String(500), nullable=True),
        sa.Column('default_role_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('roles.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=False),
        sa.Column('metadata', postgresql.JSONB(), default={}, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_unique_constraint('uq_team_org_slug', 'teams', ['organization_id', 'slug'])
    op.create_unique_constraint('uq_team_org_name', 'teams', ['organization_id', 'name'])
    op.create_index('ix_teams_organization_id', 'teams', ['organization_id'])
    op.create_index('ix_teams_slug', 'teams', ['slug'])
    op.create_index('ix_teams_deleted_at', 'teams', ['deleted_at'])

    # Team Memberships table
    op.create_table(
        'team_memberships',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('team_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('teams.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('role', postgresql.ENUM('lead', 'member', name='team_membership_role', create_constraint=True), default='member', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_unique_constraint('uq_team_membership_user_team', 'team_memberships', ['team_id', 'user_id'])
    op.create_index('ix_team_memberships_team_id', 'team_memberships', ['team_id'])
    op.create_index('ix_team_memberships_user_id', 'team_memberships', ['user_id'])

    # Organization Invitations table
    op.create_table(
        'organization_invitations',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('email', sa.String(255), nullable=False),
        sa.Column('role_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('roles.id', ondelete='CASCADE'), nullable=False),
        sa.Column('invited_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('token_hash', sa.String(255), unique=True, nullable=False),
        sa.Column('status', postgresql.ENUM('pending', 'accepted', 'declined', 'expired', 'revoked', name='invitation_status', create_constraint=True), default='pending', nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('metadata', postgresql.JSONB(), default={}, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_organization_invitations_organization_id', 'organization_invitations', ['organization_id'])
    op.create_index('ix_organization_invitations_email', 'organization_invitations', ['email'])
    op.create_index('ix_organization_invitations_token_hash', 'organization_invitations', ['token_hash'])
    op.create_index('ix_organization_invitations_status', 'organization_invitations', ['status'])
    op.create_index('ix_organization_invitations_expires_at', 'organization_invitations', ['expires_at'])
    op.create_index('ix_org_invitation_email_status', 'organization_invitations', ['organization_id', 'email', 'status'])

    # Service Accounts table
    op.create_table(
        'service_accounts',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('status', postgresql.ENUM('active', 'inactive', 'revoked', 'expired', name='service_account_status', create_constraint=True), default='active', nullable=False),
        sa.Column('key_hash', sa.String(255), unique=True, nullable=False),
        sa.Column('key_prefix', sa.String(20), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('metadata', postgresql.JSONB(), default={}, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_service_accounts_organization_id', 'service_accounts', ['organization_id'])
    op.create_index('ix_service_accounts_key_hash', 'service_accounts', ['key_hash'])
    op.create_index('ix_service_accounts_key_prefix', 'service_accounts', ['key_prefix'])
    op.create_index('ix_service_accounts_status', 'service_accounts', ['status'])
    op.create_index('ix_service_accounts_expires_at', 'service_accounts', ['expires_at'])
    op.create_index('ix_service_accounts_deleted_at', 'service_accounts', ['deleted_at'])

    # Service Account Permissions table
    op.create_table(
        'service_account_permissions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('service_account_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('service_accounts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('permission_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('permissions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_unique_constraint('uq_service_account_permission', 'service_account_permissions', ['service_account_id', 'permission_id'])
    op.create_index('ix_service_account_permissions_service_account_id', 'service_account_permissions', ['service_account_id'])
    op.create_index('ix_service_account_permissions_permission_id', 'service_account_permissions', ['permission_id'])

    # Add role_id to memberships
    op.add_column('memberships', sa.Column('role_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('roles.id', ondelete='SET NULL'), nullable=True))
    op.add_column('memberships', sa.Column('legacy_role', sa.String(50), nullable=False, server_default='member'))
    op.create_index('ix_memberships_role_id', 'memberships', ['role_id'])

    # Update memberships to use legacy_role
    op.execute("UPDATE memberships SET legacy_role = role::text")
    op.alter_column('memberships', 'role', new_column_name='legacy_role_temp')
    op.drop_column('memberships', 'legacy_role_temp')
    # Note: The original 'role' column was a VARCHAR, we need to handle the enum conversion carefully
    # This is handled by the ORM model using the legacy_role column


def downgrade() -> None:
    # Remove role_id from memberships
    op.drop_index('ix_memberships_role_id', table_name='memberships')
    op.drop_column('memberships', 'role_id')
    op.drop_column('memberships', 'legacy_role')

    # Drop tables
    op.drop_table('service_account_permissions')
    op.drop_table('service_accounts')
    op.drop_table('organization_invitations')
    op.drop_table('team_memberships')
    op.drop_table('teams')
    op.drop_table('role_permissions')
    op.drop_table('roles')
    op.drop_table('permissions')

    # Drop ENUM types
    op.execute("DROP TYPE IF EXISTS service_account_status")
    op.execute("DROP TYPE IF EXISTS invitation_status")
    op.execute("DROP TYPE IF EXISTS team_membership_role")
    op.execute("DROP TYPE IF EXISTS role_type")
    op.execute("DROP TYPE IF EXISTS permission_scope")
    op.execute("DROP TYPE IF EXISTS permission_resource")
    op.execute("DROP TYPE IF EXISTS permission_action")