"""Add MP23 marketplace / publisher / review / distribution / commerce tables.

Revision ID: 022_add_marketplace
Revises: 021_add_packages
Create Date: 2026-09-30 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '022_add_marketplace'
down_revision = '021_add_packages'
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


_MKT_TYPE = ('PUBLIC_MARKETPLACE', 'ORGANIZATION_MARKETPLACE',
             'TEAM_MARKETPLACE', 'PRIVATE_MARKETPLACE', 'LOCAL_CATALOG')
_MKT_STATUS = ('ACTIVE', 'SUSPENDED', 'ARCHIVED')
_LISTING_STATUS = ('DRAFT', 'SUBMITTED', 'VALIDATING', 'UNDER_REVIEW',
                   'APPROVED', 'PUBLISHED', 'SUSPENDED', 'DEPRECATED',
                   'REVOKED', 'ARCHIVED', 'REJECTED')
_PUB_TYPE = ('INDIVIDUAL', 'ORGANIZATION', 'COMPANY', 'COMMUNITY',
             'OPENAGENT_OFFICIAL')
_VERIFY = ('UNVERIFIED', 'PENDING', 'VERIFIED', 'OFFICIAL', 'SUSPENDED',
           'REVOKED')
_REVIEW_STATUS = ('PUBLISHED', 'PENDING', 'FLAGGED', 'HIDDEN', 'REMOVED')
_ADV_SEV = ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')
_ADV_STATUS = ('AFFECTED', 'RESOLVED', 'REVOKED')
_PRICING = ('FREE', 'ONE_TIME', 'SUBSCRIPTION', 'USAGE_BASED', 'TIERED',
            'ENTERPRISE', 'CUSTOM')
_PRODUCT_TYPE = ('SINGLE_LISTING', 'BUNDLE', 'SUPPORT_PLAN', 'CUSTOM')
_PRODUCT_STATUS = ('DRAFT', 'ACTIVE', 'ARCHIVED')
_ENT_STATUS = ('ACTIVE', 'EXPIRED', 'REVOKED', 'TRIAL')
_REV_STATUS = ('PENDING', 'SETTLED', 'DISPUTED')
_PAYOUT_STATUS = ('PENDING', 'PROCESSING', 'PAID', 'FAILED', 'CANCELLED')
_REPORT_REASON = ('SPAM', 'ABUSE', 'HARASSMENT', 'FRAUD', 'IRRELEVANT',
                  'SENSITIVE_INFORMATION', 'MANIPULATION', 'COPYRIGHT',
                  'TRADEMARK', 'MALICIOUS', 'IMPERSONATION',
                  'POLICY_VIOLATION', 'OTHER')
_REPORT_STATE = ('OPEN', 'INVESTIGATING', 'ACTION_REQUIRED', 'RESOLVED',
                 'DISMISSED')
_MOD_ACTION = ('APPROVE', 'REJECT', 'SUSPEND', 'REVOKE', 'REQUEST_CHANGES',
               'FLAG_PUBLISHER', 'FLAG_PACKAGE', 'RESTORE', 'HIDE_REVIEW',
               'REMOVE_REVIEW', 'VERIFY_PUBLISHER', 'SUSPEND_PUBLISHER',
               'FEATURE', 'UNFEATURE')
_ANALYTICS = ('VIEW', 'SEARCH', 'CLICK', 'INSTALL_STARTED',
              'INSTALL_COMPLETED', 'INSTALL_FAILED', 'UPDATE', 'UNINSTALL',
              'FAVORITE', 'SHARE', 'REVIEW', 'REPORT')
_NOTIF = ('LISTING_APPROVED', 'LISTING_REJECTED', 'REVIEW_RECEIVED',
          'SECURITY_ISSUE', 'PACKAGE_REVOKED', 'UPDATE_PUBLISHED',
          'PAYOUT_EVENT', 'INSTALLED_UPDATE', 'SECURITY_ADVISORY',
          'REVOKED_PACKAGE', 'FOLLOWED_RELEASE', 'REVIEW_RESPONSE',
          'MODERATION_DECISION')
_ARTIFACT_TYPE = ('PACKAGE_ARCHIVE', 'MANIFEST', 'METADATA', 'SIGNATURE',
                  'INTEGRITY', 'DOCUMENTATION', 'ASSET')
_ARTIFACT_STATUS = ('PENDING', 'VERIFYING', 'VERIFIED', 'REJECTED',
                    'PUBLISHED')
_DIST_PROVIDER = ('LOCAL', 'OBJECT_STORAGE', 'CDN', 'REGISTRY',
                  'GITHUB_RELEASE', 'FUTURE_CLOUD')
_REGISTRY_KIND = ('OFFICIAL', 'COMMUNITY', 'PRIVATE', 'GIT', 'SELF_HOSTED',
                  'ENTERPRISE')


def upgrade() -> None:
    for name, values in (
        ("marketplace_type", _MKT_TYPE),
        ("marketplace_status", _MKT_STATUS),
        ("listing_status", _LISTING_STATUS),
        ("publisher_type", _PUB_TYPE),
        ("verification_status", _VERIFY),
        ("review_status", _REVIEW_STATUS),
        ("advisory_severity", _ADV_SEV),
        ("advisory_status", _ADV_STATUS),
        ("pricing_model", _PRICING),
        ("product_type", _PRODUCT_TYPE),
        ("product_status", _PRODUCT_STATUS),
        ("entitlement_status", _ENT_STATUS),
        ("revenue_status", _REV_STATUS),
        ("payout_status", _PAYOUT_STATUS),
        ("report_reason", _REPORT_REASON),
        ("report_state", _REPORT_STATE),
        ("moderation_action", _MOD_ACTION),
        ("analytics_event_type", _ANALYTICS),
        ("notification_type", _NOTIF),
        ("artifact_type", _ARTIFACT_TYPE),
        ("artifact_status", _ARTIFACT_STATUS),
        ("distribution_provider", _DIST_PROVIDER),
        ("registry_kind", _REGISTRY_KIND),
    ):
        op.execute(
            sa.text("DO $$ BEGIN CREATE TYPE %s AS ENUM (%s); "
                    "EXCEPTION WHEN duplicate_object THEN NULL; END $$;"
                    % (name, ", ".join(f"'{v}'" for v in values))))

    # --- MP23 extension columns on MP22 publisher_profiles ---
    for col, ddl in (
        ("slug", "VARCHAR(120) NOT NULL DEFAULT ''"),
        ("publisher_type", "VARCHAR(32) NOT NULL DEFAULT 'INDIVIDUAL'"),
        ("avatar", "VARCHAR(500) NOT NULL DEFAULT ''"),
        ("banner", "VARCHAR(500) NOT NULL DEFAULT ''"),
        ("description", "TEXT NOT NULL DEFAULT ''"),
        ("social_links", "JSON NOT NULL DEFAULT '{}'"),
        ("verification_status", "VARCHAR(32) NOT NULL DEFAULT 'UNVERIFIED'"),
        ("verified_at", "TIMESTAMPTZ NULL"),
        ("verified_by", "UUID NULL REFERENCES users(id) ON DELETE SET NULL"),
        ("trust_status", "VARCHAR(32) NOT NULL DEFAULT 'UNTRUSTED'"),
        ("suspended_reason", "TEXT NOT NULL DEFAULT ''"),
    ):
        op.execute(sa.text(
            f"ALTER TABLE publisher_profiles ADD COLUMN IF NOT EXISTS {col} {ddl}"))
    op.execute(sa.text(
        "UPDATE publisher_profiles SET slug = "
        "'publisher-' || substr(id::text, 1, 8) WHERE slug = ''"))
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_publisher_profiles_slug "
                       "ON publisher_profiles (slug)"))
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_publisher_profiles_verification "
                       "ON publisher_profiles (verification_status)"))

    op.create_table(
        'marketplaces', _uuid_pk(),
        sa.Column('slug', sa.String(100), nullable=False, unique=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('type', _enum('marketplace_type', _MKT_TYPE), nullable=False),
        sa.Column('owner_organization_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=True),
        sa.Column('visibility', sa.String(32), nullable=False, server_default='PUBLIC'),
        sa.Column('status', _enum('marketplace_status', _MKT_STATUS),
                  nullable=False, server_default='ACTIVE'),
        sa.Column('configuration', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('created_by', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        *_ts(),
    )
    op.create_index('ix_marketplaces_type', 'marketplaces', ['type'])
    op.create_index('ix_marketplaces_status', 'marketplaces', ['status'])
    op.create_index('ix_marketplaces_owner', 'marketplaces', ['owner_organization_id'])

    op.create_table(
        'marketplace_policies', _uuid_pk(),
        sa.Column('marketplace_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('marketplaces.id', ondelete='CASCADE'),
                  nullable=False, unique=True),
        sa.Column('name', sa.String(255), nullable=False, server_default=''),
        sa.Column('rules', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('updated_by', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        *_ts(),
    )

    op.create_table(
        'publisher_members', _uuid_pk(),
        sa.Column('publisher_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('publisher_profiles.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('role', sa.String(32), nullable=False, server_default='MEMBER'),
        *_ts(),
        sa.UniqueConstraint('publisher_id', 'user_id', name='uq_publisher_members'),
    )
    op.create_index('ix_publisher_members_user', 'publisher_members', ['user_id'])

    op.create_table(
        'publisher_followers', _uuid_pk(),
        sa.Column('publisher_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('publisher_profiles.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=True),
        *_ts(),
        sa.UniqueConstraint('publisher_id', 'user_id', name='uq_publisher_followers'),
    )
    op.create_index('ix_publisher_followers_publisher', 'publisher_followers',
                    ['publisher_id'])

    op.create_table(
        'marketplace_categories', _uuid_pk(),
        sa.Column('marketplace_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('marketplaces.id', ondelete='CASCADE'), nullable=True),
        sa.Column('parent_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('marketplace_categories.id', ondelete='CASCADE'),
                  nullable=True),
        sa.Column('slug', sa.String(100), nullable=False),
        sa.Column('name', sa.String(120), nullable=False),
        sa.Column('description', sa.Text(), nullable=False, server_default=''),
        sa.Column('position', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('official', sa.Boolean(), nullable=False, server_default='false'),
        *_ts(),
    )
    op.create_index('ix_marketplace_categories_parent', 'marketplace_categories',
                    ['parent_id'])
    op.create_index('ix_marketplace_categories_marketplace', 'marketplace_categories',
                    ['marketplace_id'])

    op.create_table(
        'marketplace_tags', _uuid_pk(),
        sa.Column('slug', sa.String(100), nullable=False, unique=True),
        sa.Column('name', sa.String(120), nullable=False),
        sa.Column('kind', sa.String(32), nullable=False, server_default='package'),
        sa.Column('usage_count', sa.Integer(), nullable=False, server_default='0'),
        *_ts(),
    )

    op.create_table(
        'marketplace_listings', _uuid_pk(),
        sa.Column('marketplace_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('marketplaces.id', ondelete='CASCADE'), nullable=False),
        sa.Column('package_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('reusable_packages.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('publisher_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('publisher_profiles.id', ondelete='RESTRICT'),
                  nullable=False),
        sa.Column('slug', sa.String(160), nullable=False),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('short_description', sa.String(500), nullable=False, server_default=''),
        sa.Column('full_description', sa.Text(), nullable=False, server_default=''),
        sa.Column('icon', sa.String(500), nullable=False, server_default=''),
        sa.Column('banner', sa.String(500), nullable=False, server_default=''),
        sa.Column('screenshots', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('videos', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('category', sa.String(100), nullable=False, server_default=''),
        sa.Column('license', sa.String(64), nullable=False, server_default=''),
        sa.Column('pricing_model', _enum('pricing_model', _PRICING),
                  nullable=False, server_default='FREE'),
        sa.Column('compatibility', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('requirements', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('trust_level', sa.String(32), nullable=False,
                  server_default='UNTRUSTED'),
        sa.Column('security_status', sa.String(16), nullable=False,
                  server_default='UNKNOWN'),
        sa.Column('published_version_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('package_versions.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('published_version', sa.String(32), nullable=False, server_default=''),
        sa.Column('status', _enum('listing_status', _LISTING_STATUS),
                  nullable=False, server_default='DRAFT'),
        sa.Column('status_reason', sa.Text(), nullable=False, server_default=''),
        sa.Column('badges', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('rating_average', sa.Float(), nullable=False, server_default='0'),
        sa.Column('rating_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('rating_distribution', sa.JSON(), nullable=False,
                  server_default='{}'),
        sa.Column('verified_review_count', sa.Integer(), nullable=False,
                  server_default='0'),
        sa.Column('install_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('successful_install_count', sa.Integer(), nullable=False,
                  server_default='0'),
        sa.Column('active_install_count', sa.Integer(), nullable=False,
                  server_default='0'),
        sa.Column('favorite_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('view_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_by', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        *_ts(),
        sa.UniqueConstraint('marketplace_id', 'slug',
                            name='uq_listings_marketplace_slug'),
    )
    for iname, cols in (
        ('ix_listings_package', ['package_id']),
        ('ix_listings_publisher', ['publisher_id']),
        ('ix_listings_status', ['status']),
        ('ix_listings_category', ['category']),
        ('ix_listings_rating', ['rating_average', 'rating_count']),
        ('ix_listings_installs', ['install_count']),
        ('ix_listings_updated', ['updated_at']),
        ('ix_listings_published', ['published_at']),
    ):
        op.create_index(iname, 'marketplace_listings', cols)

    op.create_table(
        'listing_tags', _uuid_pk(),
        sa.Column('listing_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('marketplace_listings.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('tag_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('marketplace_tags.id', ondelete='CASCADE'),
                  nullable=False),
        *_ts(),
        sa.UniqueConstraint('listing_id', 'tag_id', name='uq_listing_tags'),
    )

    op.create_table(
        'marketplace_listing_versions', _uuid_pk(),
        sa.Column('listing_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('marketplace_listings.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('version_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('package_versions.id', ondelete='RESTRICT'),
                  nullable=False),
        sa.Column('version', sa.String(32), nullable=False),
        sa.Column('changelog', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('is_current', sa.Boolean(), nullable=False, server_default='false'),
        *_ts(),
        sa.UniqueConstraint('listing_id', 'version_id', name='uq_listing_versions'),
    )
    op.create_index('ix_listing_versions_listing', 'marketplace_listing_versions',
                    ['listing_id'])

    op.create_table(
        'listing_reviews', _uuid_pk(),
        sa.Column('listing_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('marketplace_listings.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('version_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('package_versions.id', ondelete='SET NULL'),
                  nullable=False),
        sa.Column('installation_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('package_installations.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('reviewer_user_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('organizations.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('rating', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(255), nullable=False, server_default=''),
        sa.Column('body', sa.Text(), nullable=False, server_default=''),
        sa.Column('usage_context', sa.String(500), nullable=False, server_default=''),
        sa.Column('status', _enum('review_status', _REVIEW_STATUS),
                  nullable=False, server_default='PUBLISHED'),
        sa.Column('status_reason', sa.Text(), nullable=False, server_default=''),
        sa.Column('verified_use', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('helpful_count', sa.Integer(), nullable=False, server_default='0'),
        *_ts(),
        sa.UniqueConstraint('listing_id', 'reviewer_user_id', 'version_id',
                            name='uq_reviews_listing_user_version'),
    )
    op.create_index('ix_reviews_listing', 'listing_reviews', ['listing_id', 'status'])
    op.create_index('ix_reviews_reviewer', 'listing_reviews', ['reviewer_user_id'])

    op.create_table(
        'review_responses', _uuid_pk(),
        sa.Column('review_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('listing_reviews.id', ondelete='CASCADE'),
                  nullable=False, unique=True),
        sa.Column('responder_user_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('publisher_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('publisher_profiles.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('body', sa.Text(), nullable=False, server_default=''),
        *_ts(),
    )

    op.create_table(
        'review_reports', _uuid_pk(),
        sa.Column('review_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('listing_reviews.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('reporter_user_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('reason', _enum('report_reason', _REPORT_REASON), nullable=False),
        sa.Column('details', sa.Text(), nullable=False, server_default=''),
        sa.Column('status', _enum('report_state', _REPORT_STATE),
                  nullable=False, server_default='OPEN'),
        *_ts(),
    )

    op.create_table(
        'listing_favorites', _uuid_pk(),
        sa.Column('listing_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('marketplace_listings.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=True),
        *_ts(),
        sa.UniqueConstraint('listing_id', 'user_id', name='uq_listing_favorites'),
    )

    op.create_table(
        'marketplace_events', _uuid_pk(),
        sa.Column('marketplace_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('marketplaces.id', ondelete='CASCADE'), nullable=True),
        sa.Column('listing_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('marketplace_listings.id', ondelete='CASCADE'),
                  nullable=True),
        sa.Column('event_type', _enum('analytics_event_type', _ANALYTICS),
                  nullable=False),
        sa.Column('actor_user_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('organizations.id', ondelete='SET NULL'), nullable=True),
        sa.Column('event_metadata', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_marketplace_events_listing', 'marketplace_events',
                    ['listing_id', 'event_type', 'created_at'])

    op.create_table(
        'marketplace_analytics_daily', _uuid_pk(),
        sa.Column('listing_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('marketplace_listings.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('day', sa.Date(), nullable=False),
        sa.Column('views', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('clicks', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('installs_started', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('installs_completed', sa.Integer(), nullable=False,
                  server_default='0'),
        sa.Column('installs_failed', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('updates', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('uninstalls', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('favorites', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('shares', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('reviews', sa.Integer(), nullable=False, server_default='0'),
        *_ts(),
        sa.UniqueConstraint('listing_id', 'day', name='uq_analytics_listing_day'),
    )

    op.create_table(
        'security_advisories', _uuid_pk(),
        sa.Column('package_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('reusable_packages.id', ondelete='CASCADE'),
                  nullable=True),
        sa.Column('listing_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('marketplace_listings.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('publisher_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('publisher_profiles.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=False, server_default=''),
        sa.Column('affected_versions', sa.String(255), nullable=False, server_default=''),
        sa.Column('severity', _enum('advisory_severity', _ADV_SEV), nullable=False),
        sa.Column('status', _enum('advisory_status', _ADV_STATUS),
                  nullable=False, server_default='AFFECTED'),
        sa.Column('recommended_action', sa.Text(), nullable=False,
                  server_default='Update'),
        sa.Column('recommended_version', sa.String(32), nullable=False,
                  server_default=''),
        sa.Column('published_by', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
        *_ts(),
    )
    op.create_index('ix_advisories_package', 'security_advisories', ['package_id'])
    op.create_index('ix_advisories_status', 'security_advisories', ['status'])

    op.create_table(
        'package_revocations', _uuid_pk(),
        sa.Column('package_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('reusable_packages.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('version_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('package_versions.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('reason', sa.Text(), nullable=False, server_default=''),
        sa.Column('revoked_by', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('recommended_version', sa.String(32), nullable=False,
                  server_default=''),
        sa.Column('notify_issued', sa.Boolean(), nullable=False,
                  server_default='false'),
        *_ts(),
    )

    op.create_table(
        'distribution_artifacts', _uuid_pk(),
        sa.Column('version_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('package_versions.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('artifact_type', _enum('artifact_type', _ARTIFACT_TYPE),
                  nullable=False),
        sa.Column('storage_provider', _enum('distribution_provider', _DIST_PROVIDER),
                  nullable=False, server_default='LOCAL'),
        sa.Column('storage_key', sa.String(500), nullable=False),
        sa.Column('filename', sa.String(255), nullable=False),
        sa.Column('size_bytes', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('mime', sa.String(127), nullable=False,
                  server_default='application/zip'),
        sa.Column('sha256', sa.String(64), nullable=False),
        sa.Column('signature', sa.Text(), nullable=False, server_default=''),
        sa.Column('signature_status', sa.String(16), nullable=False,
                  server_default='UNKNOWN'),
        sa.Column('status', _enum('artifact_status', _ARTIFACT_STATUS),
                  nullable=False, server_default='PENDING'),
        sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('artifact_metadata', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('created_by', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        *_ts(),
    )
    op.create_index('ix_artifacts_version', 'distribution_artifacts',
                    ['version_id', 'artifact_type'])
    op.create_index('ix_artifacts_status', 'distribution_artifacts', ['status'])

    op.create_table(
        'distribution_locations', _uuid_pk(),
        sa.Column('artifact_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('distribution_artifacts.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('provider', _enum('distribution_provider', _DIST_PROVIDER),
                  nullable=False),
        sa.Column('url_or_ref', sa.String(1000), nullable=False),
        sa.Column('region', sa.String(64), nullable=False, server_default=''),
        sa.Column('is_primary', sa.Boolean(), nullable=False, server_default='false'),
        *_ts(),
    )

    op.create_table(
        'artifact_downloads', _uuid_pk(),
        sa.Column('artifact_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('distribution_artifacts.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('organizations.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('listing_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('marketplace_listings.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('bytes_served', sa.Integer(), nullable=False, server_default='0'),
        *_ts(),
    )

    op.create_table(
        'marketplace_reports', _uuid_pk(),
        sa.Column('marketplace_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('marketplaces.id', ondelete='CASCADE'), nullable=True),
        sa.Column('target_type', sa.String(32), nullable=False),
        sa.Column('target_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('target_slug', sa.String(255), nullable=False, server_default=''),
        sa.Column('reason', _enum('report_reason', _REPORT_REASON), nullable=False),
        sa.Column('details', sa.Text(), nullable=False, server_default=''),
        sa.Column('reporter_user_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('reporter_organization_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('organizations.id', ondelete='SET NULL'), nullable=True),
        sa.Column('status', _enum('report_state', _REPORT_STATE),
                  nullable=False, server_default='OPEN'),
        sa.Column('resolution', sa.JSON(), nullable=False, server_default='{}'),
        *_ts(),
    )

    op.create_table(
        'moderation_actions', _uuid_pk(),
        sa.Column('marketplace_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('marketplaces.id', ondelete='CASCADE'), nullable=True),
        sa.Column('target_type', sa.String(32), nullable=False),
        sa.Column('target_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('action', _enum('moderation_action', _MOD_ACTION), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False, server_default=''),
        sa.Column('moderator_user_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('action_metadata', sa.JSON(), nullable=False, server_default='{}'),
        *_ts(),
    )

    op.create_table(
        'marketplace_products', _uuid_pk(),
        sa.Column('listing_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('marketplace_listings.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('product_type', _enum('product_type', _PRODUCT_TYPE),
                  nullable=False),
        sa.Column('pricing_model', _enum('pricing_model', _PRICING),
                  nullable=False, server_default='FREE'),
        sa.Column('currency', sa.String(3), nullable=False, server_default='USD'),
        sa.Column('status', _enum('product_status', _PRODUCT_STATUS),
                  nullable=False, server_default='DRAFT'),
        sa.Column('product_metadata', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('created_by', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        *_ts(),
    )

    op.create_table(
        'marketplace_prices', _uuid_pk(),
        sa.Column('product_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('marketplace_products.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('amount_minor', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('currency', sa.String(3), nullable=False, server_default='USD'),
        sa.Column('interval', sa.String(16), nullable=False,
                  server_default='ONE_TIME'),
        sa.Column('tiers', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('status', _enum('product_status', _PRODUCT_STATUS),
                  nullable=False, server_default='DRAFT'),
        *_ts(),
    )

    op.create_table(
        'marketplace_entitlements', _uuid_pk(),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=True),
        sa.Column('product_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('marketplace_products.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('listing_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('marketplace_listings.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('status', _enum('entitlement_status', _ENT_STATUS),
                  nullable=False, server_default='ACTIVE'),
        sa.Column('valid_from', sa.DateTime(timezone=True), nullable=True),
        sa.Column('valid_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column('source', sa.String(64), nullable=False, server_default='manual'),
        sa.Column('entitlement_metadata', sa.JSON(), nullable=False,
                  server_default='{}'),
        *_ts(),
    )
    op.create_index('ix_entitlements_product_org', 'marketplace_entitlements',
                    ['product_id', 'organization_id'])
    op.create_index('ix_entitlements_status', 'marketplace_entitlements', ['status'])

    op.create_table(
        'marketplace_revenue', _uuid_pk(),
        sa.Column('publisher_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('publisher_profiles.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('product_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('marketplace_products.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('transaction_reference', sa.String(255), nullable=False,
                  server_default=''),
        sa.Column('gross_minor', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('fee_minor', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('net_minor', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('currency', sa.String(3), nullable=False, server_default='USD'),
        sa.Column('status', _enum('revenue_status', _REV_STATUS),
                  nullable=False, server_default='PENDING'),
        *_ts(),
    )

    op.create_table(
        'marketplace_payouts', _uuid_pk(),
        sa.Column('publisher_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('publisher_profiles.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('amount_minor', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('currency', sa.String(3), nullable=False, server_default='USD'),
        sa.Column('status', _enum('payout_status', _PAYOUT_STATUS),
                  nullable=False, server_default='PENDING'),
        sa.Column('provider_reference', sa.String(255), nullable=False,
                  server_default=''),
        sa.Column('payout_metadata', sa.JSON(), nullable=False, server_default='{}'),
        *_ts(),
    )

    op.create_table(
        'billing_webhook_events', _uuid_pk(),
        sa.Column('provider', sa.String(64), nullable=False),
        sa.Column('event_id', sa.String(255), nullable=False, unique=True),
        sa.Column('event_type', sa.String(128), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('signature_valid', sa.Boolean(), nullable=False,
                  server_default='false'),
        sa.Column('processed', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('idempotency_key', sa.String(255), nullable=False, unique=True),
        *_ts(),
    )

    op.create_table(
        'marketplace_notifications', _uuid_pk(),
        sa.Column('user_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=True),
        sa.Column('type', _enum('notification_type', _NOTIF), nullable=False),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('body', sa.Text(), nullable=False, server_default=''),
        sa.Column('listing_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('marketplace_listings.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('publisher_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('publisher_profiles.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('read', sa.Boolean(), nullable=False, server_default='false'),
        *_ts(),
    )
    op.create_index('ix_notifications_user_read', 'marketplace_notifications',
                    ['user_id', 'read'])

    op.create_table(
        'marketplace_notification_prefs', _uuid_pk(),
        sa.Column('user_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=True),
        sa.Column('prefs', sa.JSON(), nullable=False, server_default='{}'),
        *_ts(),
        sa.UniqueConstraint('user_id', 'organization_id',
                            name='uq_notification_prefs'),
    )

    op.create_table(
        'marketplace_registries', _uuid_pk(),
        sa.Column('slug', sa.String(100), nullable=False, unique=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('kind', _enum('registry_kind', _REGISTRY_KIND), nullable=False),
        sa.Column('url_or_ref', sa.String(1000), nullable=False, server_default=''),
        sa.Column('trust_level', sa.String(32), nullable=False,
                  server_default='UNTRUSTED'),
        sa.Column('is_public', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('verification_policy', sa.JSON(), nullable=False,
                  server_default='{}'),
        sa.Column('signature_policy', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('mirror_of', sa.String(100), nullable=False, server_default=''),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default='true'),
        *_ts(),
    )

    # --- RBAC: marketplace-domain permission resources ---
    for value in ('marketplace', 'publisher', 'review'):
        op.execute(
            sa.text(f"ALTER TYPE permission_resource ADD VALUE IF NOT EXISTS '{value}'"))
    _new_perms = (
        ('marketplace', 'read', 'View marketplaces and listings', 1),
        ('marketplace', 'create', 'Create marketplaces and listings', 2),
        ('marketplace', 'update', 'Update marketplaces and listings', 2),
        ('marketplace', 'delete', 'Delete marketplaces and listings', 3),
        ('marketplace', 'manage', 'Moderate listings, policies and featured content', 4),
        ('publisher', 'read', 'View publisher profiles', 1),
        ('publisher', 'create', 'Create publisher profiles', 2),
        ('publisher', 'update', 'Update publisher profiles', 2),
        ('publisher', 'delete', 'Delete publisher profiles', 3),
        ('publisher', 'manage', 'Verify, suspend and moderate publishers', 4),
        ('review', 'read', 'View reviews', 1),
        ('review', 'create', 'Write reviews', 1),
        ('review', 'update', 'Update own reviews and respond', 2),
        ('review', 'delete', 'Delete reviews', 3),
        ('review', 'manage', 'Moderate reviews and reports', 4),
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
        'organization_owner': ('marketplace:read', 'marketplace:create',
                               'marketplace:update', 'marketplace:delete',
                               'marketplace:manage', 'publisher:read',
                               'publisher:create', 'publisher:update',
                               'publisher:delete', 'publisher:manage',
                               'review:read', 'review:create', 'review:update',
                               'review:delete', 'review:manage'),
        'organization_admin': ('marketplace:read', 'marketplace:create',
                               'marketplace:update', 'marketplace:delete',
                               'marketplace:manage', 'publisher:read',
                               'publisher:create', 'publisher:update',
                               'publisher:delete', 'publisher:manage',
                               'review:read', 'review:create', 'review:update',
                               'review:delete', 'review:manage'),
        'developer': ('marketplace:read', 'marketplace:create',
                      'marketplace:update', 'publisher:read',
                      'publisher:create', 'publisher:update', 'review:read',
                      'review:create', 'review:update'),
        'operator': ('marketplace:read', 'publisher:read', 'review:read'),
        'member': ('marketplace:read', 'publisher:read', 'review:read',
                   'review:create'),
        'viewer': ('marketplace:read', 'publisher:read', 'review:read'),
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

    # --- Seed default public marketplace + policy + global categories ---
    op.execute(sa.text(
        "INSERT INTO marketplaces (id, slug, name, type, visibility, status, "
        "configuration) "
        "SELECT gen_random_uuid(), 'openagent-public', 'OpenAgent Marketplace', "
        "'PUBLIC_MARKETPLACE', 'PUBLIC', 'ACTIVE', '{}' "
        "WHERE NOT EXISTS (SELECT 1 FROM marketplaces WHERE slug = 'openagent-public')"
    ))
    op.execute(sa.text(
        "INSERT INTO marketplace_policies (id, marketplace_id, name, rules, is_active) "
        "SELECT gen_random_uuid(), m.id, 'Default public marketplace policy', "
        "'{\"require_security_scan\": true, \"maximum_risk_level\": \"HIGH\", "
        "\"review_required\": true, \"allowed_licenses\": "
        "[\"Apache-2.0\", \"MIT\", \"BSD-3-Clause\", \"MPL-2.0\", \"Unlicense\", "
        "\"CC-BY-4.0\", \"CC-BY-SA-4.0\", \"Proprietary\"]}'::json, true "
        "FROM marketplaces m WHERE m.slug = 'openagent-public' "
        "AND NOT EXISTS (SELECT 1 FROM marketplace_policies p "
        "WHERE p.marketplace_id = m.id)"
    ))
    _categories = (
        ("ai-agents", "AI Agents", None),
        ("ai-workforces", "AI Workforces", None),
        ("automation", "Automation", None),
        ("business", "Business", None),
        ("marketing", "Marketing", None),
        ("sales", "Sales", None),
        ("customer-support", "Customer Support", None),
        ("developer-tools", "Developer Tools", None),
        ("coding-agents", "Coding Agents", "developer-tools"),
        ("devops", "DevOps", "developer-tools"),
        ("git", "Git", "developer-tools"),
        ("testing", "Testing", "developer-tools"),
        ("database", "Database", "developer-tools"),
        ("coding", "Coding", None),
        ("research", "Research", None),
        ("data", "Data", None),
        ("productivity", "Productivity", None),
        ("content", "Content", None),
        ("seo", "SEO", None),
        ("social-media", "Social Media", None),
        ("browser-automation", "Browser Automation", None),
        ("security", "Security", None),
        ("education", "Education", None),
        ("finance", "Finance", None),
        ("operations", "Operations", None),
        ("personal-assistant", "Personal Assistant", None),
        ("enterprise", "Enterprise", None),
    )
    for position, (slug, name, _parent) in enumerate(_categories):
        op.execute(
            sa.text(
                "INSERT INTO marketplace_categories "
                "(id, slug, name, description, position, official) "
                "SELECT gen_random_uuid(), :slug, :name, '', :pos, true "
                "WHERE NOT EXISTS (SELECT 1 FROM marketplace_categories "
                "WHERE slug = :slug AND marketplace_id IS NULL)"
            ).bindparams(slug=slug, name=name, pos=position)
        )
    for slug, _name, parent in _categories:
        if parent:
            op.execute(
                sa.text(
                    "UPDATE marketplace_categories c SET parent_id = p.id "
                    "FROM marketplace_categories p "
                    "WHERE c.slug = :slug AND c.marketplace_id IS NULL "
                    "AND p.slug = :parent AND p.marketplace_id IS NULL "
                    "AND c.parent_id IS NULL"
                ).bindparams(slug=slug, parent=parent)
            )
    # Default local registry row (self-hosted, explicit trust required).
    op.execute(sa.text(
        "INSERT INTO marketplace_registries (id, slug, name, kind, trust_level, "
        "is_public, enabled) "
        "SELECT gen_random_uuid(), 'local', 'Local registry', 'SELF_HOSTED', "
        "'ORGANIZATION', false, true "
        "WHERE NOT EXISTS (SELECT 1 FROM marketplace_registries "
        "WHERE slug = 'local')"
    ))


def downgrade() -> None:
    for table in ('marketplace_registries', 'marketplace_notification_prefs',
                  'marketplace_notifications', 'billing_webhook_events',
                  'marketplace_payouts', 'marketplace_revenue',
                  'marketplace_entitlements', 'marketplace_prices',
                  'marketplace_products', 'moderation_actions',
                  'marketplace_reports', 'artifact_downloads',
                  'distribution_locations', 'distribution_artifacts',
                  'package_revocations', 'security_advisories',
                  'marketplace_analytics_daily', 'marketplace_events',
                  'listing_favorites', 'review_reports', 'review_responses',
                  'listing_reviews', 'marketplace_listing_versions',
                  'listing_tags', 'marketplace_listings', 'marketplace_tags',
                  'marketplace_categories', 'publisher_followers',
                  'publisher_members', 'marketplace_policies', 'marketplaces'):
        op.drop_table(table)
    op.execute(sa.text("ALTER TABLE publisher_profiles DROP COLUMN IF EXISTS slug"))
    op.execute(sa.text("ALTER TABLE publisher_profiles DROP COLUMN IF EXISTS publisher_type"))
    op.execute(sa.text("ALTER TABLE publisher_profiles DROP COLUMN IF EXISTS avatar"))
    op.execute(sa.text("ALTER TABLE publisher_profiles DROP COLUMN IF EXISTS banner"))
    op.execute(sa.text("ALTER TABLE publisher_profiles DROP COLUMN IF EXISTS description"))
    op.execute(sa.text("ALTER TABLE publisher_profiles DROP COLUMN IF EXISTS social_links"))
    op.execute(sa.text("ALTER TABLE publisher_profiles DROP COLUMN IF EXISTS verification_status"))
    op.execute(sa.text("ALTER TABLE publisher_profiles DROP COLUMN IF EXISTS verified_at"))
    op.execute(sa.text("ALTER TABLE publisher_profiles DROP COLUMN IF EXISTS verified_by"))
    op.execute(sa.text("ALTER TABLE publisher_profiles DROP COLUMN IF EXISTS trust_status"))
    op.execute(sa.text("ALTER TABLE publisher_profiles DROP COLUMN IF EXISTS suspended_reason"))
    # Enum types and RBAC rows are left in place (safe downgrade).
