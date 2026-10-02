"""MP24 API part 3: invoices / refunds / disputes / revenue / ledger /
payouts / promotions / webhooks / platform admin."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from openagent.api.dependencies import (
    get_current_org_context,
    require_platform_owner,
)
from openagent.api.v1.commerce import (
    _audit,
    _commerce_error,
    _need,
    _not_found,
    _org_id,
    _rate_limited,
)
from openagent.commerce import service as svc
from openagent.commerce.money import normalize_currency
from openagent.commerce.providers import CommerceError
from openagent.db.models.commerce import (
    BillingCustomer,
    CommercePayout,
    CreatorLedgerEntry,
    Dispute,
    FeePolicy,
    Invoice,
    InvoiceLine,
    Payment,
    PromoCode,
    Promotion,
    Refund,
    Subscription,
)
from openagent.db.models.marketplace import BillingWebhookEvent
from openagent.db.models.package import PublisherProfile
from openagent.db.pagination import create_pagination_meta
from openagent.db.session import get_db
from openagent.schemas.base import ApiErrorResponse

invoices_router = APIRouter(prefix="/invoices", tags=["invoices"])
refunds_router = APIRouter(prefix="/refunds", tags=["refunds"])
disputes_router = APIRouter(prefix="/disputes", tags=["disputes"])
revenue_router = APIRouter(prefix="/revenue", tags=["revenue"])
payouts_router = APIRouter(prefix="/payouts", tags=["payouts"])
promotions_router = APIRouter(prefix="/promotions", tags=["promotions"])
webhooks_router = APIRouter(prefix="/webhooks/billing",
                            tags=["billing-webhooks"])
master_billing_router = APIRouter(prefix="/master/billing",
                                  tags=["billing-admin"])


# --------------------------------------------------------------------------
# Invoices
# --------------------------------------------------------------------------

class InvoiceLineCreate(BaseModel):
    product_id: Optional[UUID] = None
    description: str = Field(default="", max_length=500)
    quantity: int = Field(default=1, ge=0)
    unit_price: str = Field(default="0.00")


class InvoiceCreate(BaseModel):
    customer_id: UUID
    currency: str = Field(default="USD", min_length=3, max_length=3)
    lines: list[InvoiceLineCreate] = Field(min_length=1)
    discount: str = Field(default="0.00")
    tax: str = Field(default="0.00")
    idempotency_key: str = Field(default="", max_length=255)


@invoices_router.get("", responses={401: {"model": ApiErrorResponse},
                                    403: {"model": ApiErrorResponse}})
async def list_invoices(
    request: Request, page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "billing:read")
    stmt = select(Invoice).where(
        Invoice.organization_id == _org_id(auth_context))
    total = (await db.execute(select(func.count()).select_from(
        stmt.subquery()))).scalar() or 0
    rows = list((await db.execute(stmt.order_by(Invoice.created_at.desc())
                 .offset((page - 1) * page_size).limit(page_size))).scalars().all())
    return {"data": [{
        "id": str(i.id), "currency": i.currency,
        "subtotal_minor": i.subtotal_minor, "tax_minor": i.tax_minor,
        "discount_minor": i.discount_minor, "total_minor": i.total_minor,
        "status": i.status} for i in rows],
        "meta": create_pagination_meta(page, page_size, total)}


@invoices_router.post("", status_code=status.HTTP_201_CREATED,
                      responses={400: {"model": ApiErrorResponse},
                                 401: {"model": ApiErrorResponse},
                                 403: {"model": ApiErrorResponse},
                                 404: {"model": ApiErrorResponse}})
async def create_invoice(
    request: Request, data: InvoiceCreate,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "billing:manage")
    customer = await db.get(BillingCustomer, data.customer_id)
    if customer is None:
        raise _not_found("Billing customer")
    if (customer.organization_id is not None
            and customer.organization_id != _org_id(auth_context)):
        raise HTTPException(status_code=403, detail={
            "error": "cross-tenant access denied", "code": "FORBIDDEN"})
    try:
        from openagent.commerce.money import parse_amount
        lines = [{"product_id": line.product_id,
                  "description": line.description,
                  "quantity": line.quantity,
                  "unit_price_minor": parse_amount(line.unit_price,
                                                   data.currency)}
                 for line in data.lines]
        invoice = await svc.create_invoice(
            db, customer_id=customer.id,
            organization_id=_org_id(auth_context), currency=data.currency,
            lines=lines,
            discount_minor=parse_amount(data.discount, data.currency),
            tax_minor=parse_amount(data.tax, data.currency),
            idempotency_key=data.idempotency_key)
    except CommerceError as exc:
        raise _commerce_error(exc)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={
            "error": str(exc), "code": "BAD_AMOUNT"})
    await db.commit()
    await db.refresh(invoice)
    await _audit(db, organization_id=_org_id(auth_context),
                 actor=auth_context.user_id,
                 action="commerce.invoice.create", resource_id=invoice.id,
                 metadata={"total_minor": invoice.total_minor})
    return {"id": str(invoice.id), "total_minor": invoice.total_minor,
            "status": invoice.status}


@invoices_router.get("/{invoice_id}",
                     responses={401: {"model": ApiErrorResponse},
                                403: {"model": ApiErrorResponse},
                                404: {"model": ApiErrorResponse}})
async def get_invoice(
    request: Request, invoice_id: UUID,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Secure invoice retrieval: org-scoped, authenticated, no public links."""
    await _need(request, db, "billing:read")
    invoice = await db.get(Invoice, invoice_id)
    if invoice is None:
        raise _not_found("Invoice")
    if (invoice.organization_id is not None
            and invoice.organization_id != _org_id(auth_context)
            and not auth_context.is_platform_owner):
        raise HTTPException(status_code=403, detail={
            "error": "cross-tenant access denied", "code": "FORBIDDEN"})
    lines = list((await db.execute(select(InvoiceLine).where(
        InvoiceLine.invoice_id == invoice.id))).scalars().all())
    return {"id": str(invoice.id), "currency": invoice.currency,
            "subtotal_minor": invoice.subtotal_minor,
            "tax_minor": invoice.tax_minor,
            "discount_minor": invoice.discount_minor,
            "total_minor": invoice.total_minor, "status": invoice.status,
            "lines": [{
                "description": line.description, "quantity": line.quantity,
                "unit_price_minor": line.unit_price_minor,
                "amount_minor": line.amount_minor} for line in lines]}


