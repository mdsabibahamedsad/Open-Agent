"""MP24 API part 2: subscriptions / entitlements / usage / quotas /
credits. Shared helpers live in ``commerce``; invoices, refunds, disputes,
revenue, payouts, promotions, webhooks and platform admin live in
``commerce_billing``."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from openagent.api.dependencies import get_current_org_context
from openagent.api.v1.commerce import (
    _audit,
    _commerce_error,
    _need,
    _not_found,
    _org_id,
)
from openagent.commerce import service as svc
from openagent.commerce.config import get_commerce_settings
from openagent.commerce.providers import CommerceError, get_billing_provider
from openagent.commerce.types import can_transition_subscription
from openagent.db.models.commerce import (
    BillingCustomer,
    CreditAccount,
    Quota,
    Subscription,
    UsageMeter,
)
from openagent.db.models.marketplace import (
    Price,
    Product,
)
from openagent.db.pagination import create_pagination_meta
from openagent.db.session import get_db
from openagent.schemas.base import ApiErrorResponse

subscriptions_router = APIRouter(prefix="/subscriptions",
                                 tags=["subscriptions"])
entitlements_router = APIRouter(prefix="/entitlements", tags=["entitlements"])
usage_router = APIRouter(prefix="/usage", tags=["usage"])
quotas_router = APIRouter(prefix="/quotas", tags=["quotas"])
credits_router = APIRouter(prefix="/credits", tags=["credits"])


# --------------------------------------------------------------------------
# Subscriptions
# --------------------------------------------------------------------------

class SubscriptionCreate(BaseModel):
    customer_id: UUID
    price_id: UUID
    trial_days: int = Field(default=0, ge=0, le=365)
    quantity: int = Field(default=1, ge=1, le=10000)


@subscriptions_router.get("", responses={401: {"model": ApiErrorResponse},
                                         403: {"model": ApiErrorResponse}})
async def list_subscriptions(
    request: Request, page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status_filter: Optional[str] = None,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "billing:read")
    stmt = select(Subscription).where(
        Subscription.organization_id == _org_id(auth_context))
    if status_filter:
        stmt = stmt.where(Subscription.status == status_filter.upper())
    total = (await db.execute(select(func.count()).select_from(
        stmt.subquery()))).scalar() or 0
    rows = list((await db.execute(stmt.order_by(
        Subscription.created_at.desc()).offset(
            (page - 1) * page_size).limit(page_size))).scalars().all())
    return {"data": [{
        "id": str(s.id), "status": s.status,
        "product_id": str(s.product_id) if s.product_id else None,
        "price_id": str(s.price_id) if s.price_id else None,
        "current_period_start": s.current_period_start.isoformat()
        if s.current_period_start else None,
        "current_period_end": s.current_period_end.isoformat()
        if s.current_period_end else None,
        "quantity": s.quantity} for s in rows],
        "meta": create_pagination_meta(page, page_size, total)}


@subscriptions_router.post("", status_code=status.HTTP_201_CREATED,
                           responses={400: {"model": ApiErrorResponse},
                                      401: {"model": ApiErrorResponse},
                                      403: {"model": ApiErrorResponse},
                                      404: {"model": ApiErrorResponse},
                                      409: {"model": ApiErrorResponse}})
async def create_subscription(
    request: Request, data: SubscriptionCreate,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "billing:create")
    customer = await db.get(BillingCustomer, data.customer_id)
    price = await db.get(Price, data.price_id)
    if customer is None or price is None:
        raise _not_found("Customer or price")
    if (customer.organization_id is not None
            and customer.organization_id != _org_id(auth_context)):
        raise HTTPException(status_code=403, detail={
            "error": "cross-tenant access denied", "code": "FORBIDDEN"})
    settings = get_commerce_settings()
    provider = get_billing_provider(mode=settings.normalized_mode(),
                                    webhook_secret=settings.BILLING_WEBHOOK_SECRET)
    try:
        created = await provider.create_subscription(
            provider_customer_id=customer.provider_customer_id,
            provider_price_id=str(price.id), trial_days=data.trial_days)
        row = Subscription(
            customer_id=customer.id,
            organization_id=_org_id(auth_context),
            product_id=price.product_id, price_id=price.id,
            provider=provider.name,
            provider_subscription_id=str(created["provider_subscription_id"]),
            status="TRIALING" if data.trial_days > 0 else "ACTIVE",
            quantity=data.quantity, subscription_metadata={"test_mode":
                settings.normalized_mode() == "mock"})
        db.add(row)
        await db.flush()
    except CommerceError as exc:
        raise _commerce_error(exc)
    await db.commit()
    await db.refresh(row)
    await _audit(db, organization_id=_org_id(auth_context),
                 actor=auth_context.user_id,
                 action="commerce.subscription.create", resource_id=row.id,
                 metadata={"status": row.status})
    return {"id": str(row.id), "status": row.status}


@subscriptions_router.post("/{subscription_id}/cancel",
                           responses={401: {"model": ApiErrorResponse},
                                      403: {"model": ApiErrorResponse},
                                      404: {"model": ApiErrorResponse},
                                      409: {"model": ApiErrorResponse}})
async def cancel_subscription(
    request: Request, subscription_id: UUID,
    at_period_end: bool = Query(True),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "billing:update")
    row = await db.get(Subscription, subscription_id)
    if row is None:
        raise _not_found("Subscription")
    if (row.organization_id is not None
            and row.organization_id != _org_id(auth_context)):
        raise HTTPException(status_code=403, detail={
            "error": "cross-tenant access denied", "code": "FORBIDDEN"})
    settings = get_commerce_settings()
    provider = get_billing_provider(mode=settings.normalized_mode(),
                                    webhook_secret=settings.BILLING_WEBHOOK_SECRET)
    try:
        await provider.cancel_subscription(
            provider_subscription_id=row.provider_subscription_id,
            at_period_end=at_period_end)
    except CommerceError as exc:
        raise _commerce_error(exc)
    if can_transition_subscription(row.status, "CANCELLED"):
        row.status = "CANCELLED"
    else:
        row.subscription_metadata = {**row.subscription_metadata,
                                     "cancel_requested": True,
                                     "at_period_end": at_period_end}
    await db.commit()
    await _audit(db, organization_id=_org_id(auth_context),
                 actor=auth_context.user_id,
                 action="commerce.subscription.cancel", resource_id=row.id,
                 metadata={"at_period_end": at_period_end})
    return {"id": str(row.id), "status": row.status}


# --------------------------------------------------------------------------
# Entitlements
# --------------------------------------------------------------------------

class EntitlementGrant(BaseModel):
    product_id: UUID
    organization_id: Optional[UUID] = None
    user_id: Optional[UUID] = None
    features: list[str] = Field(default_factory=lambda: ["package.install"])
    source: str = Field(default="GRANT")
    valid_until: Optional[datetime] = None
    quantity: Optional[int] = None
    inherited: bool = False


@entitlements_router.get("", responses={401: {"model": ApiErrorResponse},
                                        403: {"model": ApiErrorResponse}})
async def list_entitlements(
    request: Request, product_id: Optional[UUID] = None,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "billing:read")
    rows = await svc.list_live_entitlements(
        db, organization_id=_org_id(auth_context), product_id=product_id)
    return {"data": [svc.entitlement_to_dict(r) for r in rows]}


@entitlements_router.get("/check",
                         responses={401: {"model": ApiErrorResponse},
                                    403: {"model": ApiErrorResponse}})
async def check_entitlement(
    request: Request, feature: str = Query("package.install"),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "billing:read")
    allowed, reason = await svc.check_access(
        db, feature=feature, organization_id=_org_id(auth_context),
        user_id=auth_context.user_id)
    return {"feature": feature, "allowed": allowed, "reason": reason}


@entitlements_router.post("/grant", status_code=status.HTTP_201_CREATED,
                          responses={400: {"model": ApiErrorResponse},
                                     401: {"model": ApiErrorResponse},
                                     403: {"model": ApiErrorResponse},
                                     404: {"model": ApiErrorResponse}})
async def grant_entitlement(
    request: Request, data: EntitlementGrant,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Manual grant (ADMIN/GRANT source). Purchases/subscriptions grant via
    verified webhooks only — this endpoint cannot forge those sources."""
    await _need(request, db, "billing:manage")
    if data.source.upper() in ("PURCHASE", "SUBSCRIPTION"):
        raise HTTPException(status_code=400, detail={
            "error": "PURCHASE/SUBSCRIPTION entitlements are granted from "
                     "verified payment events only",
            "code": "FORGED_SOURCE"})
    product = await db.get(Product, data.product_id)
    if product is None:
        raise _not_found("Product")
    entitlement_id = await svc.grant_entitlement(
        db, product=product, source=data.source.upper(),
        organization_id=data.organization_id or _org_id(auth_context),
        user_id=data.user_id, features=data.features, status="ACTIVE",
        valid_until=data.valid_until, quantity=data.quantity,
        inherited=data.inherited)
    await db.commit()
    await _audit(db, organization_id=_org_id(auth_context),
                 actor=auth_context.user_id,
                 action="commerce.entitlement.grant",
                 resource_id=entitlement_id,
                 metadata={"source": data.source})
    return {"id": entitlement_id, "status": "ACTIVE"}


