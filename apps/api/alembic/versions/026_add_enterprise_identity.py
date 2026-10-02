"""Add MP27 enterprise identity tables (additive only, reversible).

Revision ID: 026_add_enterprise_identity
Revises: 025_add_control_plane
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '026_add_enterprise_identity'
down_revision = '025_add_control_plane'
branch_labels = None
depends_on = None


def _uuid_pk():
    return sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                     server_default=sa.text('gen_random_uuid()'))


def _ts():
    return (sa.Column('created_at', sa.DateTime(timezone=True),
                      server_default=sa.func.now(), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True),
                      server_default=sa.func.now(), nullable=False))


def _org_fk(nullable=False):
    return sa.Column('organization_id', postgresql.UUID(as_uuid=True),
                     sa.ForeignKey('organizations.id', ondelete='CASCADE'),
                     nullable=nullable)


TABLES = (
    "identity_providers", "identity_provider_domains", "sso_sessions",
    "scim_credentials", "scim_sync_runs", "identity_group_mappings",
    "devices", "authentication_events", "session_risk_events",
    "workload_identities", "credential_leases", "security_policies",
    "security_policy_versions", "policy_decisions",
    "data_classification_rules", "security_controls", "control_evidence",
    "security_alerts",
)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.create_table(
        "identity_providers", _uuid_pk(), *(_ts()),
        _org_fk(),
        sa.Column('provider_type', sa.String(16), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('issuer', sa.String(1024), nullable=False, server_default=''),
        sa.Column('client_id', sa.String(512), nullable=False, server_default=''),
        sa.Column('client_secret_ref', sa.String(512), nullable=False, server_default=''),
        sa.Column('metadata_url', sa.String(1024), nullable=False, server_default=''),
        sa.Column('certificate_ref', sa.String(512), nullable=False, server_default=''),
        sa.Column('attribute_mapping', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('status', sa.String(16), nullable=False, server_default='DRAFT'),
        sa.Column('enforce_mfa', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_by', sa.String(255), nullable=False, server_default=''),
    )
    op.create_index("ix_identity_providers_org", "identity_providers",
                    ["organization_id"])
    op.create_index("ix_identity_providers_status", "identity_providers",
                    ["status"])

    op.create_table(
        "identity_provider_domains", _uuid_pk(), *(_ts()),
        sa.Column('provider_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('identity_providers.id', ondelete='CASCADE'),
                  nullable=False),
        _org_fk(),
        sa.Column('domain', sa.String(255), nullable=False),
        sa.Column('status', sa.String(16), nullable=False, server_default='PENDING'),
        sa.Column('method', sa.String(16), nullable=False, server_default='dns_txt'),
        sa.Column('challenge_hash', sa.String(128), nullable=False, server_default=''),
        sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_idp_domains_domain", "identity_provider_domains",
                    ["domain"])
    op.create_index("ix_idp_domains_org_status", "identity_provider_domains",
                    ["organization_id", "status"])

    op.create_table(
        "sso_sessions", _uuid_pk(), *(_ts()),
        sa.Column('provider_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('identity_providers.id', ondelete='CASCADE'),
                  nullable=False),
        _org_fk(),
        sa.Column('user_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('subject', sa.String(512), nullable=False),
        sa.Column('request_id', sa.String(128), nullable=False, server_default=''),
        sa.Column('auth_strength', sa.String(8), nullable=False, server_default='AAL1'),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_sso_sessions_provider", "sso_sessions",
                    ["provider_id"])
    op.create_index("ix_sso_sessions_request", "sso_sessions",
                    ["request_id"])

    op.create_table(
        "scim_credentials", _uuid_pk(), *(_ts()),
        _org_fk(),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('token_hash', sa.String(128), nullable=False),
        sa.Column('prefix', sa.String(20), nullable=False, server_default=''),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('revoked', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by', sa.String(255), nullable=False, server_default=''),
        sa.UniqueConstraint('token_hash', name='uq_scim_credentials_token'),
    )
    op.create_index("ix_scim_credentials_org", "scim_credentials",
                    ["organization_id"])

    op.create_table(
        "scim_sync_runs", _uuid_pk(), *(_ts()),
        _org_fk(),
        sa.Column('credential_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('scim_credentials.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('users_created', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('users_updated', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('users_deactivated', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('groups_synced', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('status', sa.String(32), nullable=False, server_default='completed'),
        sa.Column('error', sa.Text(), nullable=False, server_default=''),
    )

    op.create_table(
        "identity_group_mappings", _uuid_pk(), *(_ts()),
        _org_fk(),
        sa.Column('provider_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('identity_providers.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('external_group', sa.String(512), nullable=False),
        sa.Column('team_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('teams.id', ondelete='SET NULL'), nullable=True),
        sa.Column('role', sa.String(64), nullable=False, server_default='member'),
        sa.Column('created_by', sa.String(255), nullable=False, server_default=''),
    )
    op.create_index("ix_group_mappings_org_group",
                    "identity_group_mappings",
                    ["organization_id", "external_group"])

    op.create_table(
        "devices", _uuid_pk(), *(_ts()),
        sa.Column('user_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('device_key', sa.String(128), nullable=False),
        sa.Column('type', sa.String(32), nullable=False, server_default='unknown'),
        sa.Column('platform', sa.String(64), nullable=False, server_default=''),
        sa.Column('browser', sa.String(64), nullable=False, server_default=''),
        sa.Column('trust', sa.String(16), nullable=False, server_default='UNKNOWN'),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_devices_user", "devices", ["user_id"])
    op.create_index("ix_devices_user_key", "devices", ["user_id", "device_key"])

    op.create_table(
        "authentication_events", _uuid_pk(), *(_ts()),
        sa.Column('user_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('organizations.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('method', sa.String(32), nullable=False),
        sa.Column('result', sa.String(16), nullable=False),
        sa.Column('ip_address', sa.String(45), nullable=True),
        sa.Column('device_key', sa.String(128), nullable=False, server_default=''),
        sa.Column('auth_strength', sa.String(8), nullable=False, server_default='AAL1'),
        sa.Column('detail', sa.String(1024), nullable=False, server_default=''),
        sa.Column('request_id', sa.String(64), nullable=False, server_default=''),
    )
    op.create_index("ix_auth_events_method", "authentication_events",
                    ["method"])
    op.create_index("ix_auth_events_user_created", "authentication_events",
                    ["user_id", "created_at"])
    op.create_index("ix_auth_events_org_created", "authentication_events",
                    ["organization_id", "created_at"])

    op.create_table(
        "session_risk_events", _uuid_pk(), *(_ts()),
        sa.Column('session_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('sessions.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('score', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('level', sa.String(16), nullable=False),
        sa.Column('signals', postgresql.JSONB(), nullable=False, server_default='[]'),
    )
    op.create_index("ix_session_risk_session", "session_risk_events",
                    ["session_id"])

    op.create_table(
        "workload_identities", _uuid_pk(), *(_ts()),
        sa.Column('kind', sa.String(32), nullable=False),
        _org_fk(),
        sa.Column('execution_id', sa.String(64), nullable=False, server_default=''),
        sa.Column('region', sa.String(100), nullable=False, server_default=''),
        sa.Column('pool', sa.String(100), nullable=False, server_default=''),
        sa.Column('scopes', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('revoked', sa.Boolean(), nullable=False, server_default='false'),
    )
    op.create_index("ix_workload_kind", "workload_identities", ["kind"])
    op.create_index("ix_workload_execution", "workload_identities",
                    ["execution_id"])

    op.create_table(
        "credential_leases", _uuid_pk(), *(_ts()),
        sa.Column('workload_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('workload_identities.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('credential_ref', sa.String(512), nullable=False),
        sa.Column('scopes', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('uses', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('max_uses', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('revoked', sa.Boolean(), nullable=False, server_default='false'),
    )
    op.create_index("ix_credential_leases_workload", "credential_leases",
                    ["workload_id"])

    op.create_table(
        "security_policies", _uuid_pk(), *(_ts()),
        sa.Column('scope', sa.String(32), nullable=False),
        sa.Column('scope_id', sa.String(128), nullable=False, server_default=''),
        sa.Column('sections', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_by', sa.String(255), nullable=False, server_default=''),
        sa.Column('reason', sa.Text(), nullable=False, server_default=''),
    )
    op.create_index("ix_security_policies_scope", "security_policies",
                    ["scope", "scope_id"])

    op.create_table(
        "security_policy_versions", _uuid_pk(), *(_ts()),
        sa.Column('policy_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('security_policies.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('sections', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('changed_by', sa.String(255), nullable=False, server_default=''),
        sa.Column('reason', sa.Text(), nullable=False, server_default=''),
        sa.Column('result', sa.String(32), nullable=False, server_default='applied'),
    )
    op.create_index("ix_policy_versions_policy", "security_policy_versions",
                    ["policy_id", "version"])

    op.create_table(
        "policy_decisions", _uuid_pk(), *(_ts()),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('organizations.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('actor', sa.String(255), nullable=False, server_default=''),
        sa.Column('action', sa.String(255), nullable=False),
        sa.Column('resource', sa.String(512), nullable=False, server_default=''),
        sa.Column('verdict', sa.String(16), nullable=False),
        sa.Column('explanation', sa.Text(), nullable=False, server_default=''),
        sa.Column('policy_id', sa.String(128), nullable=False, server_default=''),
        sa.Column('request_id', sa.String(64), nullable=False, server_default=''),
    )
    op.create_index("ix_policy_decisions_action", "policy_decisions",
                    ["action"])
    op.create_index("ix_policy_decisions_org_created", "policy_decisions",
                    ["organization_id", "created_at"])

    op.create_table(
        "data_classification_rules", _uuid_pk(), *(_ts()),
        _org_fk(),
        sa.Column('rule_id', sa.String(128), nullable=False),
        sa.Column('classification', sa.String(16), nullable=False),
        sa.Column('pattern', sa.Text(), nullable=False, server_default=''),
        sa.Column('action', sa.String(16), nullable=False, server_default='redact'),
        sa.Column('created_by', sa.String(255), nullable=False, server_default=''),
    )
    op.create_index("ix_data_rules_org_rule",
                    "data_classification_rules",
                    ["organization_id", "rule_id"])

    op.create_table(
        "security_controls", _uuid_pk(), *(_ts()),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('organizations.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('control_id', sa.String(128), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=False, server_default=''),
        sa.Column('category', sa.String(64), nullable=False),
        sa.Column('status', sa.String(16), nullable=False, server_default='implemented'),
        sa.Column('owner', sa.String(255), nullable=False, server_default=''),
        sa.Column('mappings', postgresql.JSONB(), nullable=False, server_default='{}'),
    )
    op.create_index("ix_controls_category", "security_controls",
                    ["category"])
    op.create_index("ix_controls_org_control", "security_controls",
                    ["organization_id", "control_id"])

    op.create_table(
        "control_evidence", _uuid_pk(), *(_ts()),
        sa.Column('control_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('security_controls.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('kind', sa.String(64), nullable=False),
        sa.Column('reference', sa.Text(), nullable=False),
        sa.Column('recorded_by', sa.String(255), nullable=False, server_default=''),
    )
    op.create_index("ix_evidence_control", "control_evidence",
                    ["control_id"])

    op.create_table(
        "security_alerts", _uuid_pk(), *(_ts()),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('organizations.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('kind', sa.String(64), nullable=False),
        sa.Column('severity', sa.String(16), nullable=False),
        sa.Column('detail', sa.Text(), nullable=False, server_default=''),
        sa.Column('status', sa.String(16), nullable=False, server_default='open'),
        sa.Column('actor', sa.String(255), nullable=False, server_default=''),
        sa.Column('request_id', sa.String(64), nullable=False, server_default=''),
    )
    op.create_index("ix_security_alerts_kind", "security_alerts", ["kind"])
    op.create_index("ix_security_alerts_org_status", "security_alerts",
                    ["organization_id", "status"])


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_table(table)
