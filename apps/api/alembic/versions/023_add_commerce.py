"""Add MP24 commerce / billing / entitlement / usage / revenue tables.

Revision ID: 023_add_commerce
Revises: 022_add_marketplace
Create Date: 2026-09-30 00:00:00.000000

Additive only: new tables + ADD COLUMN IF NOT EXISTS on MP23 tables.
Never drops or rebuilds marketplace/package data.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '023_add_commerce'
down_revision = '022_add_marketplace'
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


def _user_fk(nullable=True):
    return sa.Column('user_id', postgresql.UUID(as_uuid=True),
                     sa.ForeignKey('users.id', ondelete='CASCADE'),
                     nullable=nullable)


def _org_fk(nullable=True):
    return sa.Column('organization_id', postgresql.UUID(as_uuid=True),
                     sa.ForeignKey('organizations.id', ondelete='CASCADE'),
                     nullable=nullable)


def _idem():
    return sa.Column('idempotency_key', sa.String(255), nullable=False,
                     unique=True)


def _meta(name='metadata'):
    return sa.Column(name, sa.JSON(), nullable=False, server_default='{}')


def upgrade() -> None:
    op.execute(sa.text(
        "DO $$ BEGIN CREATE TYPE billing_customer_status AS ENUM "
        "('ACTIVE', 'SUSPENDED', 'ARCHIVED'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; END $$;"))

    # MP24: extend MP23 product/pricing vocabularies (additive enum values).
    for value in ('PACKAGE', 'SUBSCRIPTION', 'LICENSE', 'CREDITS',
                  'SERVICE', 'ENTERPRISE'):
        op.execute(sa.text(
            f"ALTER TYPE product_type ADD VALUE IF NOT EXISTS '{value}'"))
    op.execute(sa.text(
        "ALTER TYPE pricing_model ADD VALUE IF NOT EXISTS 'VOLUME'"))

    op.create_table(
        'billing_customers', _uuid_pk(), _user_fk(), _org_fk(),
        sa.Column('provider', sa.String(64), nullable=False),
        sa.Column('provider_customer_id', sa.String(255), nullable=False),
        sa.Column('status', postgresql.ENUM('ACTIVE', 'SUSPENDED', 'ARCHIVED',
                                            name='billing_customer_status',
                                            create_type=False),
                  nullable=False, server_default='ACTIVE'),
        _meta('customer_metadata'), *_ts(),
        sa.UniqueConstraint('provider', 'provider_customer_id',
                            name='uq_billing_customers_provider_ref'),
    )
    op.create_index('ix_billing_customers_org', 'billing_customers',
                    ['organization_id'])

    op.create_table(
        'billing_checkout_sessions', _uuid_pk(), _user_fk(), _org_fk(),
        sa.Column('product_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('marketplace_products.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('price_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('marketplace_prices.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('customer_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('billing_customers.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('provider', sa.String(64), nullable=False),
        sa.Column('provider_session_id', sa.String(255), nullable=False,
                  unique=True),
        sa.Column('status', sa.String(16), nullable=False,
                  server_default='CREATED'),
        _idem(),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        _meta('session_metadata'), *_ts(),
    )

    op.create_table(
        'billing_payments', _uuid_pk(),
        sa.Column('customer_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('billing_customers.id', ondelete='SET NULL'),
                  nullable=True),
        _org_fk(),
        sa.Column('product_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('marketplace_products.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('price_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('marketplace_prices.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('checkout_session_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('billing_checkout_sessions.id',
                                ondelete='SET NULL'), nullable=True),
        sa.Column('provider', sa.String(64), nullable=False),
        sa.Column('provider_reference', sa.String(255), nullable=False,
                  unique=True),
        sa.Column('amount_minor', sa.Integer(), nullable=False,
                  server_default='0'),
        sa.Column('currency', sa.String(3), nullable=False,
                  server_default='USD'),
        sa.Column('status', sa.String(16), nullable=False,
                  server_default='CREATED'),
        _idem(), _meta('payment_metadata'), *_ts(),
    )

    op.create_table(
        'billing_payment_events', _uuid_pk(),
        sa.Column('payment_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('billing_payments.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('provider', sa.String(64), nullable=False),
        sa.Column('provider_event_id', sa.String(255), nullable=False,
                  unique=True),
        sa.Column('event_type', sa.String(64), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False, server_default='{}'),
        *_ts(),
    )

    op.create_table(
        'billing_subscriptions', _uuid_pk(),
        sa.Column('customer_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('billing_customers.id', ondelete='CASCADE'),
                  nullable=False),
        _org_fk(),
        sa.Column('product_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('marketplace_products.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('price_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('marketplace_prices.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('provider', sa.String(64), nullable=False),
        sa.Column('provider_subscription_id', sa.String(255), nullable=False,
                  unique=True),
        sa.Column('status', sa.String(16), nullable=False,
                  server_default='INCOMPLETE'),
        sa.Column('current_period_start', sa.DateTime(timezone=True),
                  nullable=True),
        sa.Column('current_period_end', sa.DateTime(timezone=True),
                  nullable=True),
        sa.Column('cancel_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('trial_end', sa.DateTime(timezone=True), nullable=True),
        sa.Column('quantity', sa.Integer(), nullable=False, server_default='1'),
        _meta('subscription_metadata'), *_ts(),
    )

    op.create_table(
        'commerce_entitlements', _uuid_pk(), _user_fk(), _org_fk(),
        sa.Column('product_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('marketplace_products.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('listing_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('marketplace_listings.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('feature', sa.String(255), nullable=False,
                  server_default='package.install'),
        sa.Column('features', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('source', sa.String(32), nullable=False,
                  server_default='PURCHASE'),
        sa.Column('source_reference', sa.String(255), nullable=False,
                  server_default=''),
        sa.Column('status', sa.String(16), nullable=False,
                  server_default='PENDING'),
        sa.Column('valid_from', sa.DateTime(timezone=True), nullable=True),
        sa.Column('valid_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column('quantity', sa.Integer(), nullable=True),
        sa.Column('used', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('inherited', sa.Boolean(), nullable=False,
                  server_default='false'),
        _meta('entitlement_metadata'), *_ts(),
    )
    op.create_index('ix_commerce_entitlements_subject', 'commerce_entitlements',
                    ['organization_id', 'user_id'])
    op.create_index('ix_commerce_entitlements_product', 'commerce_entitlements',
                    ['product_id', 'status'])

    op.create_table(
        'usage_meters', _uuid_pk(),
        sa.Column('slug', sa.String(100), nullable=False, unique=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('unit', sa.String(32), nullable=False, server_default='count'),
        sa.Column('aggregation', sa.String(16), nullable=False,
                  server_default='SUM'),
        sa.Column('reset_period', sa.String(16), nullable=False,
                  server_default='MONTHLY'),
        sa.Column('rules', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('is_active', sa.Boolean(), nullable=False,
                  server_default='true'),
        *_ts(),
    )

    op.create_table(
        'usage_records', _uuid_pk(), _user_fk(), _org_fk(),
        sa.Column('meter_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('usage_meters.id', ondelete='RESTRICT'),
                  nullable=False),
        sa.Column('product_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('marketplace_products.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('feature', sa.String(255), nullable=False, server_default=''),
        sa.Column('quantity', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('unit', sa.String(32), nullable=False,
                  server_default='count'),
        sa.Column('source', sa.String(64), nullable=False, server_default='api'),
        sa.Column('dedup_key', sa.String(255), nullable=False, server_default=''),
        _idem(),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        _meta('record_metadata'), *_ts(),
    )
    op.create_index('ix_usage_records_meter_org', 'usage_records',
                    ['meter_id', 'organization_id', 'occurred_at'])

    op.create_table(
        'usage_summaries', _uuid_pk(), _user_fk(), _org_fk(),
        sa.Column('meter_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('usage_meters.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('period_start', sa.DateTime(timezone=True), nullable=False),
        sa.Column('period_end', sa.DateTime(timezone=True), nullable=False),
        sa.Column('total', sa.Integer(), nullable=False, server_default='0'),
        *_ts(),
        sa.UniqueConstraint('organization_id', 'user_id', 'meter_id',
                            'period_start', name='uq_usage_summaries'),
    )

    op.create_table(
        'commerce_quotas', _uuid_pk(), _user_fk(), _org_fk(),
        sa.Column('meter_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('usage_meters.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('product_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('marketplace_products.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('limit_value', sa.Integer(), nullable=True),
        sa.Column('period', sa.String(16), nullable=False,
                  server_default='MONTHLY'),
        _meta('quota_metadata'), *_ts(),
    )

    op.create_table(
        'commerce_quota_usage', _uuid_pk(),
        sa.Column('quota_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('commerce_quotas.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('period_start', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used', sa.Integer(), nullable=False, server_default='0'),
        *_ts(),
        sa.UniqueConstraint('quota_id', 'period_start', name='uq_quota_usage'),
    )

    op.create_table(
        'billing_invoices', _uuid_pk(),
        sa.Column('customer_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('billing_customers.id', ondelete='CASCADE'),
                  nullable=False),
        _org_fk(),
        sa.Column('period_start', sa.DateTime(timezone=True), nullable=True),
        sa.Column('period_end', sa.DateTime(timezone=True), nullable=True),
        sa.Column('currency', sa.String(3), nullable=False,
                  server_default='USD'),
        sa.Column('subtotal_minor', sa.Integer(), nullable=False,
                  server_default='0'),
        sa.Column('tax_minor', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('discount_minor', sa.Integer(), nullable=False,
                  server_default='0'),
        sa.Column('total_minor', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('status', sa.String(16), nullable=False, server_default='DRAFT'),
        sa.Column('provider', sa.String(64), nullable=False, server_default=''),
        sa.Column('provider_reference', sa.String(255), nullable=False,
                  server_default=''),
        _idem(), *_ts(),
    )

    op.create_table(
        'billing_invoice_lines', _uuid_pk(),
        sa.Column('invoice_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('billing_invoices.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('product_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('marketplace_products.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('description', sa.String(500), nullable=False,
                  server_default=''),
        sa.Column('quantity', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('unit_price_minor', sa.Integer(), nullable=False,
                  server_default='0'),
        sa.Column('amount_minor', sa.Integer(), nullable=False,
                  server_default='0'),
        _meta('line_metadata'), *_ts(),
    )

    op.create_table(
        'billing_refunds', _uuid_pk(),
        sa.Column('payment_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('billing_payments.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('amount_minor', sa.Integer(), nullable=False,
                  server_default='0'),
        sa.Column('reason', sa.Text(), nullable=False, server_default=''),
        sa.Column('provider', sa.String(64), nullable=False, server_default=''),
        sa.Column('provider_reference', sa.String(255), nullable=False,
                  server_default=''),
        sa.Column('status', sa.String(16), nullable=False,
                  server_default='PENDING'),
        _idem(),
        sa.Column('created_by', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        *_ts(),
    )

    op.create_table(
        'billing_disputes', _uuid_pk(),
        sa.Column('payment_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('billing_payments.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('provider', sa.String(64), nullable=False, server_default=''),
        sa.Column('provider_reference', sa.String(255), nullable=False,
                  server_default=''),
        sa.Column('status', sa.String(16), nullable=False, server_default='OPEN'),
        sa.Column('reason', sa.Text(), nullable=False, server_default=''),
        sa.Column('amount_minor', sa.Integer(), nullable=False,
                  server_default='0'),
        sa.Column('currency', sa.String(3), nullable=False, server_default='USD'),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        *_ts(),
    )

    op.create_table(
        'credit_accounts', _uuid_pk(), _user_fk(), _org_fk(),
        sa.Column('currency', sa.String(16), nullable=False,
                  server_default='CREDITS'),
        *_ts(),
    )

    op.create_table(
        'credit_transactions', _uuid_pk(),
        sa.Column('account_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('credit_accounts.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('type', sa.String(16), nullable=False),
        sa.Column('amount', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('source', sa.String(64), nullable=False, server_default=''),
        sa.Column('product_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('marketplace_products.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        _idem(), _meta('txn_metadata'), *_ts(),
    )

    op.create_table(
        'commerce_fee_policies', _uuid_pk(),
        sa.Column('marketplace', sa.String(100), nullable=False,
                  server_default=''),
        sa.Column('product_type', sa.String(32), nullable=False,
                  server_default=''),
        sa.Column('publisher_type', sa.String(32), nullable=False,
                  server_default=''),
        sa.Column('rate_bps', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('fixed_fee_minor', sa.Integer(), nullable=False,
                  server_default='0'),
        sa.Column('currency', sa.String(3), nullable=False, server_default='USD'),
        sa.Column('effective_from', sa.DateTime(timezone=True), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False,
                  server_default='true'),
        *_ts(),
    )

    op.create_table(
        'creator_ledger_entries', _uuid_pk(),
        sa.Column('publisher_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('publisher_profiles.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('account', sa.String(64), nullable=False),
        sa.Column('type', sa.String(16), nullable=False),
        sa.Column('amount_minor', sa.Integer(), nullable=False,
                  server_default='0'),
        sa.Column('currency', sa.String(3), nullable=False, server_default='USD'),
        sa.Column('reference', sa.String(255), nullable=False, server_default=''),
        sa.Column('reference_type', sa.String(64), nullable=False,
                  server_default=''),
        sa.Column('status', sa.String(16), nullable=False,
                  server_default='POSTED'),
        _idem(), _meta('entry_metadata'), *_ts(),
    )
    op.create_index('ix_ledger_publisher', 'creator_ledger_entries',
                    ['publisher_id', 'status'])

    op.create_table(
        'commerce_payouts', _uuid_pk(),
        sa.Column('publisher_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('publisher_profiles.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('amount_minor', sa.Integer(), nullable=False,
                  server_default='0'),
        sa.Column('currency', sa.String(3), nullable=False, server_default='USD'),
        sa.Column('destination_reference', sa.String(255), nullable=False,
                  server_default=''),
        sa.Column('provider', sa.String(64), nullable=False, server_default=''),
        sa.Column('provider_reference', sa.String(255), nullable=False,
                  server_default=''),
        sa.Column('status', sa.String(16), nullable=False,
                  server_default='PENDING'),
        sa.Column('hold_reason', sa.Text(), nullable=False, server_default=''),
        sa.Column('requested_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
        _idem(), _meta('payout_metadata'),
        sa.Column('requested_by', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        *_ts(),
    )

    op.create_table(
        'commerce_payout_events', _uuid_pk(),
        sa.Column('payout_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('commerce_payouts.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('event_type', sa.String(64), nullable=False),
        sa.Column('actor_user_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('payload', sa.JSON(), nullable=False, server_default='{}'),
        *_ts(),
    )

    op.create_table(
        'commerce_promotions', _uuid_pk(),
        sa.Column('publisher_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('publisher_profiles.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('kind', sa.String(16), nullable=False,
                  server_default='PERCENT'),
        sa.Column('percent_bps', sa.Integer(), nullable=False,
                  server_default='0'),
        sa.Column('amount_minor', sa.Integer(), nullable=False,
                  server_default='0'),
        sa.Column('currency', sa.String(3), nullable=False, server_default='USD'),
        sa.Column('is_active', sa.Boolean(), nullable=False,
                  server_default='true'),
        *_ts(),
    )

    op.create_table(
        'commerce_promo_codes', _uuid_pk(),
        sa.Column('promotion_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('commerce_promotions.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('code', sa.String(64), nullable=False, unique=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('max_redemptions', sa.Integer(), nullable=True),
        sa.Column('max_per_customer', sa.Integer(), nullable=False,
                  server_default='1'),
        sa.Column('eligible_customers', sa.JSON(), nullable=False,
                  server_default='[]'),
        sa.Column('eligible_products', sa.JSON(), nullable=False,
                  server_default='[]'),
        sa.Column('is_active', sa.Boolean(), nullable=False,
                  server_default='true'),
        sa.Column('redemption_count', sa.Integer(), nullable=False,
                  server_default='0'),
        *_ts(),
    )

    op.create_table(
        'commerce_promo_redemptions', _uuid_pk(),
        sa.Column('promo_code_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('commerce_promo_codes.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('customer_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('billing_customers.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('checkout_session_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('billing_checkout_sessions.id',
                                ondelete='SET NULL'), nullable=True),
        sa.Column('discount_minor', sa.Integer(), nullable=False,
                  server_default='0'),
        _idem(), *_ts(),
    )

    op.create_table(
        'commerce_tax_calculations', _uuid_pk(),
        sa.Column('customer_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('billing_customers.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('amount_minor', sa.Integer(), nullable=False,
                  server_default='0'),
        sa.Column('tax_minor', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('currency', sa.String(3), nullable=False, server_default='USD'),
        sa.Column('provider', sa.String(64), nullable=False,
                  server_default='noop'),
        sa.Column('calculated', sa.Boolean(), nullable=False,
                  server_default='false'),
        _meta('calc_metadata'), *_ts(),
    )

    op.create_table(
        'commerce_registry_syncs', _uuid_pk(),
        sa.Column('registry_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('marketplace_registries.id',
                                ondelete='CASCADE'), nullable=False),
        sa.Column('status', sa.String(16), nullable=False,
                  server_default='PENDING'),
        sa.Column('packages_synced', sa.Integer(), nullable=False,
                  server_default='0'),
        sa.Column('error', sa.Text(), nullable=False, server_default=''),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        *_ts(),
    )

    op.create_table(
        'commerce_registry_cache', _uuid_pk(),
        sa.Column('registry_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('marketplace_registries.id',
                                ondelete='CASCADE'), nullable=False),
        sa.Column('cache_key', sa.String(64), nullable=False, unique=True),
        sa.Column('kind', sa.String(32), nullable=False,
                  server_default='metadata'),
        sa.Column('payload', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('sha256', sa.String(64), nullable=False, server_default=''),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        *_ts(),
    )

    op.create_table(
        'commerce_registry_credentials', _uuid_pk(),
        sa.Column('registry_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('marketplace_registries.id',
                                ondelete='CASCADE'), nullable=False,
                  unique=True),
        sa.Column('auth_type', sa.String(32), nullable=False,
                  server_default='PUBLIC'),
        sa.Column('credential_ref', sa.String(255), nullable=False,
                  server_default=''),
        *_ts(),
    )

    # --- Additive MP23 extensions (data-preserving) ---
    for col, ddl in (
        ("publisher_id", "UUID NULL REFERENCES publisher_profiles(id) "
         "ON DELETE SET NULL"),
        ("access", "VARCHAR(32) NOT NULL DEFAULT 'FREE'"),
        ("seat_model", "VARCHAR(32) NOT NULL DEFAULT ''"),
        ("license_kind", "VARCHAR(32) NOT NULL DEFAULT ''"),
        ("trial_days", "INTEGER NOT NULL DEFAULT 0"),
    ):
        op.execute(sa.text(
            f"ALTER TABLE marketplace_products ADD COLUMN IF NOT EXISTS "
            f"{col} {ddl}"))
    for col, ddl in (
        ("pricing_model", "VARCHAR(16) NOT NULL DEFAULT ''"),
        ("billing_interval", "VARCHAR(16) NOT NULL DEFAULT 'ONE_TIME'"),
        ("trial_days", "INTEGER NOT NULL DEFAULT 0"),
        ("usage_rules", "JSON NOT NULL DEFAULT '{}'"),
        ("min_quantity", "INTEGER NOT NULL DEFAULT 1"),
        ("max_quantity", "INTEGER NULL"),
    ):
        op.execute(sa.text(
            f"ALTER TABLE marketplace_prices ADD COLUMN IF NOT EXISTS "
            f"{col} {ddl}"))
    for col, ddl in (
        ("feature", "VARCHAR(255) NOT NULL DEFAULT 'package.install'"),
        ("features", "JSON NOT NULL DEFAULT '[]'"),
        ("quantity", "INTEGER NULL"),
        ("used", "INTEGER NOT NULL DEFAULT 0"),
        ("inherited", "BOOLEAN NOT NULL DEFAULT false"),
        ("source_reference", "VARCHAR(255) NOT NULL DEFAULT ''"),
    ):
        op.execute(sa.text(
            f"ALTER TABLE marketplace_entitlements ADD COLUMN IF NOT EXISTS "
            f"{col} {ddl}"))
    for col, ddl in (
        ("destination_reference", "VARCHAR(255) NOT NULL DEFAULT ''"),
        ("provider", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("hold_reason", "TEXT NOT NULL DEFAULT ''"),
        ("requested_at", "TIMESTAMPTZ NULL"),
        ("processed_at", "TIMESTAMPTZ NULL"),
    ):
        op.execute(sa.text(
            f"ALTER TABLE marketplace_payouts ADD COLUMN IF NOT EXISTS "
            f"{col} {ddl}"))
    for col, ddl in (
        ("retry_count", "INTEGER NOT NULL DEFAULT 0"),
        ("last_error", "TEXT NOT NULL DEFAULT ''"),
        ("dead_letter", "BOOLEAN NOT NULL DEFAULT false"),
    ):
        op.execute(sa.text(
            f"ALTER TABLE billing_webhook_events ADD COLUMN IF NOT EXISTS "
            f"{col} {ddl}"))
    for col, ddl in (
        ("registry_type", "VARCHAR(32) NOT NULL DEFAULT 'PRIVATE'"),
        ("endpoint", "VARCHAR(1000) NOT NULL DEFAULT ''"),
        ("visibility", "VARCHAR(32) NOT NULL DEFAULT 'PRIVATE'"),
        ("auth_type", "VARCHAR(32) NOT NULL DEFAULT 'PUBLIC'"),
        ("status", "VARCHAR(16) NOT NULL DEFAULT 'ACTIVE'"),
        ("last_sync_at", "TIMESTAMPTZ NULL"),
        ("organization_id", "UUID NULL REFERENCES organizations(id) "
         "ON DELETE CASCADE"),
    ):
        op.execute(sa.text(
            f"ALTER TABLE marketplace_registries ADD COLUMN IF NOT EXISTS "
            f"{col} {ddl}"))

    # --- RBAC: billing / payout / registry resources ---
    for value in ('billing', 'payout', 'registry'):
        op.execute(sa.text(
            f"ALTER TYPE permission_resource ADD VALUE IF NOT EXISTS "
            f"'{value}'"))
    _new_perms = (
        ('billing', 'read', 'View billing, subscriptions and invoices', 1),
        ('billing', 'create', 'Create checkouts and customers', 2),
        ('billing', 'update', 'Update subscriptions and billing data', 2),
        ('billing', 'manage', 'Manage refunds, disputes and invoices', 4),
        ('payout', 'read', 'View payouts and revenue', 1),
        ('payout', 'create', 'Request payouts', 2),
        ('payout', 'manage', 'Review, hold, release and reject payouts', 4),
        ('registry', 'read', 'View registries', 1),
        ('registry', 'create', 'Add registries', 2),
        ('registry', 'update', 'Update registries', 2),
        ('registry', 'delete', 'Remove registries', 3),
        ('registry', 'manage', 'Sync and manage registries', 4),
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
        'organization_owner': ('billing:read', 'billing:create',
                               'billing:update', 'billing:manage',
                               'payout:read', 'payout:create', 'payout:manage',
                               'registry:read', 'registry:create',
                               'registry:update', 'registry:delete',
                               'registry:manage'),
        'organization_admin': ('billing:read', 'billing:create',
                               'billing:update', 'billing:manage',
                               'payout:read', 'payout:create', 'payout:manage',
                               'registry:read', 'registry:create',
                               'registry:update', 'registry:delete',
                               'registry:manage'),
        'developer': ('billing:read', 'billing:create', 'payout:read',
                      'registry:read'),
        'operator': ('billing:read', 'payout:read', 'registry:read'),
        'member': ('billing:read', 'payout:read', 'registry:read'),
        'viewer': ('billing:read', 'payout:read', 'registry:read'),
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

    # --- Seed default usage meters (idempotent) ---
    _meters = (
        ("agent_runs", "Agent runs", "run", "COUNT", "MONTHLY"),
        ("workflow_runs", "Workflow executions", "run", "COUNT", "MONTHLY"),
        ("tokens", "AI tokens", "token", "SUM", "MONTHLY"),
        ("browser_minutes", "Browser minutes", "minute", "SUM", "MONTHLY"),
        ("sandbox_seconds", "Sandbox seconds", "second", "SUM", "MONTHLY"),
        ("storage_gb", "Storage GB", "gb", "MAX", "MONTHLY"),
        ("api_requests", "API requests", "request", "COUNT", "MONTHLY"),
    )
    for slug, name, unit, agg, reset in _meters:
        op.execute(
            sa.text(
                "INSERT INTO usage_meters (id, slug, name, unit, aggregation, "
                "reset_period) SELECT gen_random_uuid(), :slug, :name, :unit, "
                ":agg, :reset WHERE NOT EXISTS (SELECT 1 FROM usage_meters "
                "WHERE slug = :slug)"
            ).bindparams(slug=slug, name=name, unit=unit, agg=agg,
                         reset=reset))


def downgrade() -> None:
    for table in ('commerce_registry_credentials', 'commerce_registry_cache',
                  'commerce_registry_syncs', 'commerce_tax_calculations',
                  'commerce_promo_redemptions', 'commerce_promo_codes',
                  'commerce_promotions', 'commerce_payout_events',
                  'commerce_payouts', 'creator_ledger_entries',
                  'commerce_fee_policies', 'credit_transactions',
                  'credit_accounts', 'billing_disputes', 'billing_refunds',
                  'billing_invoice_lines', 'billing_invoices',
                  'commerce_quota_usage', 'commerce_quotas',
                  'usage_summaries', 'usage_records', 'usage_meters',
                  'commerce_entitlements', 'billing_subscriptions',
                  'billing_payment_events', 'billing_payments',
                  'billing_checkout_sessions', 'billing_customers'):
        op.drop_table(table)
    # Additive MP23 columns are left in place (safe downgrade preserves data).
