"""MP24: commerce persistence — registry, billing, entitlements, usage, revenue.

MP23 tables (``marketplace_products/prices/entitlements/revenue/payouts``,
``billing_webhook_events``, ``marketplace_registries``) are EXTENDED by
migration 023 with additive nullable columns — never rebuilt, never dropped.

New tables here are normalized per concept: customer, checkout, payment,
payment event (immutable), subscription, entitlement (rich), meters/records/
summaries, quotas, invoices/lines, refunds, disputes, credits, fee policies,
ledger entries, payout events, promotions/codes/redemptions, registry
syncs/cache/credentials, tax calculations.

Money: integer minor units everywhere. No card/bank secrets anywhere —
only ``credential_ref`` handles and provider references.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from openagent.db.models.base import Base, TimestampMixin, UUIDMixin


class BillingCustomerStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    ARCHIVED = "ARCHIVED"


class BillingCustomer(TimestampMixin, UUIDMixin, Base):
    """Provider customer. One org may map to several providers."""

    __tablename__ = "billing_customers"

    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True, index=True)
    organization_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True, index=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    provider_customer_id: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[BillingCustomerStatus] = mapped_column(
        SQLEnum(BillingCustomerStatus, name="billing_customer_status",
                create_constraint=True),
        default=BillingCustomerStatus.ACTIVE, nullable=False, index=True)
    customer_metadata: Mapped[Dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False)

    __table_args__ = (
        UniqueConstraint("provider", "provider_customer_id",
                         name="uq_billing_customers_provider_ref"),
        Index("ix_billing_customers_org", "organization_id"),
    )


class CheckoutSession(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "billing_checkout_sessions"

    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True, index=True)
    organization_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True, index=True)
    product_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("marketplace_products.id",
                                       ondelete="SET NULL"),
        nullable=True, index=True)
    price_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("marketplace_prices.id",
                                       ondelete="SET NULL"),
        nullable=True)
    customer_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("billing_customers.id",
                                       ondelete="SET NULL"),
        nullable=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    provider_session_id: Mapped[str] = mapped_column(String(255), nullable=False,
                                                    unique=True, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False,
                                        default="CREATED", index=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False,
                                                unique=True, index=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True)
    session_metadata: Mapped[Dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False)


class Payment(TimestampMixin, UUIDMixin, Base):
    """Verified payment — created only from provider verification/webhook."""

    __tablename__ = "billing_payments"

    customer_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("billing_customers.id",
                                       ondelete="SET NULL"),
        nullable=True, index=True)
    organization_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True, index=True)
    product_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("marketplace_products.id",
                                       ondelete="SET NULL"),
        nullable=True, index=True)
    price_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("marketplace_prices.id",
                                       ondelete="SET NULL"),
        nullable=True)
    checkout_session_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("billing_checkout_sessions.id",
                                       ondelete="SET NULL"),
        nullable=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    provider_reference: Mapped[str] = mapped_column(String(255), nullable=False,
                                                   unique=True, index=True)
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    status: Mapped[str] = mapped_column(String(16), nullable=False,
                                        default="CREATED", index=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False,
                                                unique=True, index=True)
    payment_metadata: Mapped[Dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False)


class PaymentEvent(TimestampMixin, UUIDMixin, Base):
    """Immutable payment event log (idempotent by provider event id)."""

    __tablename__ = "billing_payment_events"

    payment_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("billing_payments.id",
                                       ondelete="SET NULL"),
        nullable=True, index=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    provider_event_id: Mapped[str] = mapped_column(String(255), nullable=False,
                                                  unique=True, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    payload: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict,
                                                   nullable=False)


class Subscription(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "billing_subscriptions"

    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("billing_customers.id",
                                       ondelete="CASCADE"),
        nullable=False, index=True)
    organization_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True, index=True)
    product_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("marketplace_products.id",
                                       ondelete="SET NULL"),
        nullable=True, index=True)
    price_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("marketplace_prices.id",
                                       ondelete="SET NULL"),
        nullable=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    provider_subscription_id: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False,
                                        default="INCOMPLETE", index=True)
    current_period_start: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True)
    current_period_end: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True)
    cancel_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True)
    trial_end: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    subscription_metadata: Mapped[Dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False)


class CommerceEntitlement(TimestampMixin, UUIDMixin, Base):
    """Rich MP24 entitlement. Commercial access only — never a permission."""

    __tablename__ = "commerce_entitlements"

    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True, index=True)
    organization_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True, index=True)
    product_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("marketplace_products.id",
                                       ondelete="SET NULL"),
        nullable=True, index=True)
    listing_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("marketplace_listings.id",
                                       ondelete="SET NULL"),
        nullable=True, index=True)
    feature: Mapped[str] = mapped_column(String(255), nullable=False,
                                         default="package.install", index=True)
    features: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False,
                                        default="PURCHASE", index=True)
    source_reference: Mapped[str] = mapped_column(String(255), nullable=False,
                                                 default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False,
                                        default="PENDING", index=True)
    valid_from: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True)
    valid_until: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True)
    quantity: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    inherited: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    entitlement_metadata: Mapped[Dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False)

    __table_args__ = (
        Index("ix_commerce_entitlements_subject", "organization_id", "user_id"),
        Index("ix_commerce_entitlements_product", "product_id", "status"),
    )


class UsageMeter(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "usage_meters"

    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True,
                                      index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False, default="count")
    aggregation: Mapped[str] = mapped_column(String(16), nullable=False,
                                             default="SUM")
    reset_period: Mapped[str] = mapped_column(String(16), nullable=False,
                                              default="MONTHLY")
    rules: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict,
                                                 nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class UsageRecord(TimestampMixin, UUIDMixin, Base):
    """Append-oriented raw usage facts. Never updated in place."""

    __tablename__ = "usage_records"

    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True, index=True)
    organization_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True, index=True)
    meter_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("usage_meters.id", ondelete="RESTRICT"),
        nullable=False, index=True)
    product_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("marketplace_products.id",
                                       ondelete="SET NULL"),
        nullable=True)
    feature: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    quantity: Mapped[float] = mapped_column(Integer, nullable=False, default=0)
    unit: Mapped[str] = mapped_column(String(32), nullable=False, default="count")
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="api")
    dedup_key: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False,
                                                unique=True, index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 nullable=False, index=True)
    record_metadata: Mapped[Dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False)

    __table_args__ = (
        Index("ix_usage_records_meter_org", "meter_id", "organization_id",
              "occurred_at"),
    )


class UsageSummary(TimestampMixin, UUIDMixin, Base):
    """Pre-aggregated per-meter/org/period totals (worker-maintained)."""

    __tablename__ = "usage_summaries"

    organization_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True, index=True)
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True)
    meter_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("usage_meters.id", ondelete="CASCADE"),
        nullable=False, index=True)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                  nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                nullable=False)
    total: Mapped[float] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", "meter_id",
                         "period_start", name="uq_usage_summaries"),
    )


class Quota(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "commerce_quotas"

    organization_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True, index=True)
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True)
    meter_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("usage_meters.id", ondelete="CASCADE"),
        nullable=False, index=True)
    product_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("marketplace_products.id",
                                       ondelete="SET NULL"),
        nullable=True)
    limit_value: Mapped[Optional[float]] = mapped_column(Integer, nullable=True)
    period: Mapped[str] = mapped_column(String(16), nullable=False,
                                        default="MONTHLY")
    quota_metadata: Mapped[Dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False)


class QuotaUsage(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "commerce_quota_usage"

    quota_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("commerce_quotas.id", ondelete="CASCADE"),
        nullable=False, index=True)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                  nullable=False)
    used: Mapped[float] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint("quota_id", "period_start", name="uq_quota_usage"),
    )


class Invoice(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "billing_invoices"

    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("billing_customers.id",
                                       ondelete="CASCADE"),
        nullable=False, index=True)
    organization_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True, index=True)
    period_start: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True)
    period_end: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    subtotal_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tax_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    discount_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(16), nullable=False,
                                        default="DRAFT", index=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    provider_reference: Mapped[str] = mapped_column(String(255), nullable=False,
                                                   default="")
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False,
                                                unique=True, index=True)


class InvoiceLine(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "billing_invoice_lines"

    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("billing_invoices.id", ondelete="CASCADE"),
        nullable=False, index=True)
    product_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("marketplace_products.id",
                                       ondelete="SET NULL"),
        nullable=True)
    description: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    quantity: Mapped[float] = mapped_column(Integer, nullable=False, default=1)
    unit_price_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    line_metadata: Mapped[Dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False)


class Refund(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "billing_refunds"

    payment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("billing_payments.id", ondelete="CASCADE"),
        nullable=False, index=True)
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    provider: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    provider_reference: Mapped[str] = mapped_column(String(255), nullable=False,
                                                   default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False,
                                        default="PENDING", index=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False,
                                                unique=True, index=True)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True)


class Dispute(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "billing_disputes"

    payment_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("billing_payments.id", ondelete="SET NULL"),
        nullable=True, index=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    provider_reference: Mapped[str] = mapped_column(String(255), nullable=False,
                                                   default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False,
                                        default="OPEN", index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True)


class CreditAccount(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "credit_accounts"

    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True, index=True)
    organization_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True, index=True)
    currency: Mapped[str] = mapped_column(String(16), nullable=False,
                                          default="CREDITS")

    __table_args__ = (
        Index("ix_credit_accounts_subject", "organization_id", "user_id"),
    )


class CreditTransaction(TimestampMixin, UUIDMixin, Base):
    """Append-only credit ledger. Balance derives from these rows."""

    __tablename__ = "credit_transactions"

    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("credit_accounts.id", ondelete="CASCADE"),
        nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    amount: Mapped[float] = mapped_column(Integer, nullable=False, default=0)
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    product_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("marketplace_products.id",
                                       ondelete="SET NULL"),
        nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False,
                                                unique=True, index=True)
    txn_metadata: Mapped[Dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False)


class FeePolicy(TimestampMixin, UUIDMixin, Base):
    """Configurable platform fee. No hard-coded revenue split."""

    __tablename__ = "commerce_fee_policies"

    marketplace: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    product_type: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    publisher_type: Mapped[str] = mapped_column(String(32), nullable=False,
                                               default="")
    rate_bps: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fixed_fee_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    effective_from: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class CreatorLedgerEntry(TimestampMixin, UUIDMixin, Base):
    """Double-entry-ready creator ledger. Immutable once POSTED."""

    __tablename__ = "creator_ledger_entries"

    publisher_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("publisher_profiles.id",
                                       ondelete="CASCADE"),
        nullable=False, index=True)
    account: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    reference: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    reference_type: Mapped[str] = mapped_column(String(64), nullable=False,
                                               default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False,
                                        default="POSTED", index=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False,
                                                unique=True, index=True)
    entry_metadata: Mapped[Dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False)

    __table_args__ = (
        Index("ix_ledger_publisher", "publisher_id", "status"),
    )


class CommercePayout(TimestampMixin, UUIDMixin, Base):
    """MP24 payout with full lifecycle incl. HELD/ELIGIBLE."""

    __tablename__ = "commerce_payouts"

    publisher_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("publisher_profiles.id",
                                       ondelete="CASCADE"),
        nullable=False, index=True)
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    destination_reference: Mapped[str] = mapped_column(
        String(255), nullable=False, default="")
    provider: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    provider_reference: Mapped[str] = mapped_column(String(255), nullable=False,
                                                   default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False,
                                        default="PENDING", index=True)
    hold_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    requested_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True)
    processed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False,
                                                unique=True, index=True)
    payout_metadata: Mapped[Dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False)
    requested_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True)


class PayoutEvent(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "commerce_payout_events"

    payout_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("commerce_payouts.id", ondelete="CASCADE"),
        nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    actor_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True)
    payload: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict,
                                                   nullable=False)


class Promotion(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "commerce_promotions"

    publisher_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("publisher_profiles.id",
                                       ondelete="SET NULL"),
        nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="PERCENT")
    percent_bps: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class PromoCode(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "commerce_promo_codes"

    promotion_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("commerce_promotions.id",
                                       ondelete="CASCADE"),
        nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True,
                                      index=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True)
    max_redemptions: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    max_per_customer: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    eligible_customers: Mapped[List[str]] = mapped_column(JSON, default=list,
                                                         nullable=False)
    eligible_products: Mapped[List[str]] = mapped_column(JSON, default=list,
                                                        nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    redemption_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class PromoRedemption(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "commerce_promo_redemptions"

    promo_code_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("commerce_promo_codes.id",
                                       ondelete="CASCADE"),
        nullable=False, index=True)
    customer_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("billing_customers.id",
                                       ondelete="SET NULL"),
        nullable=True, index=True)
    checkout_session_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("billing_checkout_sessions.id",
                                       ondelete="SET NULL"),
        nullable=True)
    discount_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False,
                                                unique=True, index=True)


class TaxCalculation(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "commerce_tax_calculations"

    customer_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("billing_customers.id",
                                       ondelete="SET NULL"),
        nullable=True, index=True)
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tax_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    provider: Mapped[str] = mapped_column(String(64), nullable=False, default="noop")
    calculated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    calc_metadata: Mapped[Dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False)


class RegistrySync(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "commerce_registry_syncs"

    registry_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("marketplace_registries.id",
                                       ondelete="CASCADE"),
        nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False,
                                        default="PENDING", index=True)
    packages_synced: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True)


class RegistryCacheEntry(TimestampMixin, UUIDMixin, Base):
    """Local cache of registry metadata/manifests/artifacts (TTL + hash)."""

    __tablename__ = "commerce_registry_cache"

    registry_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("marketplace_registries.id",
                                       ondelete="CASCADE"),
        nullable=False, index=True)
    cache_key: Mapped[str] = mapped_column(String(64), nullable=False,
                                           unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="metadata")
    payload: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict,
                                                   nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True)


class RegistryCredential(TimestampMixin, UUIDMixin, Base):
    """Registry auth binding — credential_ref ONLY, never plaintext."""

    __tablename__ = "commerce_registry_credentials"

    registry_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("marketplace_registries.id",
                                       ondelete="CASCADE"),
        nullable=False, unique=True, index=True)
    auth_type: Mapped[str] = mapped_column(String(32), nullable=False,
                                           default="PUBLIC")
    credential_ref: Mapped[str] = mapped_column(String(255), nullable=False,
                                               default="")
