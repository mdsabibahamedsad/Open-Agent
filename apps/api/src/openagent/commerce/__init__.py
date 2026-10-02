"""MP24: commerce domain — registry, billing, entitlements, usage, revenue.

Pure, provider-neutral business logic. No FastAPI / SQLAlchemy imports here
(except ``config`` which reads env). Persistence lives in
``openagent.db.models.commerce``; orchestration in
``openagent.commerce.service``.

Security invariants enforced by this package:

- Money is integer minor units only; no floats.
- No raw card/bank data types exist anywhere in this package.
- Webhooks are never trusted without HMAC verification (see ``webhooks``).
- Entitlements answer commercial access only, never security privileges.
- Self-hosted works with BILLING_MODE=disabled; paid flows raise instead of
  fabricating success.
"""

from openagent.commerce.types import (
    BILLING_EVENTS,
    BILLING_METRICS,
    BillingInterval,
    BillingMode,
    CheckoutStatus,
    CreditTxnType,
    CurrencyCode,
    DisputeStatus,
    EntitlementSource,
    EntitlementStatus,
    InvoiceStatus,
    LedgerEntryType,
    PaymentStatus,
    PayoutStatus,
    PriceStatus,
    PricingModel,
    ProductStatus,
    ProductType,
    PromotionType,
    QuotaPeriod,
    RefundStatus,
    RegistryAuth,
    RegistryStatus,
    RegistryTrust,
    RegistryType,
    SubscriptionStatus,
    UsageAggregation,
)

__all__ = [
    "BILLING_EVENTS",
    "BILLING_METRICS",
    "BillingInterval",
    "BillingMode",
    "CheckoutStatus",
    "CreditTxnType",
    "CurrencyCode",
    "DisputeStatus",
    "EntitlementSource",
    "EntitlementStatus",
    "InvoiceStatus",
    "LedgerEntryType",
    "PayoutStatus",
    "PaymentStatus",
    "PriceStatus",
    "PricingModel",
    "ProductStatus",
    "ProductType",
    "PromotionType",
    "QuotaPeriod",
    "RefundStatus",
    "RegistryAuth",
    "RegistryStatus",
    "RegistryTrust",
    "RegistryType",
    "SubscriptionStatus",
    "UsageAggregation",
]
