"""Add browser automation tables

Revision ID: 015_add_browser_automation
Revises: 013_add_management
Create Date: 2026-09-27 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '015_add_browser_automation'
down_revision = '013_add_management'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create enums
    browser_provider_type_enum = sa.Enum('playwright', 'browserless', 'remote_chromium', 'cloud_browser', 'custom', name='browser_provider_type')
    browser_provider_type_enum.create(op.get_bind(), checkfirst=True)

    browser_type_enum = sa.Enum('chromium', 'firefox', 'webkit', name='browser_type')
    browser_type_enum.create(op.get_bind(), checkfirst=True)

    browser_session_status_enum = sa.Enum('CREATED', 'STARTING', 'READY', 'BUSY', 'WAITING', 'PAUSED', 'ERROR', 'CLOSING', 'CLOSED', 'EXPIRED', name='browser_session_status')
    browser_session_status_enum.create(op.get_bind(), checkfirst=True)

    browser_profile_type_enum = sa.Enum('EPHEMERAL', 'PERSISTENT', 'SHARED', 'ORGANIZATION', 'USER', name='browser_profile_type')
    browser_profile_type_enum.create(op.get_bind(), checkfirst=True)

    browser_page_status_enum = sa.Enum('CREATED', 'LOADING', 'READY', 'CLOSED', 'ERROR', name='browser_page_status')
    browser_page_status_enum.create(op.get_bind(), checkfirst=True)

    browser_action_type_enum = sa.Enum(
        'NAVIGATE', 'CLICK', 'DOUBLE_CLICK', 'TYPE', 'FILL', 'SELECT', 'CHECK', 'UNCHECK',
        'HOVER', 'SCROLL', 'PRESS_KEY', 'DRAG', 'DROP', 'WAIT', 'SCREENSHOT', 'EXTRACT',
        'UPLOAD', 'DOWNLOAD', 'SWITCH_TAB', 'GO_BACK', 'GO_FORWARD', 'RELOAD', 'FOCUS',
        'EVALUATE', 'SET_VIEWPORT', 'SET_COOKIE', 'CLEAR_COOKIES', 'GET_COOKIES',
        'AUTHENTICATE', 'HANDLE_DIALOG', 'WAIT_FOR_SELECTOR', 'WAIT_FOR_NAVIGATION',
        'WAIT_FOR_FUNCTION', 'SELECT_OPTION', 'SET_INPUT_FILES', 'CHECKBOX', 'RADIO',
        name='browser_action_type'
    )
    browser_action_type_enum.create(op.get_bind(), checkfirst=True)

    browser_action_risk_level_enum = sa.Enum('LOW', 'MEDIUM', 'HIGH', 'CRITICAL', name='browser_action_risk_level')
    browser_action_risk_level_enum.create(op.get_bind(), checkfirst=True)

    browser_task_status_enum = sa.Enum('QUEUED', 'STARTING', 'RUNNING', 'WAITING', 'WAITING_FOR_HUMAN', 'PAUSED', 'SUCCEEDED', 'FAILED', 'CANCELLED', 'TIMED_OUT', name='browser_task_status')
    browser_task_status_enum.create(op.get_bind(), checkfirst=True)

    browser_domain_policy_action_enum = sa.Enum('ALLOW', 'DENY', 'CONFIRM', name='browser_domain_policy_action')
    browser_domain_policy_action_enum.create(op.get_bind(), checkfirst=True)

    browser_challenge_type_enum = sa.Enum('CAPTCHA', 'MFA_REQUIRED', 'LOGIN_REQUIRED', 'SECURITY_CHECK', 'BOT_CHALLENGE', name='browser_challenge_type')
    browser_challenge_type_enum.create(op.get_bind(), checkfirst=True)

    browser_artifact_type_enum = sa.Enum('screenshot', 'download', 'extraction', 'html', 'har', 'video', 'trace', name='browser_artifact_type')
    browser_artifact_type_enum.create(op.get_bind(), checkfirst=True)

    # Create browser_profiles table
    op.create_table(
        'browser_profiles',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=sa.text('gen_random_uuid()')),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('owner_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('display_name', sa.String(255), nullable=False),
        sa.Column('browser_type', browser_type_enum, default='chromium', nullable=False),
        sa.Column('profile_type', browser_profile_type_enum, default='EPHEMERAL', nullable=False),
        sa.Column('storage_state', postgresql.JSONB, nullable=True),
        sa.Column('policy', postgresql.JSONB, default={}, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True, index=True),
    )
    op.create_index('ix_browser_profiles_organization_id', 'browser_profiles', ['organization_id'])
    op.create_index('ix_browser_profiles_owner_id', 'browser_profiles', ['owner_id'])
    op.create_index('ix_browser_profiles_profile_type', 'browser_profiles', ['profile_type'])
    op.create_index('ix_browser_profiles_deleted_at', 'browser_profiles', ['deleted_at'])

    # Create browser_sessions table
    op.create_table(
        'browser_sessions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=sa.text('gen_random_uuid()')),
        sa.Column('session_id', sa.String(100), nullable=False, unique=True, index=True),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True),
        sa.Column('agent_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('agents.id', ondelete='SET NULL'), nullable=True, index=True),
        sa.Column('workflow_execution_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('workflow_executions.id', ondelete='SET NULL'), nullable=True, index=True),
        sa.Column('browser_profile_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('browser_profiles.id', ondelete='SET NULL'), nullable=True, index=True),
        sa.Column('provider', browser_provider_type_enum, default='playwright', nullable=False),
        sa.Column('provider_config', postgresql.JSONB, default={}, nullable=False),
        sa.Column('status', browser_session_status_enum, default='CREATED', nullable=False, index=True),
        sa.Column('headless', sa.Boolean, default=True, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('last_activity_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column('metadata', postgresql.JSONB, default={}, nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True, index=True),
    )
    op.create_index('ix_browser_sessions_organization_id', 'browser_sessions', ['organization_id'])
    op.create_index('ix_browser_sessions_user_id', 'browser_sessions', ['user_id'])
    op.create_index('ix_browser_sessions_agent_id', 'browser_sessions', ['agent_id'])
    op.create_index('ix_browser_sessions_workflow_execution_id', 'browser_sessions', ['workflow_execution_id'])
    op.create_index('ix_browser_sessions_status', 'browser_sessions', ['status'])
    op.create_index('ix_browser_sessions_expires_at', 'browser_sessions', ['expires_at'])
    op.create_index('ix_browser_sessions_deleted_at', 'browser_sessions', ['deleted_at'])

    # Create browser_contexts table
    op.create_table(
        'browser_contexts',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=sa.text('gen_random_uuid()')),
        sa.Column('context_id', sa.String(100), nullable=False, unique=True, index=True),
        sa.Column('session_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('browser_sessions.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('cookies', postgresql.JSONB, default=[], nullable=False),
        sa.Column('local_storage', postgresql.JSONB, default={}, nullable=False),
        sa.Column('session_storage', postgresql.JSONB, default={}, nullable=False),
        sa.Column('permissions', postgresql.JSONB, default=[], nullable=False),
        sa.Column('locale', sa.String(10), nullable=True),
        sa.Column('timezone_id', sa.String(50), nullable=True),
        sa.Column('viewport', postgresql.JSONB, nullable=True),
        sa.Column('user_agent', sa.Text, nullable=True),
        sa.Column('proxy', postgresql.JSONB, nullable=True),
        sa.Column('offline', sa.Boolean, default=False, nullable=False),
        sa.Column('storage_state', postgresql.JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )
    op.create_index('ix_browser_contexts_session_id', 'browser_contexts', ['session_id'])

    # Create browser_pages table
    op.create_table(
        'browser_pages',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=sa.text('gen_random_uuid()')),
        sa.Column('page_id', sa.String(100), nullable=False, unique=True, index=True),
        sa.Column('session_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('browser_sessions.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('context_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('browser_contexts.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('url', sa.Text, nullable=False),
        sa.Column('title', sa.String(500), nullable=True),
        sa.Column('status', browser_page_status_enum, default='CREATED', nullable=False),
        sa.Column('is_popup', sa.Boolean, default=False, nullable=False),
        sa.Column('opener_page_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('browser_pages.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('last_activity_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_browser_pages_session_id', 'browser_pages', ['session_id'])
    op.create_index('ix_browser_pages_context_id', 'browser_pages', ['context_id'])
    op.create_index('ix_browser_pages_opener_page_id', 'browser_pages', ['opener_page_id'])

    # Create browser_frames table
    op.create_table(
        'browser_frames',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=sa.text('gen_random_uuid()')),
        sa.Column('frame_id', sa.String(100), nullable=False, unique=True, index=True),
        sa.Column('page_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('browser_pages.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('parent_frame_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('browser_frames.id', ondelete='SET NULL'), nullable=True),
        sa.Column('url', sa.Text, nullable=False),
        sa.Column('name', sa.String(255), nullable=True),
        sa.Column('is_main_frame', sa.Boolean, default=False, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_browser_frames_page_id', 'browser_frames', ['page_id'])
    op.create_index('ix_browser_frames_parent_frame_id', 'browser_frames', ['parent_frame_id'])

    # Create browser_tasks table
    op.create_table(
        'browser_tasks',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=sa.text('gen_random_uuid()')),
        sa.Column('task_id', sa.String(100), nullable=False, unique=True, index=True),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('agent_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('agents.id', ondelete='SET NULL'), nullable=True, index=True),
        sa.Column('workflow_execution_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('workflow_executions.id', ondelete='SET NULL'), nullable=True, index=True),
        sa.Column('browser_session_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('browser_sessions.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('status', browser_task_status_enum, default='QUEUED', nullable=False, index=True),
        sa.Column('objective', sa.Text, nullable=False),
        sa.Column('current_url', sa.Text, nullable=True),
        sa.Column('current_page_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('browser_pages.id', ondelete='SET NULL'), nullable=True),
        sa.Column('current_step', sa.Integer, default=0, nullable=False),
        sa.Column('max_steps', sa.Integer, default=100, nullable=False),
        sa.Column('timeout', sa.Integer, default=300000, nullable=False),
        sa.Column('risk_policy', postgresql.JSONB, default={}, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('metadata', postgresql.JSONB, default={}, nullable=False),
    )
    op.create_index('ix_browser_tasks_organization_id', 'browser_tasks', ['organization_id'])
    op.create_index('ix_browser_tasks_agent_id', 'browser_tasks', ['agent_id'])
    op.create_index('ix_browser_tasks_workflow_execution_id', 'browser_tasks', ['workflow_execution_id'])
    op.create_index('ix_browser_tasks_browser_session_id', 'browser_tasks', ['browser_session_id'])
    op.create_index('ix_browser_tasks_status', 'browser_tasks', ['status'])

    # Create browser_actions table
    op.create_table(
        'browser_actions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=sa.text('gen_random_uuid()')),
        sa.Column('action_id', sa.String(100), nullable=False, unique=True, index=True),
        sa.Column('task_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('browser_tasks.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('session_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('browser_sessions.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('page_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('browser_pages.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('type', browser_action_type_enum, nullable=False),
        sa.Column('input', postgresql.JSONB, default={}, nullable=False),
        sa.Column('risk_level', browser_action_risk_level_enum, default='MEDIUM', nullable=False),
        sa.Column('status', sa.String(30), default='PENDING', nullable=False),
        sa.Column('result', postgresql.JSONB, nullable=True),
        sa.Column('error', postgresql.JSONB, nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('duration_ms', sa.Integer, default=0, nullable=False),
        sa.Column('retry_count', sa.Integer, default=0, nullable=False),
        sa.Column('idempotency_key', sa.String(100), nullable=True, index=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_browser_actions_task_id', 'browser_actions', ['task_id'])
    op.create_index('ix_browser_actions_session_id', 'browser_actions', ['session_id'])
    op.create_index('ix_browser_actions_page_id', 'browser_actions', ['page_id'])
    op.create_index('ix_browser_actions_type', 'browser_actions', ['type'])
    op.create_index('ix_browser_actions_status', 'browser_actions', ['status'])
    op.create_index('ix_browser_actions_idempotency_key', 'browser_actions', ['idempotency_key'])

    # Create browser_observations table
    op.create_table(
        'browser_observations',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=sa.text('gen_random_uuid()')),
        sa.Column('task_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('browser_tasks.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('action_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('browser_actions.id', ondelete='SET NULL'), nullable=True, index=True),
        sa.Column('url', sa.Text, nullable=False),
        sa.Column('title', sa.String(500), nullable=True),
        sa.Column('viewport', postgresql.JSONB, nullable=True),
        sa.Column('scroll_position', postgresql.JSONB, nullable=True),
        sa.Column('interactive_elements', postgresql.JSONB, default=[], nullable=False),
        sa.Column('text_content', sa.Text, nullable=True),
        sa.Column('dom_snapshot', sa.Text, nullable=True),
        sa.Column('screenshot_ref', sa.String(500), nullable=True),
        sa.Column('accessibility_tree', postgresql.JSONB, nullable=True),
        sa.Column('metadata', postgresql.JSONB, default={}, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_browser_observations_task_id', 'browser_observations', ['task_id'])
    op.create_index('ix_browser_observations_action_id', 'browser_observations', ['action_id'])

    # Create browser_artifacts table
    op.create_table(
        'browser_artifacts',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=sa.text('gen_random_uuid()')),
        sa.Column('artifact_id', sa.String(100), nullable=False, unique=True, index=True),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('task_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('browser_tasks.id', ondelete='SET NULL'), nullable=True, index=True),
        sa.Column('session_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('browser_sessions.id', ondelete='SET NULL'), nullable=True, index=True),
        sa.Column('type', browser_artifact_type_enum, nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('size', sa.BigInteger, nullable=False),
        sa.Column('mime_type', sa.String(100), nullable=False),
        sa.Column('storage_ref', sa.String(500), nullable=False),
        sa.Column('metadata', postgresql.JSONB, default={}, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True, index=True),
    )
    op.create_index('ix_browser_artifacts_organization_id', 'browser_artifacts', ['organization_id'])
    op.create_index('ix_browser_artifacts_task_id', 'browser_artifacts', ['task_id'])
    op.create_index('ix_browser_artifacts_session_id', 'browser_artifacts', ['session_id'])
    op.create_index('ix_browser_artifacts_type', 'browser_artifacts', ['type'])
    op.create_index('ix_browser_artifacts_expires_at', 'browser_artifacts', ['expires_at'])

    # Create browser_events table
    op.create_table(
        'browser_events',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=sa.text('gen_random_uuid()')),
        sa.Column('event_id', sa.String(100), nullable=False, unique=True, index=True),
        sa.Column('type', sa.String(100), nullable=False, index=True),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('session_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('browser_sessions.id', ondelete='SET NULL'), nullable=True, index=True),
        sa.Column('task_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('browser_tasks.id', ondelete='SET NULL'), nullable=True, index=True),
        sa.Column('page_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('browser_pages.id', ondelete='SET NULL'), nullable=True, index=True),
        sa.Column('payload', postgresql.JSONB, default={}, nullable=False),
        sa.Column('metadata', postgresql.JSONB, default={}, nullable=False),
        sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False, index=True),
    )
    op.create_index('ix_browser_events_organization_id', 'browser_events', ['organization_id'])
    op.create_index('ix_browser_events_session_id', 'browser_events', ['session_id'])
    op.create_index('ix_browser_events_task_id', 'browser_events', ['task_id'])
    op.create_index('ix_browser_events_type', 'browser_events', ['type'])
    op.create_index('ix_browser_events_timestamp', 'browser_events', ['timestamp'])

    # Create browser_domain_policies table
    op.create_table(
        'browser_domain_policies',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=sa.text('gen_random_uuid()')),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=True, index=True),
        sa.Column('team_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('teams.id', ondelete='CASCADE'), nullable=True, index=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=True, index=True),
        sa.Column('agent_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('agents.id', ondelete='CASCADE'), nullable=True, index=True),
        sa.Column('workflow_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('workflows.id', ondelete='CASCADE'), nullable=True, index=True),
        sa.Column('browser_profile_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('browser_profiles.id', ondelete='CASCADE'), nullable=True, index=True),
        sa.Column('task_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('browser_tasks.id', ondelete='CASCADE'), nullable=True, index=True),
        sa.Column('domain', sa.String(255), nullable=False, index=True),
        sa.Column('action', browser_domain_policy_action_enum, default='ALLOW', nullable=False),
        sa.Column('priority', sa.Integer, default=0, nullable=False),
        sa.Column('reason', sa.Text, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )
    op.create_index('ix_browser_domain_policies_organization_id', 'browser_domain_policies', ['organization_id'])
    op.create_index('ix_browser_domain_policies_domain', 'browser_domain_policies', ['domain'])
    op.create_index('ix_browser_domain_policies_priority', 'browser_domain_policies', ['priority'])

    # Create browser_session_leases table
    op.create_table(
        'browser_session_leases',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=sa.text('gen_random_uuid()')),
        sa.Column('lease_id', sa.String(100), nullable=False, unique=True, index=True),
        sa.Column('session_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('browser_sessions.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('holder_id', sa.String(100), nullable=False),
        sa.Column('holder_type', sa.String(20), nullable=False),  # agent, workflow, human
        sa.Column('acquired_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column('purpose', sa.String(255), nullable=False),
    )
    op.create_index('ix_browser_session_leases_session_id', 'browser_session_leases', ['session_id'])
    op.create_index('ix_browser_session_leases_expires_at', 'browser_session_leases', ['expires_at'])

    # Create browser_state_fingerprints table
    op.create_table(
        'browser_state_fingerprints',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=sa.text('gen_random_uuid()')),
        sa.Column('task_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('browser_tasks.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('url', sa.Text, nullable=False),
        sa.Column('title', sa.String(500), nullable=True),
        sa.Column('text_hash', sa.String(64), nullable=False),
        sa.Column('dom_hash', sa.String(64), nullable=False),
        sa.Column('interactive_elements_hash', sa.String(64), nullable=False),
        sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False, index=True),
    )
    op.create_index('ix_browser_state_fingerprints_task_id', 'browser_state_fingerprints', ['task_id'])
    op.create_index('ix_browser_state_fingerprints_timestamp', 'browser_state_fingerprints', ['timestamp'])


def downgrade() -> None:
    op.drop_table('browser_state_fingerprints')
    op.drop_table('browser_session_leases')
    op.drop_table('browser_domain_policies')
    op.drop_table('browser_events')
    op.drop_table('browser_artifacts')
    op.drop_table('browser_observations')
    op.drop_table('browser_actions')
    op.drop_table('browser_tasks')
    op.drop_table('browser_frames')
    op.drop_table('browser_pages')
    op.drop_table('browser_contexts')
    op.drop_table('browser_sessions')
    op.drop_table('browser_profiles')

    browser_state_fingerprint_enum = sa.Enum(name='browser_state_fingerprint')
    browser_state_fingerprint_enum.drop(op.get_bind(), checkfirst=True)

    browser_session_lease_enum = sa.Enum(name='browser_session_lease')
    browser_session_lease_enum.drop(op.get_bind(), checkfirst=True)

    browser_domain_policy_action_enum = sa.Enum(name='browser_domain_policy_action')
    browser_domain_policy_action_enum.drop(op.get_bind(), checkfirst=True)

    browser_challenge_type_enum = sa.Enum(name='browser_challenge_type')
    browser_challenge_type_enum.drop(op.get_bind(), checkfirst=True)

    browser_artifact_type_enum = sa.Enum(name='browser_artifact_type')
    browser_artifact_type_enum.drop(op.get_bind(), checkfirst=True)

    browser_task_status_enum = sa.Enum(name='browser_task_status')
    browser_task_status_enum.drop(op.get_bind(), checkfirst=True)

    browser_action_risk_level_enum = sa.Enum(name='browser_action_risk_level')
    browser_action_risk_level_enum.drop(op.get_bind(), checkfirst=True)

    browser_action_type_enum = sa.Enum(name='browser_action_type')
    browser_action_type_enum.drop(op.get_bind(), checkfirst=True)

    browser_page_status_enum = sa.Enum(name='browser_page_status')
    browser_page_status_enum.drop(op.get_bind(), checkfirst=True)

    browser_profile_type_enum = sa.Enum(name='browser_profile_type')
    browser_profile_type_enum.drop(op.get_bind(), checkfirst=True)

    browser_session_status_enum = sa.Enum(name='browser_session_status')
    browser_session_status_enum.drop(op.get_bind(), checkfirst=True)

    browser_type_enum = sa.Enum(name='browser_type')
    browser_type_enum.drop(op.get_bind(), checkfirst=True)

    browser_provider_type_enum = sa.Enum(name='browser_provider_type')
    browser_provider_type_enum.drop(op.get_bind(), checkfirst=True)