"""MP24: commerce vocabulary — single source of truth for states/transitions.

Extends (never contradicts) MP23 ``marketplace.types``. New tables/enums for
MP24 live here; MP23 names are re-exported by the service layer where the
persistence still uses ``marketplace_*`` tables.
"""

from __future__ import annotations


class RegistryType:
    LOCAL = "LOCAL"
    PUBLIC = "PUBLIC"
    PRIVATE = "PRIVATE"
    ORGANIZATION = "ORGANIZATION"
    ENTERPRISE = "ENTERPRISE"
    GIT = "GIT"
    OBJECT_STORAGE = "OBJECT_STORAGE"
    CLOUD = "CLOUD"


REGISTRY_TYPES: frozenset[str] = frozenset({
    RegistryType.LOCAL, RegistryType.PUBLIC, RegistryType.PRIVATE,
    RegistryType.ORGANIZATION, RegistryType.ENTERPRISE, RegistryType.GIT,
    RegistryType.OBJECT_STORAGE, RegistryType.CLOUD,
})


class RegistryStatus:
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"
    UNAVAILABLE = "UNAVAILABLE"
    SUSPENDED = "SUSPENDED"


REGISTRY_STATUSES: frozenset[str] = frozenset({
    RegistryStatus.ACTIVE, RegistryStatus.DISABLED,
    RegistryStatus.UNAVAILABLE, RegistryStatus.SUSPENDED,
})


class RegistryTrust:
    CORE = "CORE"
    OFFICIAL = "OFFICIAL"
    VERIFIED = "VERIFIED"
    ORGANIZATION = "ORGANIZATION"
    COMMUNITY = "COMMUNITY"
    UNKNOWN = "UNKNOWN"
    UNTRUSTED = "UNTRUSTED"


#: Ordered worst -> best. Trust affects warnings/signature requirements only;
#: it never bypasses security controls.
REGISTRY_TRUST_RANK: dict[str, int] = {
    RegistryTrust.UNTRUSTED: 0,
    RegistryTrust.UNKNOWN: 1,
    RegistryTrust.COMMUNITY: 2,
    RegistryTrust.ORGANIZATION: 3,
    RegistryTrust.VERIFIED: 4,
    RegistryTrust.OFFICIAL: 5,
    RegistryTrust.CORE: 6,
}


class RegistryAuth:
    PUBLIC = "PUBLIC"
    API_KEY = "API_KEY"
    OAUTH = "OAUTH"
    SERVICE_ACCOUNT = "SERVICE_ACCOUNT"
    SIGNED_REQUEST = "SIGNED_REQUEST"
    PRIVATE_NETWORK = "PRIVATE_NETWORK"


REGISTRY_AUTHS: frozenset[str] = frozenset({
    RegistryAuth.PUBLIC, RegistryAuth.API_KEY, RegistryAuth.OAUTH,
    RegistryAuth.SERVICE_ACCOUNT, RegistryAuth.SIGNED_REQUEST,
    RegistryAuth.PRIVATE_NETWORK,
})


class ProductType:
    PACKAGE = "PACKAGE"
    SUBSCRIPTION = "SUBSCRIPTION"
    BUNDLE = "BUNDLE"
    LICENSE = "LICENSE"
    CREDITS = "CREDITS"
    SERVICE = "SERVICE"
    ENTERPRISE = "ENTERPRISE"


PRODUCT_TYPES: frozenset[str] = frozenset({
    ProductType.PACKAGE, ProductType.SUBSCRIPTION, ProductType.BUNDLE,
    ProductType.LICENSE, ProductType.CREDITS, ProductType.SERVICE,
    ProductType.ENTERPRISE,
})


class ProductStatus:
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class PricingModel:
    FREE = "FREE"
    ONE_TIME = "ONE_TIME"
    SUBSCRIPTION = "SUBSCRIPTION"
    USAGE_BASED = "USAGE_BASED"
    TIERED = "TIERED"
    VOLUME = "VOLUME"
    CUSTOM = "CUSTOM"


PRICING_MODELS: frozenset[str] = frozenset({
    PricingModel.FREE, PricingModel.ONE_TIME, PricingModel.SUBSCRIPTION,
    PricingModel.USAGE_BASED, PricingModel.TIERED, PricingModel.VOLUME,
    PricingModel.CUSTOM,
})


class PriceStatus:
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class BillingInterval:
    ONE_TIME = "ONE_TIME"
    DAILY = "DAILY"
    MONTHLY = "MONTHLY"
    YEARLY = "YEARLY"
    CUSTOM = "CUSTOM"


class BillingMode:
    DISABLED = "disabled"
    MOCK = "mock"
    LIVE = "live"


class CurrencyCode:
    """ISO-4217 subset we explicitly support (extensible via config)."""

    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"
    JPY = "JPY"
    CAD = "CAD"
    AUD = "AUD"