@entitlements_router.post("/{entitlement_id}/revoke",
                          responses={401: {"model": ApiErrorResponse},
                                     403: {"model": ApiErrorResponse},
                                     404: {"model": ApiErrorResponse}})
async def revoke_entitlement(
    request: Request, entitlement_id: UUID,
    reason: str = Query(""),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "billing:manage")
    try:
        row = await svc.revoke_entitlement(db, entitlement_id, reason=reason)
    except CommerceError as exc:
        raise _commerce_error(exc)
    await db.commit()
    await _audit(db, organization_id=_org_id(auth_context),
                 actor=auth_context.user_id,
                 action="commerce.entitlement.revoke",
                 resource_id=row.id, metadata={"reason": reason})
    return {"id": str(row.id), "status": row.status}


# --------------------------------------------------------------------------
# Usage + quotas + credits
# --------------------------------------------------------------------------

class UsageRecordCreate(BaseModel):
    meter: str = Field(min_length=1, max_length=100)
    quantity: float = Field(default=1, ge=0)
    feature: str = Field(default="", max_length=255)
    idempotency_key: str = Field(default="", max_length=255)
    metadata: dict[str, Any] = Field(default_factory=dict)


@usage_router.get("/meters", responses={401: {"model": ApiErrorResponse},
                                        403: {"model": ApiErrorResponse}})