@invoices_router.post("/{invoice_id}/pay",
                      responses={400: {"model": ApiErrorResponse},
                                 401: {"model": ApiErrorResponse},
                                 403: {"model": ApiErrorResponse},
                                 404: {"model": ApiErrorResponse},
                                 409: {"model": ApiErrorResponse}})
async def pay_invoice(
    request: Request, invoice_id: UUID,
    payment_reference: str = Query(...,
                                   description="Verified provider payment "
                                   "reference covering the invoice total"),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Mark an invoice paid only from a verified SUCCEEDED payment.

    The caller supplies a provider payment reference; the endpoint loads
    the verified payment row (created exclusively by the webhook path) and
    requires status SUCCEEDED with amount >= invoice total. Frontend-only
    success claims are never accepted.
    """
    await _need(request, db, "billing:manage")
    invoice = await db.get(Invoice, invoice_id)
    if invoice is None:
        raise _not_found("Invoice")
    if invoice.status == "PAID":
        return {"id": str(invoice.id), "status": "PAID",
                "deduplicated": True}
    payment = (await db.execute(select(Payment).where(
        Payment.provider_reference == payment_reference))).scalar_one_or_none()
    if payment is None or payment.status != "SUCCEEDED":
        raise HTTPException(status_code=409, detail={
            "error": "no verified SUCCEEDED payment for this reference",
            "code": "PAYMENT_NOT_VERIFIED"})
    if payment.amount_minor < invoice.total_minor:
        raise HTTPException(status_code=409, detail={
            "error": "verified payment does not cover the invoice total",
            "code": "INSUFFICIENT_PAYMENT"})
    invoice.status = "PAID"
    await db.commit()
    await _audit(db, organization_id=_org_id(auth_context),
                 actor=auth_context.user_id,
                 action="commerce.invoice.paid", resource_id=invoice.id,
                 metadata={"total_minor": invoice.total_minor,
                           "payment_id": str(payment.id)})
    return {"id": str(invoice.id), "status": "PAID"}


# --------------------------------------------------------------------------
# Refunds / disputes
# --------------------------------------------------------------------------

class RefundCreate(BaseModel):
    payment_id: UUID
    amount: Optional[str] = Field(default=None,
                                  description="Decimal string; null = full")
    reason: str = Field(default="", max_length=1000)
    idempotency_key: str = Field(default="", max_length=255)


@refunds_router.get("", responses={401: {"model": ApiErrorResponse},
                                   403: {"model": ApiErrorResponse}})
async def list_refunds(
    request: Request,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "billing:read")
    rows = list((await db.execute(select(Refund).order_by(
        Refund.created_at.desc()).limit(100))).scalars().all())
    # Only refunds for this org's payments (publisher isolation: no amounts
    # from other tenants leak).
    payments = {str(p.id): p for p in (await db.execute(select(Payment).where(
        Payment.id.in_([r.payment_id for r in rows])))).scalars().all()} \
        if rows else {}
    data = []
    for r in rows:
        payment = payments.get(str(r.payment_id))
        if (payment is not None and payment.organization_id is not None
                and payment.organization_id != _org_id(auth_context)
                and not auth_context.is_platform_owner):
            continue
        data.append({"id": str(r.id),
                     "payment_id": str(r.payment_id),
                     "amount_minor": r.amount_minor, "status": r.status,
                     "reason": r.reason})
    return {"data": data}


@refunds_router.post("", status_code=status.HTTP_201_CREATED,
                     responses={400: {"model": ApiErrorResponse},
                                401: {"model": ApiErrorResponse},
                                403: {"model": ApiErrorResponse},
                                404: {"model": ApiErrorResponse},
                                409: {"model": ApiErrorResponse}})
async def create_refund(
    request: Request, data: RefundCreate,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "billing:manage")
    payment = await db.get(Payment, data.payment_id)
    if payment is None:
        raise _not_found("Payment")
    if (payment.organization_id is not None
            and payment.organization_id != _org_id(auth_context)
            and not auth_context.is_platform_owner):
        raise HTTPException(status_code=403, detail={
            "error": "cross-tenant access denied", "code": "FORBIDDEN"})
    try:
        from openagent.commerce.money import parse_amount
        amount_minor = (parse_amount(data.amount, payment.currency)
                        if data.amount is not None else None)
        refund = await svc.create_refund(
            db, payment_id=payment.id, amount_minor=amount_minor,
            reason=data.reason, created_by=auth_context.user_id,
            idempotency_key=data.idempotency_key)
    except CommerceError as exc:
        raise _commerce_error(exc)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={
            "error": str(exc), "code": "BAD_AMOUNT"})
    await db.commit()
    await _audit(db, organization_id=_org_id(auth_context),
                 actor=auth_context.user_id,
                 action="commerce.refund.create", resource_id=refund.id,
                 metadata={"amount_minor": refund.amount_minor})
    return {"id": str(refund.id), "status": refund.status,
            "amount_minor": refund.amount_minor}


@disputes_router.get("", responses={401: {"model": ApiErrorResponse},
                                    403: {"model": ApiErrorResponse}})
async def list_disputes(
    request: Request,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "billing:read")
    rows = list((await db.execute(select(Dispute).order_by(
        Dispute.created_at.desc()).limit(100))).scalars().all())
    return {"data": [{
        "id": str(d.id), "status": d.status, "reason": d.reason,
        "amount_minor": d.amount_minor, "currency": d.currency,
        "resolved_at": d.resolved_at.isoformat() if d.resolved_at else None}
        for d in rows]}


# --------------------------------------------------------------------------
# Revenue / ledger / fee policy (publisher isolation enforced)
# --------------------------------------------------------------------------

async def _require_publisher_access(db: AsyncSession, publisher_id: UUID,
                                    auth_context) -> PublisherProfile:
    publisher = await db.get(PublisherProfile, publisher_id)
    if publisher is None:
        raise _not_found("Publisher")
    if auth_context.is_platform_owner:
        return publisher
    member = await svc.is_publisher_member(
        db, publisher_id=publisher_id, user_id=auth_context.user_id)
    if not member:
        raise HTTPException(status_code=403, detail={
            "error": "publisher membership required", "code": "FORBIDDEN"})
    return publisher


@revenue_router.get("", responses={401: {"model": ApiErrorResponse},
                                   403: {"model": ApiErrorResponse},
                                   404: {"model": ApiErrorResponse}})
async def publisher_revenue(
    request: Request, publisher_id: UUID = Query(...),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "payout:read")
    await _require_publisher_access(db, publisher_id, auth_context)
    rows = await svc.publisher_revenue(db, publisher_id=publisher_id)
    balances = await svc.creator_balance(db, publisher_id)
    return {"data": [{
        "id": str(r.id), "gross_minor": r.gross_minor,
        "fee_minor": r.fee_minor, "net_minor": r.net_minor,
        "currency": r.currency, "status": r.status.value
        if hasattr(r.status, "value") else str(r.status),
        "transaction_reference": r.transaction_reference} for r in rows],
        "balances": balances}


@revenue_router.get("/ledger", responses={401: {"model": ApiErrorResponse},
                                          403: {"model": ApiErrorResponse}})
async def publisher_ledger(
    request: Request, publisher_id: UUID = Query(...),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "payout:read")
    await _require_publisher_access(db, publisher_id, auth_context)
    rows = list((await db.execute(select(CreatorLedgerEntry).where(
        CreatorLedgerEntry.publisher_id == publisher_id).order_by(
            CreatorLedgerEntry.created_at.desc()).limit(200))).scalars().all())
    return {"data": [{
        "id": str(e.id), "account": e.account, "type": e.type,
        "amount_minor": e.amount_minor, "currency": e.currency,
        "reference": e.reference, "reference_type": e.reference_type,
        "status": e.status} for e in rows]}


@revenue_router.get("/fee-policies",
                    responses={401: {"model": ApiErrorResponse},
                               403: {"model": ApiErrorResponse}})
async def list_fee_policies(
    request: Request,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "payout:read")
    rows = list((await db.execute(select(FeePolicy).where(
        FeePolicy.is_active == True))).scalars().all())  # noqa: E712
    return {"data": [{
        "id": str(p.id), "marketplace": p.marketplace,
        "product_type": p.product_type, "publisher_type": p.publisher_type,
        "rate_bps": p.rate_bps, "fixed_fee_minor": p.fixed_fee_minor,
        "currency": p.currency} for p in rows]}


class FeePolicyCreate(BaseModel):
    marketplace: str = Field(default="", max_length=100)
    product_type: str = Field(default="", max_length=32)
    publisher_type: str = Field(default="", max_length=32)
    rate_bps: int = Field(ge=0, le=10000)
    fixed_fee_minor: int = Field(default=0, ge=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)


@revenue_router.post("/fee-policies", status_code=status.HTTP_201_CREATED,
                     responses={400: {"model": ApiErrorResponse},
                                401: {"model": ApiErrorResponse},
                                403: {"model": ApiErrorResponse}})
async def create_fee_policy(
    request: Request, data: FeePolicyCreate,
    auth_context=Depends(require_platform_owner),
    db: AsyncSession = Depends(get_db),
):
    row = FeePolicy(
        marketplace=data.marketplace, product_type=data.product_type.upper(),
        publisher_type=data.publisher_type.upper(), rate_bps=data.rate_bps,
        fixed_fee_minor=data.fixed_fee_minor,
        currency=normalize_currency(data.currency), is_active=True)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {"id": str(row.id), "rate_bps": row.rate_bps}


# --------------------------------------------------------------------------
# Payouts
# --------------------------------------------------------------------------

class PayoutCreate(BaseModel):
    publisher_id: UUID
    amount: str = Field(description="Decimal string, e.g. '25.00'")
    currency: str = Field(default="USD", min_length=3, max_length=3)
    destination_reference: str = Field(min_length=1, max_length=255,
                                       description="Provider destination "
                                       "handle — never raw bank credentials")
    idempotency_key: str = Field(default="", max_length=255)


@payouts_router.get("", responses={401: {"model": ApiErrorResponse},
                                   403: {"model": ApiErrorResponse}})
async def list_payouts(
    request: Request, publisher_id: Optional[UUID] = None,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "payout:read")
    stmt = select(CommercePayout)
    if publisher_id:
        await _require_publisher_access(db, publisher_id, auth_context)
        stmt = stmt.where(CommercePayout.publisher_id == publisher_id)
    elif not auth_context.is_platform_owner:
        raise HTTPException(status_code=400, detail={
            "error": "publisher_id is required", "code": "BAD_REQUEST"})
    rows = list((await db.execute(stmt.order_by(
        CommercePayout.created_at.desc()).limit(100))).scalars().all())
    return {"data": [{
        "id": str(p.id), "publisher_id": str(p.publisher_id),
        "amount_minor": p.amount_minor, "currency": p.currency,
        "status": p.status, "hold_reason": p.hold_reason,
        "provider_reference": p.provider_reference} for p in rows]}


@payouts_router.post("", status_code=status.HTTP_201_CREATED,
                     responses={400: {"model": ApiErrorResponse},
                                401: {"model": ApiErrorResponse},
                                403: {"model": ApiErrorResponse},
                                404: {"model": ApiErrorResponse},
                                409: {"model": ApiErrorResponse}})
async def request_payout(
    request: Request, data: PayoutCreate,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "payout:create")
    publisher = await _require_publisher_access(db, data.publisher_id,
                                                auth_context)
    lowered = data.destination_reference.lower()
    if any(secret in lowered for secret in
           ("iban de", "account_number", "routing", "sort-code", "cvv")):
        raise HTTPException(status_code=400, detail={
            "error": "destination must be a provider handle, never raw "
                     "bank credentials",
            "code": "RAW_CREDENTIALS"})
    verified = str(getattr(publisher, "verification_status",
                           "UNVERIFIED")).upper() in ("VERIFIED", "OFFICIAL")
    try:
        from openagent.commerce.money import parse_amount
        payout = await svc.request_payout(
            db, publisher_id=data.publisher_id,
            amount_minor=parse_amount(data.amount, data.currency),
            currency=data.currency,
            destination_reference=data.destination_reference,
            requested_by=auth_context.user_id,
            publisher_verified=verified,
            require_verification=True,
            idempotency_key=data.idempotency_key)
    except CommerceError as exc:
        raise _commerce_error(exc)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={
            "error": str(exc), "code": "BAD_AMOUNT"})
    await db.commit()
    await db.refresh(payout)
    await _audit(db, organization_id=_org_id(auth_context),
                 actor=auth_context.user_id,
                 action="commerce.payout.request", resource_id=payout.id,
                 metadata={"amount_minor": payout.amount_minor})
    return {"id": str(payout.id), "status": payout.status}


@payouts_router.post("/{payout_id}/transition",
                     responses={400: {"model": ApiErrorResponse},
                                401: {"model": ApiErrorResponse},
                                403: {"model": ApiErrorResponse},
                                404: {"model": ApiErrorResponse},
                                409: {"model": ApiErrorResponse}})
async def transition_payout(
    request: Request, payout_id: UUID, target: str = Query(...),
    reason: str = Query(""),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Payout state machine. PROCESSING/PAID/HELD require payout:manage
    (platform or publisher admin); every transition is audited."""
    await _need(request, db, "payout:manage")
    payout = await db.get(CommercePayout, payout_id)
    if payout is None:
        raise _not_found("Payout")
    if not auth_context.is_platform_owner:
        await _require_publisher_access(db, payout.publisher_id,
                                        auth_context)
    try:
        row = await svc.transition_payout(
            db, payout_id, target=target.upper(),
            actor_user_id=auth_context.user_id, reason=reason)
    except CommerceError as exc:
        raise _commerce_error(exc)
    await db.commit()
    await _audit(db, organization_id=_org_id(auth_context),
                 actor=auth_context.user_id,
                 action=f"commerce.payout.{target.lower()}",
                 resource_id=row.id, metadata={"reason": reason})
    return {"id": str(row.id), "status": row.status}


# --------------------------------------------------------------------------
# Promotions
# --------------------------------------------------------------------------

class PromotionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    kind: str = Field(default="PERCENT")
    percent_bps: int = Field(default=0, ge=0, le=10000)
    amount_minor: int = Field(default=0, ge=0)
    publisher_id: Optional[UUID] = None


@promotions_router.get("", responses={401: {"model": ApiErrorResponse},
                                      403: {"model": ApiErrorResponse}})
async def list_promotions(
    request: Request,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "billing:read")
    rows = list((await db.execute(select(Promotion).order_by(
        Promotion.created_at.desc()).limit(100))).scalars().all())
    return {"data": [{
        "id": str(p.id), "name": p.name, "kind": p.kind,
        "percent_bps": p.percent_bps, "amount_minor": p.amount_minor}
        for p in rows]}


@promotions_router.post("", status_code=status.HTTP_201_CREATED,
                        responses={400: {"model": ApiErrorResponse},
                                   401: {"model": ApiErrorResponse},
                                   403: {"model": ApiErrorResponse}})
async def create_promotion(
    request: Request, data: PromotionCreate,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "billing:manage")
    if data.kind.upper() not in ("PERCENT", "FIXED", "TRIAL", "PERIOD"):
        raise HTTPException(status_code=400, detail={
            "error": f"unknown promotion kind {data.kind}",
            "code": "BAD_TYPE"})
    row = Promotion(
        publisher_id=data.publisher_id, name=data.name,
        kind=data.kind.upper(), percent_bps=data.percent_bps,
        amount_minor=data.amount_minor, currency="USD", is_active=True)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {"id": str(row.id), "kind": row.kind}


class PromoCodeCreate(BaseModel):
    promotion_id: UUID
    code: str = Field(min_length=3, max_length=64)
    expires_at: Optional[datetime] = None
    max_redemptions: Optional[int] = Field(default=None, ge=1)
    max_per_customer: int = Field(default=1, ge=1)
    eligible_products: list[str] = Field(default_factory=list)


@promotions_router.post("/codes", status_code=status.HTTP_201_CREATED,
                        responses={400: {"model": ApiErrorResponse},
                                   401: {"model": ApiErrorResponse},
                                   403: {"model": ApiErrorResponse},
                                   404: {"model": ApiErrorResponse},
                                   409: {"model": ApiErrorResponse}})
async def create_promo_code(
    request: Request, data: PromoCodeCreate,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "billing:manage")
    promotion = await db.get(Promotion, data.promotion_id)
    if promotion is None:
        raise _not_found("Promotion")
    code = data.code.strip().upper()
    existing = (await db.execute(select(PromoCode).where(
        PromoCode.code == code))).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail={
            "error": "promo code already exists", "code": "CONFLICT"})
    row = PromoCode(
        promotion_id=promotion.id, code=code, expires_at=data.expires_at,
        max_redemptions=data.max_redemptions,
        max_per_customer=data.max_per_customer,
        eligible_customers=[], eligible_products=data.eligible_products,
        is_active=True, redemption_count=0)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {"id": str(row.id), "code": row.code}