#: Minor-unit exponents (default 2; JPY-style zero-decimal override here).
CURRENCY_EXPONENTS: dict[str, int] = {
    "USD": 2, "EUR": 2, "GBP": 2, "CAD": 2, "AUD": 2, "JPY": 0,
}


class CheckoutStatus:
    CREATED = "CREATED"
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


CHECKOUT_TRANSITIONS: dict[str, frozenset[str]] = {
    CheckoutStatus.CREATED: frozenset({CheckoutStatus.PENDING,
                                       CheckoutStatus.CANCELLED,
                                       CheckoutStatus.EXPIRED}),
    CheckoutStatus.PENDING: frozenset({CheckoutStatus.COMPLETED,
                                       CheckoutStatus.FAILED,
                                       CheckoutStatus.EXPIRED,
                                       CheckoutStatus.CANCELLED}),
    CheckoutStatus.COMPLETED: frozenset(),
    CheckoutStatus.EXPIRED: frozenset(),
    CheckoutStatus.CANCELLED: frozenset(),
    CheckoutStatus.FAILED: frozenset({CheckoutStatus.PENDING}),
}


def can_transition_checkout(source: str, target: str) -> bool:
    return target in CHECKOUT_TRANSITIONS.get(source, frozenset())


class PaymentStatus:
    CREATED = "CREATED"
    AUTHORIZED = "AUTHORIZED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    REFUNDED = "REFUNDED"
    CANCELLED = "CANCELLED"
    DISPUTED = "DISPUTED"


PAYMENT_EVENTS: tuple[str, ...] = (
    "PAYMENT_CREATED",
    "PAYMENT_AUTHORIZED",
    "PAYMENT_SUCCEEDED",
    "PAYMENT_FAILED",
    "PAYMENT_REFUNDED",
    "PAYMENT_CANCELLED",
    "PAYMENT_DISPUTED",
)


class SubscriptionStatus:
    TRIALING = "TRIALING"
    ACTIVE = "ACTIVE"
    PAST_DUE = "PAST_DUE"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    INCOMPLETE = "INCOMPLETE"


SUBSCRIPTION_TRANSITIONS: dict[str, frozenset[str]] = {
    SubscriptionStatus.INCOMPLETE: frozenset({SubscriptionStatus.TRIALING,
                                              SubscriptionStatus.ACTIVE,
                                              SubscriptionStatus.CANCELLED}),
    SubscriptionStatus.TRIALING: frozenset({SubscriptionStatus.ACTIVE,
                                            SubscriptionStatus.CANCELLED,
                                            SubscriptionStatus.EXPIRED,
                                            SubscriptionStatus.PAST_DUE}),
    SubscriptionStatus.ACTIVE: frozenset({SubscriptionStatus.PAST_DUE,
                                          SubscriptionStatus.PAUSED,
                                          SubscriptionStatus.CANCELLED,
                                          SubscriptionStatus.EXPIRED}),
    SubscriptionStatus.PAST_DUE: frozenset({SubscriptionStatus.ACTIVE,
                                            SubscriptionStatus.CANCELLED,
                                            SubscriptionStatus.EXPIRED}),
    SubscriptionStatus.PAUSED: frozenset({SubscriptionStatus.ACTIVE,
                                          SubscriptionStatus.CANCELLED,
                                          SubscriptionStatus.EXPIRED}),
    SubscriptionStatus.CANCELLED: frozenset(),
    SubscriptionStatus.EXPIRED: frozenset({SubscriptionStatus.ACTIVE}),
}


def can_transition_subscription(source: str, target: str) -> bool:
    return target in SUBSCRIPTION_TRANSITIONS.get(source, frozenset())


class EntitlementStatus:
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    SUSPENDED = "SUSPENDED"


ENTITLEMENT_LIVE: frozenset[str] = frozenset({
    EntitlementStatus.ACTIVE,
})


class EntitlementSource:
    PURCHASE = "PURCHASE"
    SUBSCRIPTION = "SUBSCRIPTION"
    GRANT = "GRANT"
    PROMOTION = "PROMOTION"
    ENTERPRISE = "ENTERPRISE"
    ADMIN = "ADMIN"
    TRIAL = "TRIAL"


class UsageAggregation:
    SUM = "SUM"
    COUNT = "COUNT"
    MAX = "MAX"
    UNIQUE = "UNIQUE"
    DURATION = "DURATION"


class QuotaPeriod:
    DAILY = "DAILY"
    MONTHLY = "MONTHLY"
    YEARLY = "YEARLY"
    CUSTOM = "CUSTOM"


class InvoiceStatus:
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    PAID = "PAID"
    VOID = "VOID"
    UNCOLLECTIBLE = "UNCOLLECTIBLE"


