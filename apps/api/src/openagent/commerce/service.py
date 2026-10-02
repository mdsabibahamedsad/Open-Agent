"""MP24: commerce service — DB orchestration for billing/entitlements/usage.

All financial mutations are idempotent (unique idempotency keys / provider
references) and audited. Money is integer minor units. Provider state is
authoritative for payments/subscriptions; our rows mirror verified events.

Dual-write note: entitlements are written to ``commerce_entitlements``
(rich MP24 engine) AND ``marketplace_entitlements`` (MP23 install gate) in
the same transaction so paid-install gating keeps working.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from openagent.commerce import entitlements as ent_engine
from openagent.commerce import ledger as ledger_lib
from openagent.commerce import usage as usage_lib
from openagent.commerce import webhooks as webhook_lib
from openagent.commerce.config import get_commerce_settings
from openagent.commerce.money import normalize_currency
from openagent.commerce.providers import (
    CommerceError,
    get_billing_provider,
)
from openagent.commerce.types import (
    can_transition_checkout,
    can_transition_payout,
    can_transition_subscription,
)
from openagent.db.models.commerce import (
    BillingCustomer,
    BillingCustomerStatus,
    CheckoutSession,
    CommerceEntitlement,
    CommercePayout,
    CreatorLedgerEntry,
    CreditTransaction,
    Dispute,
    FeePolicy,
    Invoice,
    InvoiceLine,
    Payment,
    PaymentEvent,
    PayoutEvent,
    PromoCode,
    PromoRedemption,
    Promotion,
    Quota,
    QuotaUsage,
    Refund,
    RegistryCacheEntry,
    RegistrySync,
    Subscription,
    UsageMeter,
    UsageRecord,
    UsageSummary,
)
from openagent.db.models.marketplace import (
    BillingWebhookEvent,
    MarketplaceRegistry,
    Price,
    PricingModel,
    Product,
    ProductStatus,
    ProductType,
    PublisherMember,
    RevenueRecord,
    RevenueStatus,
)
from openagent.db.models.marketplace import (
    Entitlement as LegacyEntitlement,
)
from openagent.db.models.marketplace import (
    EntitlementStatus as LegacyEntitlementStatus,
)
from openagent.db.models.marketplace import (
    Payout as LegacyPayout,
)
from openagent.db.models.marketplace import (
    PayoutStatus as LegacyPayoutStatus,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _idem(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


# --------------------------------------------------------------------------
# Customers / products / prices
# --------------------------------------------------------------------------

async def get_or_create_customer(db: AsyncSession, *, provider: str,
                                 provider_customer_id: str,
                                 user_id: uuid.UUID | None = None,
                                 organization_id: uuid.UUID | None = None,
                                 idem: str = "") -> BillingCustomer:
    existing = (await db.execute(select(BillingCustomer).where(
        BillingCustomer.provider == provider,
        BillingCustomer.provider_customer_id == provider_customer_id
    ))).scalar_one_or_none()
    if existing is not None:
        return existing
    row = BillingCustomer(
        user_id=user_id, organization_id=organization_id, provider=provider,
        provider_customer_id=provider_customer_id,
        status=BillingCustomerStatus.ACTIVE, customer_metadata={})
    db.add(row)
    await db.flush()
    return row


async def create_product(db: AsyncSession, *, listing_id: uuid.UUID,
                         publisher_id: uuid.UUID | None,
                         product_type: str, pricing_model: str,
                         currency: str, access: str = "FREE",
                         seat_model: str = "", license_kind: str = "",
                         trial_days: int = 0,
                         metadata: dict[str, Any] | None = None,
                         created_by: uuid.UUID | None = None) -> Product:
    currency = normalize_currency(currency)
    try:
        ptype = ProductType(product_type)
    except ValueError:
        # Legacy MP23 databases only know SINGLE_LISTING/BUNDLE/...;
        # PACKAGE-family products map to SINGLE_LISTING there.
        ptype = ProductType.SINGLE_LISTING
    try:
        pricing = PricingModel(pricing_model)
    except ValueError:
        pricing = PricingModel.CUSTOM
    product = Product(
        listing_id=listing_id, publisher_id=publisher_id, product_type=ptype,
        pricing_model=pricing, currency=currency,
        status=ProductStatus.DRAFT, access=access, seat_model=seat_model,
        license_kind=license_kind, trial_days=trial_days,
        product_metadata={**(metadata or {}),
                          "mp24_product_type": product_type,
                          "mp24_pricing_model": pricing_model},
        created_by=created_by)
    db.add(product)
    await db.flush()
    return product


async def create_price(db: AsyncSession, *, product_id: uuid.UUID,
                       amount_minor: int, currency: str,
                       pricing_model: str = "",
                       billing_interval: str = "ONE_TIME",
                       trial_days: int = 0,
                       usage_rules: dict[str, Any] | None = None) -> Price:
    if amount_minor < 0:
        raise CommerceError("BAD_AMOUNT", "price must be >= 0")
    currency = normalize_currency(currency)
    price = Price(product_id=product_id, amount_minor=amount_minor,
                  currency=currency, interval=billing_interval,
                  pricing_model=pricing_model,
                  billing_interval=billing_interval, trial_days=trial_days,
                  usage_rules=usage_rules or {},
                  tiers=[], status=ProductStatus.DRAFT)
    db.add(price)
    await db.flush()
    return price


# --------------------------------------------------------------------------
# Checkout
# --------------------------------------------------------------------------

async def create_checkout(db: AsyncSession, *, customer: BillingCustomer,
                          product: Product, price: Price,
                          organization_id: uuid.UUID | None,
                          user_id: uuid.UUID | None,
                          idempotency_key: str = "",
                          expires_minutes: int = 30) -> CheckoutSession:
    settings = get_commerce_settings()
    provider = get_billing_provider(mode=settings.normalized_mode(),
                                    webhook_secret=settings.BILLING_WEBHOOK_SECRET)
    idem = idempotency_key or _idem("chk")
    existing = (await db.execute(select(CheckoutSession).where(
        CheckoutSession.idempotency_key == idem))).scalar_one_or_none()
    if existing is not None:
        return existing
    provider_price_id = str((price.tiers or [{}])[0].get(
        "provider_price_id", "")) if isinstance(price.tiers, list) else ""
    result = await provider.create_checkout(
        provider_customer_id=customer.provider_customer_id,
        provider_price_id=provider_price_id or str(price.id),
        product_id=str(product.id),
        organization_id=str(organization_id or ""),
        success_url=settings.BILLING_SUCCESS_URL,
        cancel_url=settings.BILLING_CANCEL_URL,
        metadata={"test_mode": settings.normalized_mode() == "mock"})
    row = CheckoutSession(
        user_id=user_id, organization_id=organization_id,
        product_id=product.id, price_id=price.id, customer_id=customer.id,
        provider=provider.name,
        provider_session_id=result.provider_session_id, status="CREATED",
        idempotency_key=idem,
        expires_at=_now() + timedelta(minutes=expires_minutes),
        session_metadata={"checkout_url": result.checkout_url,
                          **result.metadata})
    db.add(row)
    await db.flush()
    return row


async def transition_checkout(db: AsyncSession, session: CheckoutSession,
                              target: str) -> CheckoutSession:
    if not can_transition_checkout(session.status, target):
        raise CommerceError("BAD_TRANSITION",
                            f"checkout {session.status} -> {target} illegal")
    session.status = target
    if target == "COMPLETED":
        session.completed_at = _now()
    await db.flush()
    return session


# --------------------------------------------------------------------------
# Webhook intake (verified, idempotent, replay-safe)
# --------------------------------------------------------------------------

async def process_billing_webhook(
        db: AsyncSession, *, provider: str, headers: dict[str, str],
        raw_body: bytes, payload: dict[str, Any]) -> dict[str, Any]:
    settings = get_commerce_settings()
    secret = settings.BILLING_WEBHOOK_SECRET or "mock-secret"
    signature = (headers.get("x-webhook-signature")
                 or headers.get("stripe-signature", "").split(",")[-1]
                 or headers.get("x-signature", ""))
    if signature.startswith("v1="):
        signature = signature[3:]
    if not webhook_lib.verify_signature(secret=secret, raw_body=raw_body,
                                        signature=signature):
        raise CommerceError("WEBHOOK_UNVERIFIED",
                            "webhook signature verification failed")
    timestamp = webhook_lib.extract_timestamp(headers, payload)
    if timestamp is not None and not webhook_lib.verify_timestamp(
            timestamp, max_skew_seconds=settings.BILLING_WEBHOOK_SKEW_SECONDS):
        raise CommerceError("WEBHOOK_STALE", "webhook timestamp outside window")
    event_id = str(payload.get("event_id") or payload.get("id") or "")
    if not event_id:
        raise CommerceError("WEBHOOK_NO_ID", "webhook has no event id")
    event_type = str(payload.get("event_type") or payload.get("type") or "UNKNOWN")
    idem = webhook_lib.idempotency_key(provider=provider, event_id=event_id)

    existing = (await db.execute(select(BillingWebhookEvent).where(
        BillingWebhookEvent.event_id == event_id))).scalar_one_or_none()
    if existing is not None:
        # Replay: return prior outcome without re-applying mutations.
        return {"deduplicated": True, "event_id": event_id,
                "processed": existing.processed}

    record = BillingWebhookEvent(
        provider=provider, event_id=event_id, event_type=event_type,
        payload={k: v for k, v in payload.items()
                 if k not in ("card_number", "cvv", "pan", "bank_account")},
        signature_valid=True, processed=False, idempotency_key=idem)
    db.add(record)
    await db.flush()
    try:
        outcome = await _apply_billing_event(db, provider=provider,
                                             event_type=event_type,
                                             payload=payload)
    except Exception as exc:  # persist + re-raise for retry/dead-letter
        if hasattr(record, "retry_count"):
            record.retry_count = int(getattr(record, "retry_count", 0)) + 1
        if hasattr(record, "last_error"):
            record.last_error = str(exc)[:2000]
        if int(getattr(record, "retry_count", 1)) >= 5 and hasattr(
                record, "dead_letter"):
            record.dead_letter = True
        await db.flush()
        raise
    record.processed = True
    record.processed_at = _now()
    await db.flush()
    return {"deduplicated": False, "event_id": event_id, "processed": True,
            **outcome}


async def _apply_billing_event(db: AsyncSession, *, provider: str,
                               event_type: str,
                               payload: dict[str, Any]) -> dict[str, Any]:
    normalized = event_type.upper()
    if normalized in ("PAYMENT_SUCCEEDED", "PAYMENT.SUCCEEDED",
                      "CHECKOUT_SESSION_COMPLETED", "CHARGE.SUCCEEDED"):
        return await _apply_payment_succeeded(db, provider=provider,
                                              payload=payload)
    if normalized in ("PAYMENT_FAILED", "PAYMENT.FAILED",
                      "CHARGE.FAILED"):
        return await _apply_payment_failed(db, provider=provider,
                                           payload=payload)
    if normalized in ("PAYMENT_REFUNDED", "CHARGE.REFUNDED"):
        return await _apply_payment_refunded(db, provider=provider,
                                             payload=payload)
    if normalized in ("SUBSCRIPTION_CREATED", "CUSTOMER.SUBSCRIPTION.CREATED"):
        return await _apply_subscription_event(
            db, provider=provider, payload=payload, status="ACTIVE")
    if normalized in ("SUBSCRIPTION_UPDATED",):
        return await _apply_subscription_event(
            db, provider=provider, payload=payload, status="ACTIVE")
    if normalized in ("SUBSCRIPTION_CANCELLED", "CUSTOMER.SUBSCRIPTION.DELETED"):
        return await _apply_subscription_event(
            db, provider=provider, payload=payload, status="CANCELLED")
    if normalized in ("DISPUTE_OPENED", "CHARGE.DISPUTE.CREATED"):
        return await _apply_dispute(db, provider=provider, payload=payload,
                                    status="OPEN")
    if normalized in ("DISPUTE_CLOSED", "CHARGE.DISPUTE.CLOSED"):
        return await _apply_dispute(db, provider=provider, payload=payload,
                                    status="CLOSED")
    return {"applied": False, "reason": f"unhandled event {event_type}"}


async def _apply_payment_succeeded(db: AsyncSession, *, provider: str,
                                   payload: dict[str, Any]) -> dict[str, Any]:
    reference = str(payload.get("transaction_reference") or payload.get(
        "payment_id") or payload.get("charge_id") or "")
    if not reference:
        raise CommerceError("BAD_EVENT", "payment event has no reference")
    payment = (await db.execute(select(Payment).where(
        Payment.provider == provider,
        Payment.provider_reference == reference))).scalar_one_or_none()
    if payment is None:
        product_id = payload.get("product_id")
        payment = Payment(
            customer_id=payload.get("customer_id"),
            organization_id=payload.get("organization_id"),
            product_id=product_id,
            provider=provider, provider_reference=reference,
            amount_minor=int(payload.get("amount_minor", 0)),
            currency=normalize_currency(str(payload.get("currency", "USD"))),
            status="SUCCEEDED", idempotency_key=_idem("pay"),
            payment_metadata={"test_mode": payload.get("test_mode", False)})
        db.add(payment)
        await db.flush()
    else:
        payment.status = "SUCCEEDED"
        await db.flush()
    await _record_payment_event(db, payment=payment, provider=provider,
                                event_id=str(payload.get("event_id", _idem("evt"))),
                                event_type="PAYMENT_SUCCEEDED", payload=payload)
    # Checkout completion (frontend input is never trusted; only this path
    # marks checkouts complete). Walk the state machine legally:
    # CREATED -> PENDING -> COMPLETED.
    checkout_ref = payload.get("checkout_session_id")
    if checkout_ref:
        session = (await db.execute(select(CheckoutSession).where(
            CheckoutSession.provider_session_id == str(checkout_ref)
        ))).scalar_one_or_none()
        if session is not None and session.status == "CREATED":
            await transition_checkout(db, session, "PENDING")
        if session is not None and session.status == "PENDING":
            await transition_checkout(db, session, "COMPLETED")
    entitlement_id = await _grant_purchase_entitlement(
        db, payment=payment, payload=payload)
    revenue_id = await _record_sale_revenue(db, payment=payment,
                                            payload=payload)
    return {"applied": True, "payment_id": str(payment.id),
            "entitlement_id": entitlement_id, "revenue_id": revenue_id}


async def _apply_payment_failed(db: AsyncSession, *, provider: str,
                                payload: dict[str, Any]) -> dict[str, Any]:
    reference = str(payload.get("transaction_reference") or "")
    payment = (await db.execute(select(Payment).where(
        Payment.provider == provider,
        Payment.provider_reference == reference))).scalar_one_or_none() \
        if reference else None
    if payment is not None:
        payment.status = "FAILED"
        await db.flush()
        await _record_payment_event(
            db, payment=payment, provider=provider,
            event_id=str(payload.get("event_id", _idem("evt"))),
            event_type="PAYMENT_FAILED", payload=payload)
    return {"applied": True,
            "payment_id": str(payment.id) if payment else None}


async def _apply_payment_refunded(db: AsyncSession, *, provider: str,
                                  payload: dict[str, Any]) -> dict[str, Any]:
    reference = str(payload.get("transaction_reference") or "")
    payment = (await db.execute(select(Payment).where(
        Payment.provider == provider,
        Payment.provider_reference == reference))).scalar_one_or_none() \
        if reference else None
    if payment is None:
        raise CommerceError("PAYMENT_NOT_FOUND",
                            f"refund for unknown payment {reference}")
    payment.status = "REFUNDED"
    refund = Refund(payment_id=payment.id,
                    amount_minor=int(payload.get("amount_minor",
                                                 payment.amount_minor)),
                    reason=str(payload.get("reason", "")),
                    provider=provider,
                    provider_reference=str(payload.get("refund_id", _idem("re"))),
                    status="SUCCEEDED",
                    idempotency_key=webhook_lib.idempotency_key(
                        provider=provider,
                        event_id="refund:" + str(payload.get("event_id", reference))))
    db.add(refund)
    await db.flush()
    await _record_payment_event(
        db, payment=payment, provider=provider,
        event_id=str(payload.get("event_id", _idem("evt"))),
        event_type="PAYMENT_REFUNDED", payload=payload)
    # Refund updates entitlement per product policy (default: revoke paid
    # install grant created by this payment, keep history).
    await _revoke_payment_entitlements(db, payment=payment,
                                      reason="refund issued")
    return {"applied": True, "refund_id": str(refund.id)}


async def _apply_subscription_event(db: AsyncSession, *, provider: str,
                                    payload: dict[str, Any],
                                    status: str) -> dict[str, Any]:
    sub_ref = str(payload.get("provider_subscription_id")
                  or payload.get("subscription_id") or "")
    if not sub_ref:
        raise CommerceError("BAD_EVENT", "subscription event has no id")
    sub = (await db.execute(select(Subscription).where(
        Subscription.provider_subscription_id == sub_ref))).scalar_one_or_none()
    if sub is None:
        customer_ref = payload.get("provider_customer_id")
        customer = None
        if customer_ref:
            customer = (await db.execute(select(BillingCustomer).where(
                BillingCustomer.provider_customer_id == str(customer_ref)
            ))).scalar_one_or_none()
        if customer is None:
            raise CommerceError("CUSTOMER_NOT_FOUND",
                                "subscription event for unknown customer")
        sub = Subscription(
            customer_id=customer.id,
            organization_id=payload.get("organization_id"),
            product_id=payload.get("product_id"),
            price_id=payload.get("price_id"), provider=provider,
            provider_subscription_id=sub_ref, status="INCOMPLETE",
            subscription_metadata={})
        db.add(sub)
        await db.flush()
    if not can_transition_subscription(sub.status, status) and sub.status != status:
        # Provider is authoritative: allow forward sync but keep audit trail.
        sub.subscription_metadata = {**sub.subscription_metadata,
                                     "provider_status_override": status}
    else:
        sub.status = status
    period_end = payload.get("current_period_end")
    if period_end:
        try:
            sub.current_period_end = datetime.fromisoformat(str(period_end))
        except ValueError:
            pass
    await db.flush()
    # Subscription grants/refreshes a SUBSCRIPTION-source entitlement.
    if status in ("ACTIVE",):
        await _grant_subscription_entitlement(db, subscription=sub,
                                              payload=payload)
    elif status in ("CANCELLED", "EXPIRED"):
        await _revoke_subscription_entitlements(db, subscription=sub,
                                               reason=f"subscription {status.lower()}")
    return {"applied": True, "subscription_id": str(sub.id),
            "status": sub.status}


async def _apply_dispute(db: AsyncSession, *, provider: str,
                         payload: dict[str, Any], status: str) -> dict[str, Any]:
    payment = None
    reference = str(payload.get("transaction_reference") or "")
    if reference:
        payment = (await db.execute(select(Payment).where(
            Payment.provider_reference == reference))).scalar_one_or_none()
    dispute = Dispute(
        payment_id=payment.id if payment else None, provider=provider,
        provider_reference=str(payload.get("dispute_id", _idem("dp"))),
        status=status, reason=str(payload.get("reason", "")),
        amount_minor=int(payload.get("amount_minor",
                                     payment.amount_minor if payment else 0)),
        currency=payment.currency if payment else "USD")
    if status in ("WON", "LOST", "CLOSED"):
        dispute.resolved_at = _now()
    db.add(dispute)
    if payment is not None and status == "OPEN":
        payment.status = "DISPUTED"
    await db.flush()
    return {"applied": True, "dispute_id": str(dispute.id)}


async def _record_payment_event(db: AsyncSession, *, payment: Payment,
                                provider: str, event_id: str, event_type: str,
                                payload: dict[str, Any]) -> None:
    existing = (await db.execute(select(PaymentEvent).where(
        PaymentEvent.provider_event_id == event_id))).scalar_one_or_none()
    if existing is not None:
        return
    db.add(PaymentEvent(payment_id=payment.id, provider=provider,
                        provider_event_id=event_id, event_type=event_type,
                        payload={k: v for k, v in payload.items()
                                 if k not in ("card_number", "cvv")}))
    await db.flush()


# --------------------------------------------------------------------------
# Entitlements
# --------------------------------------------------------------------------

async def _grant_purchase_entitlement(db: AsyncSession, *, payment: Payment,
                                      payload: dict[str, Any]) -> str | None:
    if payment.product_id is None:
        return None
    product = await db.get(Product, payment.product_id)
    if product is None:
        return None
    mp24_type = (product.product_metadata or {}).get("mp24_product_type") \
        or (product.product_type.value
            if hasattr(product.product_type, "value")
            else str(product.product_type))
    features = ent_engine.product_entitlement_features(
        product_type=mp24_type,
        package_slug=str(payload.get("package_slug", "")))
    return await grant_entitlement(
        db, product=product, source="PURCHASE",
        source_reference=payment.provider_reference,
        organization_id=payment.organization_id, user_id=None,
        features=features, status="ACTIVE")


async def grant_entitlement(db: AsyncSession, *, product: Product,
                            source: str, source_reference: str = "",
                            organization_id: uuid.UUID | None = None,
                            user_id: uuid.UUID | None = None,
                            features: list[str] | None = None,
                            status: str = "ACTIVE",
                            valid_from: datetime | None = None,
                            valid_until: datetime | None = None,
                            quantity: int | None = None,
                            inherited: bool = False) -> str:
    feats = features or ["package.install", "package.update"]
    # Idempotent: same source_reference never grants twice.
    if source_reference:
        existing = (await db.execute(select(CommerceEntitlement).where(
            CommerceEntitlement.source_reference == source_reference,
            CommerceEntitlement.product_id == product.id
        ))).scalar_one_or_none()
        if existing is not None:
            return str(existing.id)
    row = CommerceEntitlement(
        user_id=user_id, organization_id=organization_id,
        product_id=product.id, listing_id=product.listing_id,
        feature=feats[0], features=feats, source=source,
        source_reference=source_reference, status=status,
        valid_from=valid_from or _now(), valid_until=valid_until,
        quantity=quantity, used=0, inherited=inherited,
        entitlement_metadata={})
    db.add(row)
    await db.flush()
    # Legacy dual-write for the MP23 install gate (same transaction).
    legacy = LegacyEntitlement(
        organization_id=organization_id, user_id=user_id,
        product_id=product.id, listing_id=product.listing_id,
        status=LegacyEntitlementStatus.ACTIVE
        if status == "ACTIVE" else LegacyEntitlementStatus.REVOKED,
        valid_from=row.valid_from, valid_until=valid_until, source=source,
        feature=feats[0], features=feats, source_reference=source_reference,
        inherited=inherited,
        entitlement_metadata={"commerce_entitlement_id": str(row.id)})
    db.add(legacy)
    await db.flush()
    return str(row.id)


async def _grant_subscription_entitlement(db: AsyncSession, *,
                                          subscription: Subscription,
                                          payload: dict[str, Any]) -> None:
    if subscription.product_id is None:
        return
    product = await db.get(Product, subscription.product_id)
    if product is None:
        return
    features = ent_engine.product_entitlement_features(
        product_type="SUBSCRIPTION",
        package_slug=str(payload.get("package_slug", "")))
    await grant_entitlement(
        db, product=product, source="SUBSCRIPTION",
        source_reference=subscription.provider_subscription_id,
        organization_id=subscription.organization_id, features=features,
        status="ACTIVE", valid_until=subscription.current_period_end)


async def _revoke_payment_entitlements(db: AsyncSession, *,
                                       payment: Payment, reason: str) -> None:
    rows = (await db.execute(select(CommerceEntitlement).where(
        CommerceEntitlement.source == "PURCHASE",
        CommerceEntitlement.source_reference == payment.provider_reference,
        CommerceEntitlement.status == "ACTIVE"))).scalars().all()
    for row in rows:
        row.status = "REVOKED"
    legacy_rows = (await db.execute(select(LegacyEntitlement).where(
        LegacyEntitlement.product_id == payment.product_id,
        LegacyEntitlement.status == LegacyEntitlementStatus.ACTIVE
    ))).scalars().all() if payment.product_id else []
    for legacy in legacy_rows:
        legacy.status = LegacyEntitlementStatus.REVOKED
    await db.flush()


async def _revoke_subscription_entitlements(db: AsyncSession, *,
                                            subscription: Subscription,
                                            reason: str) -> None:
    rows = (await db.execute(select(CommerceEntitlement).where(
        CommerceEntitlement.source == "SUBSCRIPTION",
        CommerceEntitlement.source_reference ==
        subscription.provider_subscription_id,
        CommerceEntitlement.status == "ACTIVE"))).scalars().all()
    for row in rows:
        row.status = "REVOKED"
    await db.flush()


async def revoke_entitlement(db: AsyncSession, entitlement_id: uuid.UUID,
                             *, reason: str = "") -> CommerceEntitlement:
    row = await db.get(CommerceEntitlement, entitlement_id)
    if row is None:
        raise CommerceError("NOT_FOUND", "entitlement not found")
    row.status = "REVOKED"
    row.entitlement_metadata = {**row.entitlement_metadata,
                                "revoke_reason": reason}
    await db.flush()
    return row


async def list_live_entitlements(db: AsyncSession, *,
                                 organization_id: uuid.UUID | None = None,
                                 user_id: uuid.UUID | None = None,
                                 product_id: uuid.UUID | None = None,
                                 limit: int = 200) -> list[CommerceEntitlement]:
    stmt = select(CommerceEntitlement).where(
        CommerceEntitlement.status.in_(["ACTIVE", "TRIAL"]))
    if organization_id is not None:
        stmt = stmt.where(
            CommerceEntitlement.organization_id == organization_id)
    if user_id is not None:
        stmt = stmt.where(CommerceEntitlement.user_id == user_id)
    if product_id is not None:
        stmt = stmt.where(CommerceEntitlement.product_id == product_id)
    return list((await db.execute(stmt.order_by(
        CommerceEntitlement.created_at.desc()).limit(limit))).scalars().all())


def entitlement_to_dict(row: CommerceEntitlement) -> dict[str, Any]:
    return {"id": str(row.id),
            "organization_id": str(row.organization_id) if row.organization_id else None,
            "user_id": str(row.user_id) if row.user_id else None,
            "product_id": str(row.product_id) if row.product_id else None,
            "listing_id": str(row.listing_id) if row.listing_id else None,
            "feature": row.feature, "features": row.features,
            "source": row.source, "status": row.status,
            "valid_from": row.valid_from.isoformat() if row.valid_from else None,
            "valid_until": row.valid_until.isoformat() if row.valid_until else None,
            "quantity": row.quantity, "used": row.used}


async def check_access(db: AsyncSession, *, feature: str,
                       organization_id: uuid.UUID | None = None,
                       user_id: uuid.UUID | None = None,
                       allow_org_inherit: bool = False) -> tuple[bool, str]:
    rows = await list_live_entitlements(
        db, organization_id=organization_id, user_id=user_id)
    dicts = [{**entitlement_to_dict(r)} for r in rows]
    return ent_engine.has_access(
        entitlements=dicts, feature=feature,
        user_id=str(user_id or ""),
        organization_id=str(organization_id or ""),
        allow_org_inherit=allow_org_inherit)


# --------------------------------------------------------------------------
# Usage + quotas + credits
# --------------------------------------------------------------------------

async def record_usage(db: AsyncSession, *, meter_slug: str,
                       organization_id: uuid.UUID | None,
                       user_id: uuid.UUID | None = None,
                       quantity: float = 1, feature: str = "",
                       product_id: uuid.UUID | None = None,
                       source: str = "api",
                       idempotency_key: str = "",
                       occurred_at: datetime | None = None,
                       metadata: dict[str, Any] | None = None) -> UsageRecord:
    meter = (await db.execute(select(UsageMeter).where(
        UsageMeter.slug == meter_slug))).scalar_one_or_none()
    if meter is None or not meter.is_active:
        raise CommerceError("UNKNOWN_METER", f"unknown meter {meter_slug}")
    idem = idempotency_key or _idem("use")
    existing = (await db.execute(select(UsageRecord).where(
        UsageRecord.idempotency_key == idem))).scalar_one_or_none()
    if existing is not None:
        return existing
    row = UsageRecord(
        user_id=user_id, organization_id=organization_id, meter_id=meter.id,
        product_id=product_id, feature=feature, quantity=int(quantity),
        unit=meter.unit, source=source, dedup_key=idem,
        idempotency_key=idem, occurred_at=occurred_at or _now(),
        record_metadata=metadata or {})
    db.add(row)
    await db.flush()
    return row


async def aggregate_usage(db: AsyncSession, *, meter_slug: str,
                          organization_id: uuid.UUID | None,
                          period_start: datetime,
                          period_end: datetime) -> dict[str, Any]:
    meter = (await db.execute(select(UsageMeter).where(
        UsageMeter.slug == meter_slug))).scalar_one_or_none()
    if meter is None:
        raise CommerceError("UNKNOWN_METER", f"unknown meter {meter_slug}")
    stmt = select(UsageRecord).where(
        UsageRecord.meter_id == meter.id,
        UsageRecord.occurred_at >= period_start,
        UsageRecord.occurred_at < period_end)
    if organization_id is not None:
        stmt = stmt.where(UsageRecord.organization_id == organization_id)
    records = list((await db.execute(stmt)).scalars().all())
    dicts = [{"quantity": r.quantity, "dedup_key": r.dedup_key}
             for r in records]
    total = usage_lib.aggregate(dicts, aggregation=meter.aggregation)
    summary = (await db.execute(select(UsageSummary).where(
        UsageSummary.meter_id == meter.id,
        UsageSummary.organization_id == organization_id,
        UsageSummary.period_start == period_start))).scalar_one_or_none()
    if summary is None:
        summary = UsageSummary(
            organization_id=organization_id, meter_id=meter.id,
            period_start=period_start, period_end=period_end,
            total=int(total))
        db.add(summary)
    else:
        summary.total = int(total)
    await db.flush()
    return {"meter": meter_slug, "total": total, "events": len(records),
            "aggregation": meter.aggregation}


async def check_quota(db: AsyncSession, *, quota_id: uuid.UUID,
                      quantity: float = 1) -> tuple[bool, str, float]:
    quota = await db.get(Quota, quota_id)
    if quota is None:
        raise CommerceError("NOT_FOUND", "quota not found")
    period_start = _period_start(quota.period)
    usage = (await db.execute(select(QuotaUsage).where(
        QuotaUsage.quota_id == quota.id,
        QuotaUsage.period_start == period_start))).scalar_one_or_none()
    used = float(usage.used) if usage else 0.0
    return usage_lib.quota_decision(
        limit=None if quota.limit_value is None else float(quota.limit_value),
        used=used, requested=quantity)


async def consume_quota(db: AsyncSession, *, quota_id: uuid.UUID,
                        quantity: float = 1) -> dict[str, Any]:
    quota = await db.get(Quota, quota_id)
    if quota is None:
        raise CommerceError("NOT_FOUND", "quota not found")
    period_start = _period_start(quota.period)
    usage = (await db.execute(select(QuotaUsage).where(
        QuotaUsage.quota_id == quota.id,
        QuotaUsage.period_start == period_start).with_for_update()
    )).scalar_one_or_none()
    if usage is None:
        usage = QuotaUsage(quota_id=quota.id, period_start=period_start,
                           used=0)
        db.add(usage)
        await db.flush()
    allowed, reason, _ = usage_lib.quota_decision(
        limit=None if quota.limit_value is None else float(quota.limit_value),
        used=float(usage.used), requested=quantity)
    if not allowed:
        raise CommerceError("QUOTA_EXCEEDED", reason)
    usage.used = float(usage.used) + quantity
    await db.flush()
    return {"quota_id": str(quota.id), "used": usage.used,
            "limit": quota.limit_value}


def _period_start(period: str) -> datetime:
    now = _now()
    period = (period or "MONTHLY").upper()
    if period == "DAILY":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "YEARLY":
        return now.replace(month=1, day=1, hour=0, minute=0, second=0,
                           microsecond=0)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def credit_balance(db: AsyncSession, account_id: uuid.UUID) -> int:
    rows = (await db.execute(select(CreditTransaction).where(
        CreditTransaction.account_id == account_id))).scalars().all()
    balance = 0
    now = _now()
    for row in rows:
        if row.type in ("EXPIRE",) or (row.expires_at and row.expires_at < now
                                       and row.type in ("GRANT", "PURCHASE")):
            continue
        if row.type in ("GRANT", "PURCHASE", "REFUND", "ADJUSTMENT"):
            balance += int(row.amount)
        elif row.type in ("CONSUME", "EXPIRE"):
            balance -= abs(int(row.amount))
    return balance


async def credit_transaction(db: AsyncSession, *, account_id: uuid.UUID,
                             txn_type: str, amount: int, source: str = "",
                             idempotency_key: str = "",
                             expires_at: datetime | None = None) -> CreditTransaction:
    idem = idempotency_key or _idem("ctx")
    existing = (await db.execute(select(CreditTransaction).where(
        CreditTransaction.idempotency_key == idem))).scalar_one_or_none()
    if existing is not None:
        return existing
    if txn_type == "CONSUME":
        balance = await credit_balance(db, account_id)
        if balance < amount:
            raise CommerceError("INSUFFICIENT_CREDITS",
                                "credit balance too low")
    row = CreditTransaction(account_id=account_id, type=txn_type,
                            amount=amount, source=source,
                            expires_at=expires_at, idempotency_key=idem,
                            txn_metadata={})
    db.add(row)
    await db.flush()
    return row


# --------------------------------------------------------------------------
# Invoices / refunds / disputes
# --------------------------------------------------------------------------

async def create_invoice(db: AsyncSession, *, customer_id: uuid.UUID,
                         organization_id: uuid.UUID | None,
                         currency: str, lines: list[dict[str, Any]],
                         period_start: datetime | None = None,
                         period_end: datetime | None = None,
                         discount_minor: int = 0, tax_minor: int = 0,
                         idempotency_key: str = "") -> Invoice:
    currency = normalize_currency(currency)
    idem = idempotency_key or _idem("inv")
    existing = (await db.execute(select(Invoice).where(
        Invoice.idempotency_key == idem))).scalar_one_or_none()
    if existing is not None:
        return existing
    subtotal = 0
    for line in lines:
        qty = int(line.get("quantity", 1))
        unit = int(line.get("unit_price_minor", 0))
        if qty < 0 or unit < 0:
            raise CommerceError("BAD_AMOUNT", "invoice line must be >= 0")
        subtotal += qty * unit
    total = subtotal + tax_minor - discount_minor
    if total < 0:
        raise CommerceError("BAD_AMOUNT", "invoice total would go negative")
    invoice = Invoice(
        customer_id=customer_id, organization_id=organization_id,
        period_start=period_start, period_end=period_end, currency=currency,
        subtotal_minor=subtotal, tax_minor=tax_minor,
        discount_minor=discount_minor, total_minor=total, status="OPEN",
        idempotency_key=idem)
    db.add(invoice)
    await db.flush()
    for line in lines:
        qty = int(line.get("quantity", 1))
        unit = int(line.get("unit_price_minor", 0))
        db.add(InvoiceLine(
            invoice_id=invoice.id, product_id=line.get("product_id"),
            description=str(line.get("description", ""))[:500],
            quantity=qty, unit_price_minor=unit, amount_minor=qty * unit,
            line_metadata={}))
    await db.flush()
    return invoice


async def create_refund(db: AsyncSession, *, payment_id: uuid.UUID,
                        amount_minor: int | None, reason: str,
                        created_by: uuid.UUID | None,
                        idempotency_key: str = "") -> Refund:
    payment = await db.get(Payment, payment_id)
    if payment is None:
        raise CommerceError("NOT_FOUND", "payment not found")
    amount = payment.amount_minor if amount_minor is None else amount_minor
    if amount <= 0 or amount > payment.amount_minor:
        raise CommerceError("BAD_AMOUNT", "refund amount out of range")
    idem = idempotency_key or _idem("ref")
    existing = (await db.execute(select(Refund).where(
        Refund.idempotency_key == idem))).scalar_one_or_none()
    if existing is not None:
        return existing
    settings = get_commerce_settings()
    provider = get_billing_provider(mode=settings.normalized_mode(),
                                    webhook_secret=settings.BILLING_WEBHOOK_SECRET)
    result = await provider.refund(
        transaction_reference=payment.provider_reference,
        amount_minor=amount, reason=reason)
    row = Refund(payment_id=payment.id, amount_minor=amount, reason=reason,
                 provider=provider.name,
                 provider_reference=str(result.get("provider_refund_id", "")),
                 status="SUCCEEDED", idempotency_key=idem,
                 created_by=created_by)
    db.add(row)
    await _revoke_payment_entitlements(db, payment=payment,
                                      reason="refund issued")
    await db.flush()
    return row


# --------------------------------------------------------------------------
# Revenue / ledger / fee policy / payouts
# --------------------------------------------------------------------------

async def _record_sale_revenue(db: AsyncSession, *, payment: Payment,
                               payload: dict[str, Any]) -> str | None:
    if payment.product_id is None:
        return None
    product = await db.get(Product, payment.product_id)
    if product is None:
        return None
    publisher_id = getattr(product, "publisher_id", None) or payload.get(
        "publisher_id")
    if publisher_id is None:
        return None
    policies = list((await db.execute(select(FeePolicy).where(
        FeePolicy.is_active == True))).scalars().all())  # noqa: E712
    policy_dicts = [{"id": str(p.id), "marketplace": p.marketplace,
                     "product_type": p.product_type,
                     "publisher_type": p.publisher_type,
                     "rate_bps": p.rate_bps,
                     "fixed_fee_minor": p.fixed_fee_minor} for p in policies]
    resolved = ledger_lib.resolve_fee(
        policies=policy_dicts,
        marketplace=str(payload.get("marketplace", "")),
        product_type=str((product.product_metadata or {}).get(
            "mp24_product_type", product.product_type.value
            if hasattr(product.product_type, "value")
            else product.product_type)),
        publisher_type=str(payload.get("publisher_type", "")))
    discount = int(payload.get("discount_minor", 0))
    split = ledger_lib.split_revenue(
        gross_minor=payment.amount_minor, discount_minor=discount,
        platform_bps=resolved["platform_bps"],
        fixed_fee_minor=resolved["fixed_fee_minor"])
    ref = payment.provider_reference
    existing = (await db.execute(select(RevenueRecord).where(
        RevenueRecord.transaction_reference == ref))).scalar_one_or_none()
    if existing is None:
        db.add(RevenueRecord(
            publisher_id=publisher_id, product_id=product.id,
            transaction_reference=ref, gross_minor=split["gross"],
            fee_minor=split["platform_fee"],
            net_minor=split["creator_amount"], currency=payment.currency,
            status=RevenueStatus.PENDING))
        await db.flush()
    await _post_ledger(db, publisher_id=publisher_id, account="creator",
                       entry_type="CREDIT", amount_minor=split["creator_amount"],
                       currency=payment.currency, reference=ref,
                       reference_type="payment",
                       idem=f"ledger:credit:{ref}")
    await _post_ledger(db, publisher_id=publisher_id, account="platform_fee",
                       entry_type="FEE", amount_minor=split["platform_fee"],
                       currency=payment.currency, reference=ref,
                       reference_type="payment",
                       idem=f"ledger:fee:{ref}")
    revenue = (await db.execute(select(RevenueRecord).where(
        RevenueRecord.transaction_reference == ref))).scalar_one_or_none()
    return str(revenue.id) if revenue else None


async def _post_ledger(db: AsyncSession, *, publisher_id: Any,
                       account: str, entry_type: str, amount_minor: int,
                       currency: str, reference: str, reference_type: str,
                       idem: str) -> CreatorLedgerEntry:
    existing = (await db.execute(select(CreatorLedgerEntry).where(
        CreatorLedgerEntry.idempotency_key == idem))).scalar_one_or_none()
    if existing is not None:
        return existing
    row = CreatorLedgerEntry(
        publisher_id=publisher_id, account=account, type=entry_type,
        amount_minor=amount_minor, currency=currency, reference=reference,
        reference_type=reference_type, status="POSTED", idempotency_key=idem,
        entry_metadata={})
    db.add(row)
    await db.flush()
    return row


async def creator_balance(db: AsyncSession,
                          publisher_id: uuid.UUID) -> dict[str, int]:
    rows = (await db.execute(select(CreatorLedgerEntry).where(
        CreatorLedgerEntry.publisher_id == publisher_id,
        CreatorLedgerEntry.status == "POSTED"))).scalars().all()
    by_currency: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_currency.setdefault(row.currency, []).append(
            {"type": row.type, "amount_minor": row.amount_minor,
             "currency": row.currency})
    return {cur: ledger_lib.ledger_balance(entries, currency=cur)
            for cur, entries in by_currency.items()}


async def request_payout(db: AsyncSession, *, publisher_id: uuid.UUID,
                         amount_minor: int, currency: str,
                         destination_reference: str,
                         requested_by: uuid.UUID | None,
                         publisher_verified: bool = False,
                         require_verification: bool = True,
                         idempotency_key: str = "") -> CommercePayout:
    if amount_minor <= 0:
        raise CommerceError("BAD_AMOUNT", "payout amount must be > 0")
    currency = normalize_currency(currency)
    if not destination_reference:
        raise CommerceError("BAD_DESTINATION",
                            "destination reference required (never raw "
                            "bank credentials)")
    idem = idempotency_key or _idem("po")
    existing = (await db.execute(select(CommercePayout).where(
        CommercePayout.idempotency_key == idem))).scalar_one_or_none()
    if existing is not None:
        return existing
    balances = await creator_balance(db, publisher_id)
    available = balances.get(currency, 0)
    settings = get_commerce_settings()
    eligible, reason = ledger_lib.payout_eligibility(
        balance_minor=available,
        minimum_minor=settings.PAYOUT_MINIMUM_MINOR,
        publisher_verified=publisher_verified,
        require_verification=require_verification,
        open_disputes=0)
    if not eligible:
        raise CommerceError("PAYOUT_INELIGIBLE", reason)
    if amount_minor > available:
        raise CommerceError("INSUFFICIENT_BALANCE",
                            "payout exceeds creator balance")
    row = CommercePayout(
        publisher_id=publisher_id, amount_minor=amount_minor,
        currency=currency, destination_reference=destination_reference,
        provider="", provider_reference="", status="PENDING",
        requested_at=_now(), idempotency_key=idem, payout_metadata={},
        requested_by=requested_by)
    db.add(row)
    await db.flush()
    db.add(PayoutEvent(payout_id=row.id, event_type="PAYOUT_CREATED",
                       actor_user_id=requested_by, payload={"amount_minor": amount_minor}))
    # Mirror to legacy MP23 payouts table for the existing publisher UI.
    db.add(LegacyPayout(
        publisher_id=publisher_id, amount_minor=amount_minor,
        currency=currency, status=LegacyPayoutStatus.PENDING,
        provider_reference="", payout_metadata={"commerce_payout_id": str(row.id)}))
    await db.flush()
    return row


async def transition_payout(db: AsyncSession, payout_id: uuid.UUID, *,
                            target: str,
                            actor_user_id: uuid.UUID | None = None,
                            reason: str = "") -> CommercePayout:
    row = await db.get(CommercePayout, payout_id)
    if row is None:
        raise CommerceError("NOT_FOUND", "payout not found")
    if not can_transition_payout(row.status, target):
        raise CommerceError("BAD_TRANSITION",
                            f"payout {row.status} -> {target} illegal")
    if target == "PROCESSING":
        settings = get_commerce_settings()
        if settings.normalized_mode() == "mock":
            from openagent.commerce.providers import MockPayoutProvider
            result = await MockPayoutProvider().create_payout(
                publisher_id=str(row.publisher_id),
                amount_minor=row.amount_minor, currency=row.currency,
                destination_reference=row.destination_reference)
            row.provider = "mock"
            row.provider_reference = str(result["provider_payout_id"])
        else:
            raise CommerceError("PAYOUTS_DISABLED",
                                "payout provider not configured")
    row.status = target
    if target == "HELD":
        row.hold_reason = reason
    if target == "PAID":
        row.processed_at = _now()
        await _post_ledger(db, publisher_id=row.publisher_id,
                           account="creator", entry_type="PAYOUT",
                           amount_minor=row.amount_minor,
                           currency=row.currency,
                           reference=str(row.id), reference_type="payout",
                           idem=f"ledger:payout:{row.id}")
    db.add(PayoutEvent(payout_id=row.id, event_type=f"PAYOUT_{target}",
                       actor_user_id=actor_user_id,
                       payload={"reason": reason}))
    await db.flush()
    return row


# --------------------------------------------------------------------------
# Promotions
# --------------------------------------------------------------------------

async def redeem_promo(db: AsyncSession, *, code: str,
                       customer_id: uuid.UUID | None,
                       gross_minor: int, product_id: str = "",
                       checkout_session_id: uuid.UUID | None = None,
                       now: datetime | None = None) -> PromoRedemption:
    promo = (await db.execute(select(PromoCode).where(
        PromoCode.code == code.strip().upper()))).scalar_one_or_none()
    if promo is None or not promo.is_active:
        raise CommerceError("BAD_COUPON", "unknown or inactive coupon")
    promotion = await db.get(Promotion, promo.promotion_id)
    if promotion is None or not promotion.is_active:
        raise CommerceError("BAD_COUPON", "promotion inactive")
    prior_customer = (await db.execute(select(func.count()).select_from(
        PromoRedemption).where(
            PromoRedemption.promo_code_id == promo.id,
            PromoRedemption.customer_id == customer_id))).scalar() \
        if customer_id else 0
    from openagent.commerce import usage as usage_mod
    coupon = {"active": promo.is_active,
              "expires_at": promo.expires_at.isoformat() if promo.expires_at else "",
              "max_redemptions": promo.max_redemptions,
              "max_per_customer": promo.max_per_customer,
              "eligible_customers": promo.eligible_customers,
              "eligible_products": promo.eligible_products,
              "kind": promotion.kind,
              "percent_bps": promotion.percent_bps,
              "amount_minor": promotion.amount_minor}
    valid, reason = usage_mod.validate_coupon(
        coupon=coupon, now_iso=(now or _now()).isoformat(),
        customer_id=str(customer_id or ""), product_id=product_id,
        prior_redemptions=promo.redemption_count,
        customer_redemptions=int(prior_customer or 0))
    if not valid:
        raise CommerceError("COUPON_REJECTED", reason)
    discount = usage_mod.coupon_discount(coupon=coupon,
                                         gross_minor=gross_minor)
    redemption = PromoRedemption(
        promo_code_id=promo.id, customer_id=customer_id,
        checkout_session_id=checkout_session_id, discount_minor=discount,
        idempotency_key=_idem("promo"))
    db.add(redemption)
    promo.redemption_count = int(promo.redemption_count) + 1
    await db.flush()
    return redemption


# --------------------------------------------------------------------------
# Registries
# --------------------------------------------------------------------------

async def list_visible_registries(db: AsyncSession, *,
                                  organization_id: uuid.UUID | None = None,
                                  include_public: bool = True,
                                  limit: int = 100) -> list[MarketplaceRegistry]:
    stmt = select(MarketplaceRegistry).where(
        MarketplaceRegistry.enabled == True)  # noqa: E712
    if organization_id is None:
        if include_public:
            stmt = stmt.where(MarketplaceRegistry.is_public == True)  # noqa: E712
    else:
        org_col = getattr(MarketplaceRegistry, "organization_id", None)
        if org_col is not None:
            stmt = stmt.where(
                (MarketplaceRegistry.is_public == True) |  # noqa: E712
                (org_col == organization_id))
    return list((await db.execute(stmt.order_by(
        MarketplaceRegistry.created_at.desc()).limit(limit))).scalars().all())


async def record_registry_sync(db: AsyncSession, *,
                               registry_id: uuid.UUID,
                               status: str, packages_synced: int = 0,
                               error: str = "") -> RegistrySync:
    row = RegistrySync(registry_id=registry_id, status=status,
                       packages_synced=packages_synced, error=error,
                       started_at=_now(), finished_at=_now())
    db.add(row)
    await db.flush()
    return row


async def cache_registry_entry(db: AsyncSession, *, registry_id: uuid.UUID,
                               cache_key: str, kind: str,
                               payload: dict[str, Any], sha256: str = "",
                               ttl_seconds: int = 3600) -> RegistryCacheEntry:
    existing = (await db.execute(select(RegistryCacheEntry).where(
        RegistryCacheEntry.cache_key == cache_key))).scalar_one_or_none()
    expires = _now() + timedelta(seconds=ttl_seconds)
    if existing is not None:
        existing.payload = payload
        existing.sha256 = sha256
        existing.expires_at = expires
        await db.flush()
        return existing
    row = RegistryCacheEntry(
        registry_id=registry_id, cache_key=cache_key, kind=kind,
        payload=payload, sha256=sha256, expires_at=expires)
    db.add(row)
    await db.flush()
    return row


async def is_publisher_member(db: AsyncSession, *,
                              publisher_id: uuid.UUID,
                              user_id: uuid.UUID) -> bool:
    row = (await db.execute(select(PublisherMember).where(
        PublisherMember.publisher_id == publisher_id,
        PublisherMember.user_id == user_id))).scalar_one_or_none()
    return row is not None


async def publisher_revenue(db: AsyncSession, *,
                            publisher_id: uuid.UUID,
                            limit: int = 200) -> list[RevenueRecord]:
    return list((await db.execute(select(RevenueRecord).where(
        RevenueRecord.publisher_id == publisher_id).order_by(
            RevenueRecord.created_at.desc()).limit(limit))).scalars().all())