# --------------------------------------------------------------------------
# Webhook intake
# --------------------------------------------------------------------------

@webhooks_router.post("/{provider}",
                      responses={401: {"model": ApiErrorResponse},
                                 409: {"model": ApiErrorResponse}})
async def billing_webhook(
    request: Request, provider: str,
    db: AsyncSession = Depends(get_db),
):
    import json as _json

    raw_body = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}
    try:
        payload = _json.loads(raw_body.decode() or "{}")
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail={
            "error": "invalid webhook JSON", "code": "BAD_PAYLOAD"})
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail={
            "error": "webhook payload must be an object",
            "code": "BAD_PAYLOAD"})
    await _rate_limited(request, f"webhook-{provider}", 120, 60)
    try:
        result = await svc.process_billing_webhook(
            db, provider=provider.lower(), headers=headers,
            raw_body=raw_body, payload=payload)
    except CommerceError as exc:
        raise _commerce_error(exc, code=401
                              if exc.code == "WEBHOOK_UNVERIFIED" else 400)
    await db.commit()
    return result


# --------------------------------------------------------------------------
# Platform admin (Master Account only)
# --------------------------------------------------------------------------

@master_billing_router.get("/overview",
                           responses={401: {"model": ApiErrorResponse},
                                      403: {"model": ApiErrorResponse}})