class RefundStatus:
    PENDING = "PENDING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class DisputeStatus:
    OPEN = "OPEN"
    WON = "WON"
    LOST = "LOST"
    CLOSED = "CLOSED"


class LedgerEntryType:
    CREDIT = "CREDIT"
    DEBIT = "DEBIT"
    REFUND = "REFUND"
    FEE = "FEE"
    ADJUSTMENT = "ADJUSTMENT"
    PAYOUT = "PAYOUT"


class PayoutStatus:
    PENDING = "PENDING"
    ELIGIBLE = "ELIGIBLE"
    PROCESSING = "PROCESSING"
    PAID = "PAID"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    HELD = "HELD"


PAYOUT_TRANSITIONS: dict[str, frozenset[str]] = {
    PayoutStatus.PENDING: frozenset({PayoutStatus.ELIGIBLE,
                                     PayoutStatus.HELD,
                                     PayoutStatus.CANCELLED}),
    PayoutStatus.ELIGIBLE: frozenset({PayoutStatus.PROCESSING,
                                      PayoutStatus.HELD,
                                      PayoutStatus.CANCELLED}),
    PayoutStatus.HELD: frozenset({PayoutStatus.ELIGIBLE,
                                  PayoutStatus.CANCELLED}),
    PayoutStatus.PROCESSING: frozenset({PayoutStatus.PAID,
                                        PayoutStatus.FAILED}),
    PayoutStatus.FAILED: frozenset({PayoutStatus.ELIGIBLE,
                                    PayoutStatus.CANCELLED}),
    PayoutStatus.PAID: frozenset(),
    PayoutStatus.CANCELLED: frozenset(),
}


def can_transition_payout(source: str, target: str) -> bool:
    return target in PAYOUT_TRANSITIONS.get(source, frozenset())


class CreditTxnType:
    GRANT = "GRANT"
    PURCHASE = "PURCHASE"
    CONSUME = "CONSUME"
    REFUND = "REFUND"
    EXPIRE = "EXPIRE"
    ADJUSTMENT = "ADJUSTMENT"


class PromotionType:
    PERCENT = "PERCENT"
    FIXED = "FIXED"
    TRIAL = "TRIAL"
    PERIOD = "PERIOD"


BILLING_EVENTS: tuple[str, ...] = (
    "CUSTOMER_CREATED",
    "CHECKOUT_CREATED",
    "CHECKOUT_COMPLETED",
    "PAYMENT_SUCCEEDED",
    "PAYMENT_FAILED",
    "SUBSCRIPTION_CREATED",
    "SUBSCRIPTION_UPDATED",
    "SUBSCRIPTION_CANCELLED",
    "ENTITLEMENT_GRANTED",
    "ENTITLEMENT_REVOKED",
    "ENTITLEMENT_EXPIRED",
    "USAGE_RECORDED",
    "INVOICE_CREATED",
    "INVOICE_PAID",
    "REFUND_CREATED",
    "PAYOUT_CREATED",
    "PAYOUT_COMPLETED",
    "CREDIT_GRANTED",
    "CREDIT_CONSUMED",
    "DISPUTE_OPENED",
    "DISPUTE_CLOSED",
)

BILLING_METRICS: tuple[str, ...] = (
    "billing_checkout_total",
    "billing_payment_success_total",
    "billing_payment_failed_total",
    "billing_webhook_total",
    "billing_webhook_failed_total",
    "subscription_active_total",
    "entitlement_active_total",
    "usage_record_total",
    "invoice_total",
    "refund_total",
    "payout_total",
    "payout_failed_total",
)

#: Seat/license models for future seat-based products.
SEAT_MODELS: frozenset[str] = frozenset({"SEAT", "USER", "TEAM", "ORGANIZATION"})

#: Package commercial access levels.
PACKAGE_ACCESS: frozenset[str] = frozenset({
    "FREE", "PAID", "PRIVATE", "SUBSCRIPTION_ONLY", "ENTITLEMENT_REQUIRED",
})

#: Commercial (not OSS) license kinds — never confused with SPDX licenses.
COMMERCIAL_LICENSES: frozenset[str] = frozenset({
    "USER_LICENSE", "TEAM_LICENSE", "ORG_LICENSE", "INSTANCE_LICENSE",
})

#: Cloud service product catalog stubs (abstractions only, MP25 implements).
CLOUD_PRODUCTS: tuple[str, ...] = (
    "cloud_workspace", "hosted_agent", "workflow_executions",
    "browser_runtime", "sandbox_runtime", "storage", "api_usage",
    "team_seats", "enterprise",
)

CLOUD_METERS: tuple[str, ...] = (
    "agent_runs", "workflow_runs", "tokens", "browser_minutes",
    "sandbox_seconds", "storage_gb", "api_requests",
)
