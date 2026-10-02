"""Add code agent + repository workspace tables (MP17)

Revision ID: 016_add_code_agent
Revises: 015_add_browser_automation
Create Date: 2026-09-28 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '016_add_code_agent'
down_revision = '015_add_browser_automation'
branch_labels = None
depends_on = None


def _uuid_pk():
    return sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                     server_default=sa.text('gen_random_uuid()'))


def _org_fk(nullable=False):
    return sa.Column('organization_id', postgresql.UUID(as_uuid=True),
                     sa.ForeignKey('organizations.id', ondelete='CASCADE'),
                     nullable=nullable)


def _ts(required=True):
    if required:
        return (sa.Column('created_at', sa.DateTime(timezone=True),
                          server_default=sa.func.now(), nullable=False),
                sa.Column('updated_at', sa.DateTime(timezone=True),
                          server_default=sa.func.now(), nullable=False))
    return (sa.Column('created_at', sa.DateTime(timezone=True),
                      server_default=sa.func.now(), nullable=False),)


def upgrade() -> None:
    repo_provider = sa.Enum('local', 'generic', 'github', 'gitlab', 'bitbucket',
                            name='repository_provider')
    repo_status = sa.Enum('connected', 'syncing', 'error', 'disconnected',
                          name='repository_status')
    ws_status = sa.Enum('CREATING', 'READY', 'BUSY', 'DIRTY', 'CHECKING', 'TESTING',
                        'COMMITTING', 'ERROR', 'CLEANING', 'DELETED',
                        name='workspace_status')
    task_status = sa.Enum('QUEUED', 'INITIALIZING', 'ANALYZING', 'PLANNING', 'EDITING',
                          'VALIDATING', 'TESTING', 'REVIEWING', 'WAITING_FOR_APPROVAL',
                          'COMMITTING', 'READY_FOR_PR', 'SUCCEEDED', 'FAILED',
                          'CANCELLED', 'TIMED_OUT', name='coding_task_status')
    risk_level = sa.Enum('LOW', 'MEDIUM', 'HIGH', 'CRITICAL', name='task_risk_level')
    exec_status = sa.Enum('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'TIMED_OUT',
                          'BLOCKED', 'CANCELLED', name='execution_status')
    review_status = sa.Enum('PENDING', 'PASSED', 'CHANGES_REQUESTED', 'BLOCKED',
                            name='review_status')
    review_severity = sa.Enum('INFO', 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL',
                              name='review_severity')
    patch_status = sa.Enum('PROPOSED', 'VALIDATED', 'APPLIED', 'REJECTED',
                           name='patch_status')
    pr_status = sa.Enum('DRAFT', 'READY', 'OPENED', 'MERGED', 'CLOSED',
                        name='pr_status')

    for enum in (repo_provider, repo_status, ws_status, task_status, risk_level,
                 exec_status, review_status, review_severity, patch_status, pr_status):
        enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        'repositories',
        _uuid_pk(), _org_fk(),
        sa.Column('provider', repo_provider, nullable=False, server_default='generic'),
        sa.Column('external_id', sa.String(255), nullable=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('full_name', sa.String(500), nullable=False),
        sa.Column('clone_url', sa.Text(), nullable=False),
        sa.Column('default_branch', sa.String(255), nullable=False, server_default='main'),
        sa.Column('visibility', sa.String(20), nullable=False, server_default='private'),
        sa.Column('status', repo_status, nullable=False, server_default='connected'),
        sa.Column('credential_ref', sa.String(255), nullable=True),
        sa.Column('provider_config', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('last_synced_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('metadata', postgresql.JSONB(), nullable=False, server_default='{}'),
        *_ts(),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_repositories_org', 'repositories', ['organization_id'])
    op.create_index('ix_repositories_external', 'repositories', ['external_id'])

    op.create_table(
        'code_tasks',
        _uuid_pk(), _org_fk(),
        sa.Column('task_id', sa.String(100), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('agent_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('agents.id', ondelete='SET NULL'), nullable=True),
        sa.Column('repository_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('repositories.id', ondelete='CASCADE'), nullable=False),
        sa.Column('workspace_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('code_workspaces.id', ondelete='SET NULL'), nullable=True),
        sa.Column('objective', sa.Text(), nullable=False),
        sa.Column('branch', sa.String(255), nullable=True),
        sa.Column('base_revision', sa.String(100), nullable=True),
        sa.Column('status', task_status, nullable=False, server_default='QUEUED'),
        sa.Column('risk_level', risk_level, nullable=False, server_default='MEDIUM'),
        sa.Column('max_steps', sa.Integer(), nullable=False, server_default='50'),
        sa.Column('max_duration_seconds', sa.Integer(), nullable=False, server_default='3600'),
        sa.Column('budgets', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('current_step', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('result', postgresql.JSONB(), nullable=True),
        sa.Column('metadata', postgresql.JSONB(), nullable=False, server_default='{}'),
        *_ts(),
    )
    op.create_index('ix_code_tasks_task_id', 'code_tasks', ['task_id'], unique=True)
    op.create_index('ix_code_tasks_org', 'code_tasks', ['organization_id'])
    op.create_index('ix_code_tasks_repo', 'code_tasks', ['repository_id'])
    op.create_index('ix_code_tasks_status', 'code_tasks', ['status'])

    op.create_table(
        'code_workspaces',
        _uuid_pk(), _org_fk(),
        sa.Column('workspace_id', sa.String(100), nullable=False),
        sa.Column('repository_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('repositories.id', ondelete='CASCADE'), nullable=False),
        sa.Column('task_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('branch', sa.String(255), nullable=False),
        sa.Column('base_revision', sa.String(100), nullable=True),
        sa.Column('current_revision', sa.String(100), nullable=True),
        sa.Column('filesystem_root', sa.Text(), nullable=False),
        sa.Column('status', ws_status, nullable=False, server_default='CREATING'),
        sa.Column('user_changes_snapshot', postgresql.JSONB(), nullable=False,
                  server_default='[]'),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('metadata', postgresql.JSONB(), nullable=False, server_default='{}'),
        *_ts(),
    )
    op.create_index('ix_code_workspaces_ws_id', 'code_workspaces', ['workspace_id'], unique=True)
    op.create_index('ix_code_workspaces_org', 'code_workspaces', ['organization_id'])
    op.create_index('ix_code_workspaces_repo', 'code_workspaces', ['repository_id'])
    op.create_index('ix_code_workspaces_status', 'code_workspaces', ['status'])
    # Deferred FK (breaks the tasks<->workspaces creation cycle).
    op.create_foreign_key('fk_code_workspaces_task', 'code_workspaces', 'code_tasks',
                          ['task_id'], ['id'], ondelete='SET NULL')

    op.create_table(
        'code_task_steps',
        _uuid_pk(),
        sa.Column('task_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('code_tasks.id', ondelete='CASCADE'), nullable=False),
        sa.Column('step_no', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(40), nullable=False),
        sa.Column('status', sa.String(30), nullable=False, server_default='PENDING'),
        sa.Column('input_summary', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('output_summary', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_code_task_steps_task', 'code_task_steps', ['task_id'])

    op.create_table(
        'code_file_index',
        _uuid_pk(),
        sa.Column('repository_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('repositories.id', ondelete='CASCADE'), nullable=False),
        sa.Column('path', sa.Text(), nullable=False),
        sa.Column('language', sa.String(30), nullable=True),
        sa.Column('size', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('sha256', sa.String(64), nullable=False),
        sa.Column('mtime_ns', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('indexed_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_code_file_index_repo', 'code_file_index', ['repository_id'])
    op.create_index('ix_code_file_index_repo_path', 'code_file_index',
                    ['repository_id', 'path'], unique=True)

    op.create_table(
        'code_symbols',
        _uuid_pk(),
        sa.Column('repository_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('repositories.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(500), nullable=False),
        sa.Column('kind', sa.String(30), nullable=False),
        sa.Column('file', sa.Text(), nullable=False),
        sa.Column('line_start', sa.Integer(), nullable=False),
        sa.Column('line_end', sa.Integer(), nullable=False),
        sa.Column('signature', sa.String(500), nullable=False, server_default=''),
        sa.Column('parent', sa.String(500), nullable=False, server_default=''),
    )
    op.create_index('ix_code_symbols_repo', 'code_symbols', ['repository_id'])
    op.create_index('ix_code_symbols_name', 'code_symbols', ['name'])

    op.create_table(
        'code_references',
        _uuid_pk(),
        sa.Column('repository_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('repositories.id', ondelete='CASCADE'), nullable=False),
        sa.Column('from_file', sa.Text(), nullable=False),
        sa.Column('from_symbol', sa.String(500), nullable=False, server_default=''),
        sa.Column('to_name', sa.String(500), nullable=False),
        sa.Column('kind', sa.String(30), nullable=False),
        sa.Column('line', sa.Integer(), nullable=False),
    )
    op.create_index('ix_code_references_repo', 'code_references', ['repository_id'])
    op.create_index('ix_code_references_to', 'code_references', ['to_name'])

    op.create_table(
        'code_dependencies',
        _uuid_pk(),
        sa.Column('repository_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('repositories.id', ondelete='CASCADE'), nullable=False),
        sa.Column('file', sa.Text(), nullable=False),
        sa.Column('manager', sa.String(40), nullable=False),
        sa.Column('name', sa.String(500), nullable=False),
        sa.Column('version_spec', sa.String(255), nullable=False, server_default=''),
        sa.Column('scope', sa.String(40), nullable=False, server_default='runtime'),
    )
    op.create_index('ix_code_dependencies_repo', 'code_dependencies', ['repository_id'])

    op.create_table(
        'code_chunks',
        _uuid_pk(),
        sa.Column('repository_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('repositories.id', ondelete='CASCADE'), nullable=False),
        sa.Column('file', sa.Text(), nullable=False),
        sa.Column('symbol', sa.String(500), nullable=False, server_default=''),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('line_start', sa.Integer(), nullable=False),
        sa.Column('line_end', sa.Integer(), nullable=False),
    )
    op.create_index('ix_code_chunks_repo', 'code_chunks', ['repository_id'])

    op.create_table(
        'code_embeddings',
        _uuid_pk(),
        sa.Column('repository_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('repositories.id', ondelete='CASCADE'), nullable=False),
        sa.Column('chunk_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('code_chunks.id', ondelete='CASCADE'), nullable=True),
        sa.Column('provider', sa.String(100), nullable=False, server_default='none'),
        sa.Column('dimensions', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('vector', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_code_embeddings_repo', 'code_embeddings', ['repository_id'])

    op.create_table(
        'code_execution_runs',
        _uuid_pk(), _org_fk(),
        sa.Column('task_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('code_tasks.id', ondelete='SET NULL'), nullable=True),
        sa.Column('profile', sa.String(30), nullable=False),
        sa.Column('command', sa.Text(), nullable=False),
        sa.Column('status', exec_status, nullable=False, server_default='QUEUED'),
        sa.Column('exit_code', sa.Integer(), nullable=True),
        sa.Column('duration_ms', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('stdout_ref', sa.String(500), nullable=True),
        sa.Column('stderr_ref', sa.String(500), nullable=True),
        sa.Column('stdout_tail', sa.Text(), nullable=False, server_default=''),
        sa.Column('diagnostics', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_code_execution_runs_org', 'code_execution_runs', ['organization_id'])
    op.create_index('ix_code_execution_runs_task', 'code_execution_runs', ['task_id'])

    op.create_table(
        'code_test_results',
        _uuid_pk(),
        sa.Column('execution_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('code_execution_runs.id', ondelete='CASCADE'), nullable=True),
        sa.Column('task_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('code_tasks.id', ondelete='SET NULL'), nullable=True),
        sa.Column('suite', sa.String(255), nullable=False, server_default=''),
        sa.Column('name', sa.String(500), nullable=False),
        sa.Column('file', sa.Text(), nullable=False, server_default=''),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('duration_ms', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('message', sa.Text(), nullable=False, server_default=''),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_code_test_results_exec', 'code_test_results', ['execution_id'])
    op.create_index('ix_code_test_results_task', 'code_test_results', ['task_id'])

    op.create_table(
        'code_reviews',
        _uuid_pk(), _org_fk(),
        sa.Column('task_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('code_tasks.id', ondelete='SET NULL'), nullable=True),
        sa.Column('repository_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('repositories.id', ondelete='SET NULL'), nullable=True),
        sa.Column('reviewer', sa.String(40), nullable=False, server_default='static'),
        sa.Column('status', review_status, nullable=False, server_default='PENDING'),
        sa.Column('summary', sa.Text(), nullable=False, server_default=''),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_code_reviews_org', 'code_reviews', ['organization_id'])

    op.create_table(
        'code_review_findings',
        _uuid_pk(),
        sa.Column('review_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('code_reviews.id', ondelete='CASCADE'), nullable=False),
        sa.Column('severity', review_severity, nullable=False, server_default='INFO'),
        sa.Column('file', sa.Text(), nullable=False),
        sa.Column('line', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('category', sa.String(40), nullable=False),
        sa.Column('finding', sa.Text(), nullable=False),
        sa.Column('evidence', sa.Text(), nullable=False, server_default=''),
        sa.Column('suggested_fix', sa.Text(), nullable=False, server_default=''),
    )
    op.create_index('ix_code_review_findings_review', 'code_review_findings', ['review_id'])

    op.create_table(
        'code_patches',
        _uuid_pk(), _org_fk(),
        sa.Column('task_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('code_tasks.id', ondelete='SET NULL'), nullable=True),
        sa.Column('files', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('diff_ref', sa.String(500), nullable=True),
        sa.Column('insertions', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('deletions', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('status', patch_status, nullable=False, server_default='PROPOSED'),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_code_patches_org', 'code_patches', ['organization_id'])

    op.create_table(
        'code_commits',
        _uuid_pk(),
        sa.Column('task_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('code_tasks.id', ondelete='SET NULL'), nullable=True),
        sa.Column('repository_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('repositories.id', ondelete='CASCADE'), nullable=False),
        sa.Column('sha', sa.String(100), nullable=False),
        sa.Column('branch', sa.String(255), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('files', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('validation', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_code_commits_repo', 'code_commits', ['repository_id'])
    op.create_index('ix_code_commits_sha', 'code_commits', ['sha'])

    op.create_table(
        'code_pull_requests',
        _uuid_pk(),
        sa.Column('task_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('code_tasks.id', ondelete='SET NULL'), nullable=True),
        sa.Column('repository_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('repositories.id', ondelete='CASCADE'), nullable=False),
        sa.Column('title', sa.String(500), nullable=False),
        sa.Column('summary', sa.Text(), nullable=False, server_default=''),
        sa.Column('branch', sa.String(255), nullable=False),
        sa.Column('base', sa.String(255), nullable=False),
        sa.Column('status', pr_status, nullable=False, server_default='DRAFT'),
        sa.Column('url', sa.Text(), nullable=True),
        sa.Column('metadata', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_code_pull_requests_repo', 'code_pull_requests', ['repository_id'])

    op.create_table(
        'code_index_jobs',
        _uuid_pk(),
        sa.Column('repository_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('repositories.id', ondelete='CASCADE'), nullable=False),
        sa.Column('status', sa.String(30), nullable=False, server_default='QUEUED'),
        sa.Column('files_indexed', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('symbols_indexed', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('error', sa.Text(), nullable=False, server_default=''),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_code_index_jobs_repo', 'code_index_jobs', ['repository_id'])
    op.create_index('ix_code_index_jobs_status', 'code_index_jobs', ['status'])

    op.create_table(
        'code_events',
        _uuid_pk(),
        sa.Column('event_id', sa.String(100), nullable=False),
        sa.Column('type', sa.String(100), nullable=False),
        _org_fk(),
        sa.Column('task_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('code_tasks.id', ondelete='SET NULL'), nullable=True),
        sa.Column('workspace_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('code_workspaces.id', ondelete='SET NULL'), nullable=True),
        sa.Column('payload', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('metadata', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('timestamp', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_code_events_event_id', 'code_events', ['event_id'], unique=True)
    op.create_index('ix_code_events_org', 'code_events', ['organization_id'])
    op.create_index('ix_code_events_task', 'code_events', ['task_id'])
    op.create_index('ix_code_events_type', 'code_events', ['type'])


def downgrade() -> None:
    for table in ('code_events', 'code_index_jobs', 'code_pull_requests',
                  'code_commits', 'code_patches', 'code_review_findings',
                  'code_reviews', 'code_test_results', 'code_execution_runs',
                  'code_embeddings', 'code_chunks', 'code_dependencies',
                  'code_references', 'code_symbols', 'code_file_index',
                  'code_task_steps', 'code_workspaces', 'code_tasks',
                  'repositories'):
        op.drop_table(table)
    for name in ('repository_provider', 'repository_status', 'workspace_status',
                 'coding_task_status', 'task_risk_level', 'execution_status',
                 'review_status', 'review_severity', 'patch_status', 'pr_status'):
        sa.Enum(name=name).drop(op.get_bind(), checkfirst=True)