async def master_overview(
    request: Request,
    auth_context=Depends(require_platform_owner),
    db: AsyncSession = Depends(get_db),
):
    payments_total = (await db.execute(select(
        func.coalesce(func.sum(Payment.amount_minor), 0)))).scalar() or 0
    active_subs = (await db.execute(select(func.count()).select_from(
        Subscription).where(Subscription.status == "ACTIVE"))).scalar() or 0
    open_disputes = (await db.execute(select(func.count()).select_from(
        Dispute).where(Dispute.status == "OPEN"))).scalar() or 0
    pending_payouts = (await db.execute(select(func.count()).select_from(
        CommercePayout).where(CommercePayout.status.in_(
            ["PENDING", "ELIGIBLE", "HELD"])))).scalar() or 0
    failed_webhooks = (await db.execute(select(func.count()).select_from(
        BillingWebhookEvent).where(
            BillingWebhookEvent.processed == False))).scalar() or 0  # noqa: E712
    return {"payments_gross_minor": payments_total,
            "active_subscriptions": active_subs,
            "open_disputes": open_disputes,
            "pending_payouts": pending_payouts,
            "unprocessed_webhooks": failed_webhooks}


@master_billing_router.get("/payments",
                           responses={401: {"model": ApiErrorResponse},
                                      403: {"model": ApiErrorResponse}})
