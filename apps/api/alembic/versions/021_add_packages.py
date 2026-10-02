"""Add MP22 reusable package / skill / preset / installation tables.

Revision ID: 021_add_packages
Revises: 020_add_connectors
Create Date: 2026-09-30 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '021_add_packages'
down_revision = '020_add_connectors'
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


def _enum(name, values):
    return postgresql.ENUM(*values, name=name, create_type=False)


_PKG_TYPE = ('AGENT', 'AGENT_TEAM', 'WORKFORCE', 'WORKFLOW', 'SKILL',
             'PROMPT', 'TOOL_BUNDLE', 'CONNECTOR_BUNDLE', 'MODEL_PRESET',
             'AGENT_PRESET', 'WORKFLOW_PRESET', 'MEMORY_PRESET',
             'AUTOMATION_RECIPE', 'TEMPLATE_PACKAGE')
_VER_STATUS = ('DRAFT', 'VALIDATING', 'VALIDATED', 'PUBLISHED', 'DEPRECATED',
               'REVOKED', 'ARCHIVED')
_TRUST = ('CORE', 'VERIFIED', 'ORGANIZATION', 'COMMUNITY', 'UNTRUSTED')
_VIS = ('PRIVATE', 'TEAM', 'ORGANIZATION', 'PUBLIC', 'UNLISTED')
_INSTALL = ('REQUESTED', 'RESOLVING', 'VALIDATING', 'AWAITING_CONFIGURATION',
            'INSTALLING', 'VERIFYING', 'INSTALLED', 'FAILED', 'UPDATING',
            'ROLLING_BACK', 'ROLLED_BACK', 'UNINSTALLED')
_PRESET_KIND = ('MODEL_PRESET', 'AGENT_PRESET', 'WORKFLOW_PRESET',
                'MEMORY_PRESET')


def upgrade() -> None:
    for name, values in (
        ("reusable_package_type", _PKG_TYPE),
        ("package_version_status", _VER_STATUS),
        ("package_trust", _TRUST),
        ("package_visibility", _VIS),
        ("package_install_status", _INSTALL),
        ("preset_kind", _PRESET_KIND),
        ("skill_status", _VER_STATUS),
        ("skill_trust", _TRUST),
        ("skill_visibility", _VIS),
        ("skill_version_status", _VER_STATUS),
        ("preset_visibility", _VIS),
        ("preset_version_status", _VER_STATUS),
    ):
        op.execute(
            sa.text("DO $$ BEGIN CREATE TYPE %s AS ENUM (%s); "
                    "EXCEPTION WHEN duplicate_object THEN NULL; END $$;"
                    % (name, ", ".join(f"'{v}'" for v in values))))

    op.create_table(
        'reusable_packages', _uuid_pk(), _org_fk(nullable=True),
        sa.Column('slug', sa.String(160), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=False, server_default=''),
        sa.Column('package_type', _enum('reusable_package_type', _PKG_TYPE),
                  nullable=False),
        sa.Column('visibility', _enum('package_visibility', _VIS),
                  nullable=False, server_default='ORGANIZATION'),
        sa.Column('trust', _enum('package_trust', _TRUST),
                  nullable=False, server_default='UNTRUSTED'),
        sa.Column('official', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('license', sa.String(64), nullable=False, server_default='Apache-2.0'),
        sa.Column('author_name', sa.String(120), nullable=False, server_default=''),
        sa.Column('author_email', sa.String(255), nullable=False, server_default=''),
        sa.Column('publisher', sa.String(120), nullable=False, server_default=''),
        sa.Column('icon', sa.String(500), nullable=False, server_default=''),
        sa.Column('categories', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('tags', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('owner_user_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('team_ids', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('latest_version', sa.String(32), nullable=False, server_default=''),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        *_ts(),
        sa.UniqueConstraint('organization_id', 'slug',
                            name='uq_reusable_packages_org_slug'),
    )
    op.create_index('ix_reusable_packages_type', 'reusable_packages', ['package_type'])
    op.create_index('ix_reusable_packages_trust', 'reusable_packages', ['trust'])
    op.create_index('ix_reusable_packages_visibility', 'reusable_packages',
                    ['visibility'])
    op.create_index('ix_reusable_packages_official', 'reusable_packages', ['official'])

    op.create_table(
        'package_versions', _uuid_pk(),
        sa.Column('package_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('reusable_packages.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('version', sa.String(32), nullable=False),
        sa.Column('status', _enum('package_version_status', _VER_STATUS),
                  nullable=False, server_default='DRAFT'),
        sa.Column('manifest', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('content_hash', sa.String(64), nullable=False, server_default=''),
        sa.Column('risk', sa.String(16), nullable=False, server_default='LOW'),
        sa.Column('changelog', sa.Text(), nullable=False, server_default=''),
        sa.Column('created_by', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deprecated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_reason', sa.Text(), nullable=False, server_default=''),
        sa.Column('source_package_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('reusable_packages.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('source_version', sa.String(32), nullable=False, server_default=''),
        *_ts(),
        sa.UniqueConstraint('package_id', 'version',
                            name='uq_package_versions_package_version'),
    )
    op.create_index('ix_package_versions_status', 'package_versions', ['status'])

    op.create_table(
        'package_resources', _uuid_pk(),
        sa.Column('version_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('package_versions.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('kind', sa.String(64), nullable=False),
        sa.Column('slug', sa.String(160), nullable=False),
        sa.Column('name', sa.String(255), nullable=False, server_default=''),
        sa.Column('payload', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('content_hash', sa.String(64), nullable=False, server_default=''),
        *_ts(),
        sa.UniqueConstraint('version_id', 'kind', 'slug',
                            name='uq_package_resources_version_kind_slug'),
    )
    op.create_index('ix_package_resources_kind', 'package_resources', ['kind'])

    op.create_table(
        'package_dependencies', _uuid_pk(),
        sa.Column('version_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('package_versions.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('dep_type', sa.String(64), nullable=False),
        sa.Column('package', sa.String(160), nullable=False),
        sa.Column('constraint', sa.String(64), nullable=False, server_default='*'),
        sa.Column('optional', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('peer', sa.Boolean(), nullable=False, server_default='false'),
        *_ts(),
    )

    op.create_table(
        'skills', _uuid_pk(), _org_fk(nullable=True),
        sa.Column('slug', sa.String(160), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=False, server_default=''),
        sa.Column('status', _enum('skill_status', _VER_STATUS),
                  nullable=False, server_default='DRAFT'),
        sa.Column('trust', _enum('skill_trust', _TRUST),
                  nullable=False, server_default='UNTRUSTED'),
        sa.Column('visibility', _enum('skill_visibility', _VIS),
                  nullable=False, server_default='ORGANIZATION'),
        sa.Column('official', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('categories', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('tags', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('owner_user_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('latest_version', sa.String(32), nullable=False, server_default=''),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        *_ts(),
        sa.UniqueConstraint('organization_id', 'slug', name='uq_skills_org_slug'),
    )
    op.create_index('ix_skills_official', 'skills', ['official'])

    op.create_table(
        'skill_versions', _uuid_pk(),
        sa.Column('skill_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('skills.id', ondelete='CASCADE'), nullable=False),
        sa.Column('version', sa.String(32), nullable=False),
        sa.Column('status', _enum('skill_version_status', _VER_STATUS),
                  nullable=False, server_default='DRAFT'),
        sa.Column('instructions', sa.Text(), nullable=False, server_default=''),
        sa.Column('input_schema', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('output_schema', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('required_tools', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('required_connectors', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('model_requirements', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('memory_requirements', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('security_requirements', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('evaluation_criteria', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('content_hash', sa.String(64), nullable=False, server_default=''),
        sa.Column('created_by', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
        *_ts(),
        sa.UniqueConstraint('skill_id', 'version',
                            name='uq_skill_versions_skill_version'),
    )

    op.create_table(
        'presets', _uuid_pk(), _org_fk(nullable=True),
        sa.Column('slug', sa.String(160), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('kind', _enum('preset_kind', _PRESET_KIND), nullable=False),
        sa.Column('description', sa.Text(), nullable=False, server_default=''),
        sa.Column('visibility', _enum('preset_visibility', _VIS),
                  nullable=False, server_default='ORGANIZATION'),
        sa.Column('official', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('latest_version', sa.String(32), nullable=False, server_default=''),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        *_ts(),
        sa.UniqueConstraint('organization_id', 'slug', name='uq_presets_org_slug'),
    )
    op.create_index('ix_presets_kind', 'presets', ['kind'])

    op.create_table(
        'preset_versions', _uuid_pk(),
        sa.Column('preset_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('presets.id', ondelete='CASCADE'), nullable=False),
        sa.Column('version', sa.String(32), nullable=False),
        sa.Column('status', _enum('preset_version_status', _VER_STATUS),
                  nullable=False, server_default='DRAFT'),
        sa.Column('payload', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('content_hash', sa.String(64), nullable=False, server_default=''),
        sa.Column('created_by', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
        *_ts(),
        sa.UniqueConstraint('preset_id', 'version',
                            name='uq_preset_versions_preset_version'),
    )

    op.create_table(
        'package_installations', _uuid_pk(), _org_fk(nullable=False),
        sa.Column('package_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('reusable_packages.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('version_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('package_versions.id', ondelete='RESTRICT'),
                  nullable=False),
        sa.Column('status', _enum('package_install_status', _INSTALL),
                  nullable=False, server_default='REQUESTED'),
        sa.Column('configuration', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('resolved_dependencies', sa.JSON(), nullable=False,
                  server_default='[]'),
        sa.Column('idempotency_key', sa.String(100), nullable=False, server_default=''),
        sa.Column('installed_by', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('error', sa.Text(), nullable=False, server_default=''),
        sa.Column('previous_version_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('package_versions.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('update_available', sa.String(32), nullable=False, server_default=''),
        sa.Column('installed_at', sa.DateTime(timezone=True), nullable=True),
        *_ts(),
        sa.UniqueConstraint('organization_id', 'idempotency_key',
                            name='uq_installations_org_idempotency'),
    )
    op.create_index('ix_installations_org_package', 'package_installations',
                    ['organization_id', 'package_id'])
    op.create_index('ix_installations_status', 'package_installations', ['status'])

    op.create_table(
        'installation_resources', _uuid_pk(),
        sa.Column('installation_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('package_installations.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('kind', sa.String(64), nullable=False),
        sa.Column('slug', sa.String(160), nullable=False),
        sa.Column('name', sa.String(255), nullable=False, server_default=''),
        sa.Column('local_ref_type', sa.String(64), nullable=False, server_default=''),
        sa.Column('local_ref_id', sa.String(100), nullable=False, server_default=''),
        sa.Column('snapshot', sa.JSON(), nullable=False, server_default='{}'),
        *_ts(),
    )
    op.create_index('ix_installation_resources_kind', 'installation_resources',
                    ['installation_id', 'kind'])

    op.create_table(
        'package_signatures', _uuid_pk(),
        sa.Column('version_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('package_versions.id', ondelete='CASCADE'),
                  nullable=False, unique=True),
        sa.Column('algorithm', sa.String(32), nullable=False),
        sa.Column('signature', sa.Text(), nullable=False),
        sa.Column('key_id', sa.String(120), nullable=False, server_default=''),
        sa.Column('signer', sa.String(255), nullable=False, server_default=''),
        sa.Column('verified', sa.Boolean(), nullable=False, server_default='false'),
        *_ts(),
    )

    op.create_table(
        'package_security_scans', _uuid_pk(),
        sa.Column('version_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('package_versions.id', ondelete='CASCADE'),
                  nullable=True),
        sa.Column('installation_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('package_installations.id', ondelete='CASCADE'),
                  nullable=True),
        sa.Column('risk', sa.String(16), nullable=False, server_default='LOW'),
        sa.Column('findings', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('scanner_version', sa.String(16), nullable=False, server_default='1'),
        *_ts(),
    )

    op.create_table(
        'package_validation_results', _uuid_pk(),
        sa.Column('version_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('package_versions.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('passed', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('findings', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('stages', sa.JSON(), nullable=False, server_default='{}'),
        *_ts(),
    )

    op.create_table(
        'package_forks', _uuid_pk(),
        sa.Column('package_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('reusable_packages.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('parent_package_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('reusable_packages.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('parent_version', sa.String(32), nullable=False, server_default=''),
        sa.Column('forked_by', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        *_ts(),
    )

    op.create_table(
        'package_update_plans', _uuid_pk(),
        sa.Column('installation_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('package_installations.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('from_version_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('package_versions.id', ondelete='RESTRICT'),
                  nullable=False),
        sa.Column('to_version_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('package_versions.id', ondelete='RESTRICT'),
                  nullable=False),
        sa.Column('breaking', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('impact', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('migration_steps', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('status', sa.String(32), nullable=False, server_default='PENDING'),
        sa.Column('approved_by', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        *_ts(),
    )

    op.create_table(
        'package_categories', _uuid_pk(), _org_fk(nullable=True),
        sa.Column('slug', sa.String(100), nullable=False),
        sa.Column('name', sa.String(120), nullable=False),
        sa.Column('description', sa.Text(), nullable=False, server_default=''),
        sa.Column('official', sa.Boolean(), nullable=False, server_default='false'),
        *_ts(),
        sa.UniqueConstraint('organization_id', 'slug',
                            name='uq_package_categories_org_slug'),
    )

    op.create_table(
        'publisher_profiles', _uuid_pk(), _org_fk(nullable=True),        sa.Column('user_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=True),
        sa.Column('display_name', sa.String(120), nullable=False),
        sa.Column('website', sa.String(500), nullable=False, server_default=''),
        sa.Column('verified', sa.Boolean(), nullable=False, server_default='false'),
        *_ts(),
    )

    # RBAC: extend permission_resource with package-domain resources and seed
    # the new system permissions + grants onto existing system roles.
    # Idempotent: safe to re-run and safe on fresh installs (seed_rbac runs
    # from the same SYSTEM_PERMISSIONS source afterwards).
    for value in ('package', 'skill', 'preset'):
        op.execute(
            sa.text(f"ALTER TYPE permission_resource ADD VALUE IF NOT EXISTS '{value}'"))
    _new_perms = (
        ('package', 'read', 'View reusable packages and catalog', 1),
        ('package', 'create', 'Create packages and versions', 2),
        ('package', 'update', 'Update packages and versions', 2),
        ('package', 'delete', 'Delete packages', 3),
        ('package', 'execute', 'Install, update and roll back packages', 2),
        ('package', 'manage', 'Publish, revoke and verify packages', 4),
        ('skill', 'read', 'View skills', 1),
        ('skill', 'create', 'Create skills', 2),
        ('skill', 'update', 'Update skills', 2),
        ('skill', 'delete', 'Delete skills', 3),
        ('preset', 'read', 'View presets', 1),
        ('preset', 'create', 'Create presets', 2),
        ('preset', 'update', 'Update presets', 2),
        ('preset', 'delete', 'Delete presets', 3),
    )
    for resource, action, desc, danger in _new_perms:
        op.execute(
            sa.text(
                "INSERT INTO permissions "
                "(id, name, resource, action, scope, description, "
                "is_system, danger_level, metadata, created_at, updated_at) "
                "SELECT gen_random_uuid(), :name, :resource::permission_resource, "
                ":action::permission_action, 'organization', :desc, true, :danger, "
                "'{}', now(), now() "
                "WHERE NOT EXISTS (SELECT 1 FROM permissions WHERE name = :name)"
            ).bindparams(name=f"{resource}:{action}", resource=resource,
                         action=action, desc=desc, danger=danger))
    _grants = {
        'organization_owner': ('package:read', 'package:create', 'package:update',
                               'package:delete', 'package:execute', 'package:manage',
                               'skill:read', 'skill:create', 'skill:update',
                               'skill:delete', 'preset:read', 'preset:create',
                               'preset:update', 'preset:delete'),
        'organization_admin': ('package:read', 'package:create', 'package:update',
                               'package:delete', 'package:execute', 'package:manage',
                               'skill:read', 'skill:create', 'skill:update',
                               'skill:delete', 'preset:read', 'preset:create',
                               'preset:update', 'preset:delete'),
        'developer': ('package:read', 'package:create', 'package:update',
                      'package:execute', 'skill:read', 'skill:create',
                      'skill:update', 'preset:read', 'preset:create',
                      'preset:update'),
        'operator': ('package:read', 'package:execute', 'skill:read',
                     'preset:read'),
        'member': ('package:read', 'package:execute', 'skill:read',
                   'preset:read'),
        'viewer': ('package:read', 'skill:read', 'preset:read'),
    }
    for role_name, perms in _grants.items():
        for perm_name in perms:
            op.execute(
                sa.text(
                    "INSERT INTO role_permissions "
                    "(id, role_id, permission_id, created_at, updated_at) "
                    "SELECT gen_random_uuid(), r.id, p.id, now(), now() "
                    "FROM roles r JOIN permissions p ON p.name = :perm "
                    "WHERE r.name = :role AND r.organization_id IS NULL "
                    "AND NOT EXISTS (SELECT 1 FROM role_permissions rp "
                    "WHERE rp.role_id = r.id AND rp.permission_id = p.id)"
                ).bindparams(role=role_name, perm=perm_name))

    # Seed official categories (idempotent; mirrors
    # openagent.packages.types.STANDARD_CATEGORIES without importing app code).
    for name in (
        "AI & Agents", "Automation", "Business", "Marketing", "Sales",
        "Customer Support", "Developer Tools", "Coding", "Research", "Data",
        "Productivity", "Finance", "Operations", "Content", "SEO",
        "Social Media", "Browser Automation", "DevOps", "Security",
        "Education", "Personal Assistant", "Enterprise",
    ):
        op.execute(
            sa.text(
                "INSERT INTO package_categories "
                "(id, slug, name, description, official) "
                "SELECT gen_random_uuid(), :slug, :name, '', true "
                "WHERE NOT EXISTS "
                "(SELECT 1 FROM package_categories WHERE slug = :slug "
                "AND organization_id IS NULL)"
            ).bindparams(slug=name.lower().replace(' & ', '-').replace(' ', '-'),
                         name=name)
        )


def downgrade() -> None:
    for table in ('publisher_profiles', 'package_categories',
                  'package_update_plans', 'package_forks',
                  'package_validation_results', 'package_security_scans',
                  'package_signatures', 'installation_resources',
                  'package_installations', 'preset_versions', 'presets',
                  'skill_versions', 'skills', 'package_dependencies',
                  'package_resources', 'package_versions',
                  'reusable_packages'):
        op.drop_table(table)
    # Enum types are left in place (safe downgrade).