async def list_meters(
    request: Request,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "billing:read")
    rows = list((await db.execute(select(UsageMeter).where(
        UsageMeter.is_active == True))).scalars().all())  # noqa: E712
    return {"data": [{
        "slug": m.slug, "name": m.name, "unit": m.unit,
        "aggregation": m.aggregation, "reset_period": m.reset_period}
        for m in rows]}


@usage_router.post("", status_code=status.HTTP_201_CREATED,
                   responses={400: {"model": ApiErrorResponse},
                              401: {"model": ApiErrorResponse},
                              403: {"model": ApiErrorResponse}})
async def record_usage(
    request: Request, data: UsageRecordCreate,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "billing:create")
    try:
        row = await svc.record_usage(
            db, meter_slug=data.meter,
            organization_id=_org_id(auth_context),
            user_id=auth_context.user_id, quantity=data.quantity,
            feature=data.feature, idempotency_key=data.idempotency_key,
            metadata=data.metadata)
    except CommerceError as exc:
        raise _commerce_error(exc)
    await db.commit()
    return {"id": str(row.id), "meter": data.meter,
            "quantity": data.quantity}


@usage_router.get("/summary", responses={401: {"model": ApiErrorResponse},
                                         403: {"model": ApiErrorResponse}})
async def usage_summary(
    request: Request, meter: str = Query(...),
    period_start: datetime = Query(...), period_end: datetime = Query(...),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "billing:read")
    try:
        result = await svc.aggregate_usage(
            db, meter_slug=meter, organization_id=_org_id(auth_context),
            period_start=period_start, period_end=period_end)
    except CommerceError as exc:
        raise _commerce_error(exc)
    await db.commit()
    return result


class QuotaCreate(BaseModel):
    meter: str = Field(min_length=1, max_length=100)
    limit_value: Optional[float] = Field(default=None, ge=0)
    period: str = Field(default="MONTHLY")
    product_id: Optional[UUID] = None


@quotas_router.get("", responses={401: {"model": ApiErrorResponse},
                                  403: {"model": ApiErrorResponse}})
async def list_quotas(
    request: Request,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "billing:read")
    rows = list((await db.execute(select(Quota).where(
        Quota.organization_id == _org_id(auth_context)))).scalars().all())
    return {"data": [{
        "id": str(q.id), "meter_id": str(q.meter_id),
        "limit_value": q.limit_value, "period": q.period} for q in rows]}


@quotas_router.post("", status_code=status.HTTP_201_CREATED,
                    responses={400: {"model": ApiErrorResponse},
                               401: {"model": ApiErrorResponse},
                               403: {"model": ApiErrorResponse},
                               404: {"model": ApiErrorResponse}})
async def create_quota(
    request: Request, data: QuotaCreate,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "billing:manage")
    meter = (await db.execute(select(UsageMeter).where(
        UsageMeter.slug == data.meter))).scalar_one_or_none()
    if meter is None:
        raise _not_found("Usage meter")
    row = Quota(organization_id=_org_id(auth_context), meter_id=meter.id,
                product_id=data.product_id, limit_value=data.limit_value,
                period=data.period.upper(), quota_metadata={})
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {"id": str(row.id), "limit_value": row.limit_value}