async def master_payments(
    request: Request, page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    auth_context=Depends(require_platform_owner),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Payment)
    total = (await db.execute(select(func.count()).select_from(
        stmt.subquery()))).scalar() or 0
    rows = list((await db.execute(stmt.order_by(Payment.created_at.desc())
                 .offset((page - 1) * page_size).limit(page_size))).scalars().all())
    return {"data": [{
        "id": str(p.id), "provider": p.provider,
        "provider_reference": p.provider_reference,
        "amount_minor": p.amount_minor, "currency": p.currency,
        "status": p.status,
        "organization_id": str(p.organization_id) if p.organization_id else None}
        for p in rows],
        "meta": create_pagination_meta(page, page_size, total)}


@master_billing_router.get("/webhooks",
                           responses={401: {"model": ApiErrorResponse},
                                      403: {"model": ApiErrorResponse}})
async def master_webhooks(
    request: Request, unprocessed_only: bool = Query(False),
    auth_context=Depends(require_platform_owner),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(BillingWebhookEvent)
    if unprocessed_only:
        stmt = stmt.where(BillingWebhookEvent.processed == False)  # noqa: E712
    rows = list((await db.execute(stmt.order_by(
        BillingWebhookEvent.created_at.desc()).limit(100))).scalars().all())
    return {"data": [{
        "id": str(w.id), "provider": w.provider, "event_id": w.event_id,
        "event_type": w.event_type, "signature_valid": w.signature_valid,
        "processed": w.processed,
        "retry_count": getattr(w, "retry_count", 0),
        "dead_letter": getattr(w, "dead_letter", False)} for w in rows]}