@quotas_router.get("/{quota_id}/check",
                   responses={401: {"model": ApiErrorResponse},
                              403: {"model": ApiErrorResponse},
                              404: {"model": ApiErrorResponse}})
async def check_quota(
    request: Request, quota_id: UUID, quantity: float = Query(1, ge=0),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "billing:read")
    quota = await db.get(Quota, quota_id)
    if quota is None:
        raise _not_found("Quota")
    if (quota.organization_id is not None
            and quota.organization_id != _org_id(auth_context)):
        raise HTTPException(status_code=403, detail={
            "error": "cross-tenant access denied", "code": "FORBIDDEN"})
    try:
        allowed, reason, remaining = await svc.check_quota(
            db, quota_id=quota.id, quantity=quantity)
    except CommerceError as exc:
        raise _commerce_error(exc)
    return {"allowed": allowed, "reason": reason,
            "remaining": remaining}


@quotas_router.post("/{quota_id}/consume",
                    responses={401: {"model": ApiErrorResponse},
                               403: {"model": ApiErrorResponse},
                               404: {"model": ApiErrorResponse},
                               409: {"model": ApiErrorResponse}})
async def consume_quota(
    request: Request, quota_id: UUID, quantity: float = Query(1, ge=0),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "billing:create")
    quota = await db.get(Quota, quota_id)
    if quota is None:
        raise _not_found("Quota")
    if (quota.organization_id is not None
            and quota.organization_id != _org_id(auth_context)):
        raise HTTPException(status_code=403, detail={
            "error": "cross-tenant access denied", "code": "FORBIDDEN"})
    try:
        result = await svc.consume_quota(db, quota_id=quota.id,
                                         quantity=quantity)
    except CommerceError as exc:
        raise _commerce_error(exc)
    await db.commit()
    return result


class CreditGrant(BaseModel):
    amount: int = Field(gt=0)
    source: str = Field(default="GRANT", max_length=64)
    expires_at: Optional[datetime] = None
    idempotency_key: str = Field(default="", max_length=255)


@credits_router.get("", responses={401: {"model": ApiErrorResponse},
                                   403: {"model": ApiErrorResponse}})
async def credit_balances(
    request: Request,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "billing:read")
    accounts = list((await db.execute(select(CreditAccount).where(
        CreditAccount.organization_id == _org_id(auth_context)))).scalars().all())
    data = []
    for account in accounts:
        balance = await svc.credit_balance(db, account.id)
        data.append({"id": str(account.id), "balance": balance,
                     "currency": account.currency})
    return {"data": data}


@credits_router.post("/grant", status_code=status.HTTP_201_CREATED,
                     responses={400: {"model": ApiErrorResponse},
                                401: {"model": ApiErrorResponse},
                                403: {"model": ApiErrorResponse}})
async def grant_credits(
    request: Request, data: CreditGrant,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "billing:manage")
    account = (await db.execute(select(CreditAccount).where(
        CreditAccount.organization_id == _org_id(auth_context)))).scalar_one_or_none()
    if account is None:
        account = CreditAccount(organization_id=_org_id(auth_context),
                                user_id=None, currency="CREDITS")
        db.add(account)
        await db.flush()
    txn = await svc.credit_transaction(
        db, account_id=account.id, txn_type="GRANT", amount=data.amount,
        source=data.source, idempotency_key=data.idempotency_key,
        expires_at=data.expires_at)
    await db.commit()
    await _audit(db, organization_id=_org_id(auth_context),
                 actor=auth_context.user_id,
                 action="commerce.credit.grant", resource_id=txn.id,
                 metadata={"amount": data.amount})
    return {"id": str(txn.id), "amount": data.amount}


@credits_router.post("/consume",
                     responses={400: {"model": ApiErrorResponse},
                                401: {"model": ApiErrorResponse},
                                403: {"model": ApiErrorResponse},
                                409: {"model": ApiErrorResponse}})
async def consume_credits(
    request: Request, amount: int = Query(..., gt=0),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "billing:create")
    account = (await db.execute(select(CreditAccount).where(
        CreditAccount.organization_id == _org_id(auth_context)))).scalar_one_or_none()
    if account is None:
        raise HTTPException(status_code=409, detail={
            "error": "no credit account", "code": "NO_ACCOUNT"})
    try:
        txn = await svc.credit_transaction(
            db, account_id=account.id, txn_type="CONSUME", amount=amount,
            source="api")
    except CommerceError as exc:
        raise _commerce_error(exc)
    await db.commit()
    return {"id": str(txn.id), "consumed": amount}
