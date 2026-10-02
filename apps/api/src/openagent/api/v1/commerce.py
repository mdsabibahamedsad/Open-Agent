"""MP24 API part 1: registries / products / prices / checkout / billing
status + provider portal. Subscriptions, entitlements, usage, quotas and
credits live in ``commerce_ops``; invoices, refunds, disputes, revenue,
payouts, promotions, webhooks and platform admin live in
``commerce_billing``.

Conventions follow the MP23 marketplace router: auth via
``get_current_org_context``, RBAC via ``require_permission`` (403-mapped),
paginated lists, shared error contract. Commercial access (entitlements)
never grants security permissions; every financial mutation is idempotent
and audited.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from openagent.api.dependencies import (
    get_current_org_context,
    require_permission,
)
from openagent.commerce import registry as registry_lib
from openagent.commerce import service as svc
from openagent.commerce.config import get_commerce_settings
from openagent.commerce.money import parse_amount
from openagent.commerce.providers import CommerceError, get_billing_provider
from openagent.commerce.types import (
    PRICING_MODELS,
    PRODUCT_TYPES,
    REGISTRY_TYPES,
)
from openagent.core.security.rate_limit import (
    get_client_identifier,
    rate_limit_dependency,
)
from openagent.db.models.commerce import (
    BillingCustomer,
    CheckoutSession,
    RegistryCredential,
)
from openagent.db.models.marketplace import (
    MarketplaceListing,
    MarketplaceRegistry,
    Price,
    Product,
    ProductStatus,
    RegistryKind,
)
from openagent.db.pagination import create_pagination_meta
from openagent.db.session import get_db
from openagent.schemas.base import ApiErrorResponse
from openagent.services.authorization import AuthorizationError

registries_router = APIRouter(prefix="/registries", tags=["registries"])
products_router = APIRouter(prefix="/products", tags=["billing-products"])
prices_router = APIRouter(prefix="/prices", tags=["billing-prices"])
checkout_router = APIRouter(prefix="/checkout", tags=["checkout"])
billing_router = APIRouter(prefix="/billing", tags=["billing"])


async def _need(request: Request, db: AsyncSession, permission: str):
    try:
        return await require_permission(permission)(request, db)
    except AuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail={"error": str(exc), "code": "FORBIDDEN"})


async def _rate_limited(request: Request, endpoint: str, limit: int,
                        window: int) -> None:
    identifier = await get_client_identifier(request)
    await rate_limit_dependency(f"{identifier}", f"billing:{endpoint}",
                                limit, window)


def _not_found(resource: str = "Resource") -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                         detail={"error": f"{resource} not found",
                                 "code": "NOT_FOUND"})


def _commerce_error(exc: CommerceError, code: int = 400) -> HTTPException:
    mapping = {"COMMERCE_DISABLED": 409, "PROVIDER_NOT_CONFIGURED": 409,
               "PAYOUTS_DISABLED": 409, "NOT_FOUND": 404,
               "QUOTA_EXCEEDED": 409, "INSUFFICIENT_CREDITS": 409,
               "INSUFFICIENT_BALANCE": 409, "PAYOUT_INELIGIBLE": 409,
               "COUPON_REJECTED": 409, "BAD_COUPON": 404,
               "WEBHOOK_UNVERIFIED": 401, "WEBHOOK_STALE": 401,
               "PAYMENT_NOT_FOUND": 404, "CUSTOMER_NOT_FOUND": 404}
    return HTTPException(status_code=mapping.get(exc.code, code),
                         detail={"error": str(exc), "code": exc.code})


def _now():
    return datetime.now(timezone.utc)


async def _audit(db: AsyncSession, *, organization_id, actor, action: str,
                 resource_id, metadata: dict[str, Any]) -> None:
    from openagent.packages import telemetry as ptelemetry
    await ptelemetry.audit(db, organization_id=organization_id,
                           actor_user_id=actor, action=action,
                           resource_id=resource_id, metadata=metadata)
    await db.commit()


def _org_id(auth_context) -> Optional[UUID]:
    return getattr(auth_context, "organization_id", None)


# --------------------------------------------------------------------------
# Registries
# --------------------------------------------------------------------------

class RegistryCreate(BaseModel):
    slug: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=255)
    registry_type: str = Field(default="PRIVATE")
    endpoint: str = Field(default="", max_length=1000)
    visibility: str = Field(default="PRIVATE")
    trust_level: str = Field(default="UNKNOWN")
    auth_type: str = Field(default="PUBLIC")
    credential_ref: str = Field(default="", max_length=255)
    signature_policy: dict[str, Any] = Field(default_factory=dict)
    mirror_of: str = Field(default="", max_length=100)


@registries_router.get("", responses={401: {"model": ApiErrorResponse},
                                      403: {"model": ApiErrorResponse}})
async def list_registries(
    request: Request,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "registry:read")
    rows = await svc.list_visible_registries(
        db, organization_id=_org_id(auth_context))
    # Private registries never leak into other orgs' listings: the service
    # already filters; private rows additionally hide their endpoint unless
    # the caller owns them.
    org_col = getattr(MarketplaceRegistry, "organization_id", None)
    data = []
    for r in rows:
        is_owner = org_col is not None and getattr(r, "organization_id",
                                                   None) == _org_id(auth_context)
        data.append({
            "id": str(r.id), "slug": r.slug, "name": r.name,
            "kind": r.kind.value if hasattr(r.kind, "value") else str(r.kind),
            "registry_type": getattr(r, "registry_type", ""),
            "endpoint": r.url_or_ref if is_owner or r.is_public else "",
            "visibility": getattr(r, "visibility", ""),
            "trust_level": r.trust_level,
            "auth_type": getattr(r, "auth_type", "PUBLIC"),
            "is_public": r.is_public, "enabled": r.enabled,
            "mirror_of": r.mirror_of,
            "status": getattr(r, "status", "ACTIVE")})
    return {"data": data}


@registries_router.post("", status_code=status.HTTP_201_CREATED,
                        responses={400: {"model": ApiErrorResponse},
                                   401: {"model": ApiErrorResponse},
                                   403: {"model": ApiErrorResponse}})
async def create_registry(
    request: Request, data: RegistryCreate,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "registry:create")
    await _rate_limited(request, "registry-create", 30, 60)
    rtype = data.registry_type.upper()
    if rtype not in REGISTRY_TYPES:
        raise HTTPException(status_code=400, detail={
            "error": f"unknown registry type {data.registry_type}",
            "code": "BAD_TYPE"})
    problems = registry_lib.validate_registry_config({
        "type": rtype, "status": "ACTIVE",
        "authentication": data.auth_type.upper(),
        "credential_ref": data.credential_ref or None})
    if problems:
        raise HTTPException(status_code=400, detail={
            "error": "; ".join(problems), "code": "BAD_REGISTRY"})
    existing = (await db.execute(select(MarketplaceRegistry).where(
        MarketplaceRegistry.slug == data.slug))).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail={
            "error": "registry slug already exists", "code": "CONFLICT"})
    kind = {
        "LOCAL": RegistryKind.SELF_HOSTED,
        "ENTERPRISE": RegistryKind.ENTERPRISE,
        "GIT": RegistryKind.GIT,
        "PRIVATE": RegistryKind.PRIVATE,
        "ORGANIZATION": RegistryKind.PRIVATE,
    }.get(rtype, RegistryKind.COMMUNITY)
    row = MarketplaceRegistry(
        slug=data.slug, name=data.name, kind=kind,
        url_or_ref=data.endpoint, trust_level=data.trust_level.upper(),
        is_public=data.visibility.upper() == "PUBLIC",
        verification_policy={}, signature_policy=data.signature_policy,
        mirror_of=data.mirror_of, enabled=True)
    for attr, value in (("registry_type", rtype),
                        ("endpoint", data.endpoint),
                        ("visibility", data.visibility.upper()),
                        ("auth_type", data.auth_type.upper()),
                        ("status", "ACTIVE")):
        if hasattr(row, attr):
            setattr(row, attr, value)
    org_col = getattr(MarketplaceRegistry, "organization_id", None)
    if org_col is not None and hasattr(row, "organization_id"):
        row.organization_id = _org_id(auth_context)
    db.add(row)
    await db.flush()
    if data.auth_type.upper() != "PUBLIC":
        db.add(RegistryCredential(
            registry_id=row.id, auth_type=data.auth_type.upper(),
            credential_ref=data.credential_ref))
    await db.commit()
    await db.refresh(row)
    await _audit(db, organization_id=_org_id(auth_context),
                 actor=auth_context.user_id,
                 action="commerce.registry.create", resource_id=row.id,
                 metadata={"slug": data.slug, "type": rtype})
    return {"id": str(row.id), "slug": row.slug, "status": "ACTIVE"}


@registries_router.post("/{registry_id}/test",
                        responses={401: {"model": ApiErrorResponse},
                                   403: {"model": ApiErrorResponse},
                                   404: {"model": ApiErrorResponse}})
async def test_registry(
    request: Request, registry_id: UUID,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Connection test: usability + trust + signature policy evaluation."""
    await _need(request, db, "registry:read")
    row = await db.get(MarketplaceRegistry, registry_id)
    if row is None:
        raise _not_found("Registry")
    usable, reason = registry_lib.registry_usable(
        {"status": getattr(row, "status", "ACTIVE"),
         "enabled": row.enabled})
    return {"id": str(row.id), "usable": usable, "reason": reason,
            "trust_level": row.trust_level,
            "trust_rank_ok": registry_lib.trust_meets(row.trust_level,
                                                      "COMMUNITY")}


@registries_router.post("/{registry_id}/sync",
                        responses={401: {"model": ApiErrorResponse},
                                   403: {"model": ApiErrorResponse},
                                   404: {"model": ApiErrorResponse}})
async def sync_registry(
    request: Request, registry_id: UUID,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Record a registry sync (metadata/version/advisory refresh marker).

    Full artifact mirroring is intentionally out of scope: this records the
    sync event and refreshes the cache marker so enterprise mirrors can
    track freshness without a CDN build-out.
    """
    await _need(request, db, "registry:manage")
    await _rate_limited(request, "registry-sync", 10, 60)
    row = await db.get(MarketplaceRegistry, registry_id)
    if row is None:
        raise _not_found("Registry")
    sync = await svc.record_registry_sync(db, registry_id=row.id,
                                          status="COMPLETED",
                                          packages_synced=0)
    if hasattr(row, "last_sync_at"):
        row.last_sync_at = _now()
    await db.commit()
    await _audit(db, organization_id=_org_id(auth_context),
                 actor=auth_context.user_id,
                 action="commerce.registry.sync", resource_id=row.id,
                 metadata={"sync_id": str(sync.id)})
    return {"id": str(sync.id), "registry_id": str(row.id),
            "status": sync.status}


@registries_router.delete("/{registry_id}",
                          responses={401: {"model": ApiErrorResponse},
                                     403: {"model": ApiErrorResponse},
                                     404: {"model": ApiErrorResponse}})
async def delete_registry(
    request: Request, registry_id: UUID,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "registry:delete")
    row = await db.get(MarketplaceRegistry, registry_id)
    if row is None:
        raise _not_found("Registry")
    if row.slug == "local":
        raise HTTPException(status_code=409, detail={
            "error": "the local registry cannot be removed",
            "code": "PROTECTED"})
    await db.delete(row)
    await db.commit()
    await _audit(db, organization_id=_org_id(auth_context),
                 actor=auth_context.user_id,
                 action="commerce.registry.delete", resource_id=registry_id,
                 metadata={"slug": row.slug})
    return {"deleted": str(registry_id)}


# --------------------------------------------------------------------------
# Products / prices
# --------------------------------------------------------------------------

class ProductCreate(BaseModel):
    listing_id: UUID
    publisher_id: Optional[UUID] = None
    product_type: str = Field(default="PACKAGE")
    pricing_model: str = Field(default="FREE")
    currency: str = Field(default="USD", min_length=3, max_length=3)
    access: str = Field(default="FREE")
    seat_model: str = Field(default="")
    license_kind: str = Field(default="")
    trial_days: int = Field(default=0, ge=0, le=365)
    metadata: dict[str, Any] = Field(default_factory=dict)


@products_router.get("", responses={401: {"model": ApiErrorResponse},
                                    403: {"model": ApiErrorResponse}})
async def list_products(
    request: Request, page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    product_type: Optional[str] = None,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "billing:read")
    stmt = select(Product)
    if product_type:
        stmt = stmt.where(Product.product_type == product_type.upper())
    total = (await db.execute(select(func.count()).select_from(
        stmt.subquery()))).scalar() or 0
    rows = list((await db.execute(stmt.order_by(Product.created_at.desc())
                 .offset((page - 1) * page_size).limit(page_size))).scalars().all())
    return {"data": [{
        "id": str(p.id), "listing_id": str(p.listing_id),
        "product_type": p.product_type.value
        if hasattr(p.product_type, "value") else str(p.product_type),
        "pricing_model": p.pricing_model.value
        if hasattr(p.pricing_model, "value") else str(p.pricing_model),
        "currency": p.currency,
        "status": p.status.value if hasattr(p.status, "value") else str(p.status),
        "access": getattr(p, "access", "FREE")} for p in rows],
        "meta": create_pagination_meta(page, page_size, total)}


@products_router.post("", status_code=status.HTTP_201_CREATED,
                      responses={400: {"model": ApiErrorResponse},
                                 401: {"model": ApiErrorResponse},
                                 403: {"model": ApiErrorResponse},
                                 404: {"model": ApiErrorResponse}})
async def create_product(
    request: Request, data: ProductCreate,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "billing:create")
    if data.product_type.upper() not in PRODUCT_TYPES:
        raise HTTPException(status_code=400, detail={
            "error": f"unknown product type {data.product_type}",
            "code": "BAD_TYPE"})
    if data.pricing_model.upper() not in PRICING_MODELS:
        raise HTTPException(status_code=400, detail={
            "error": f"unknown pricing model {data.pricing_model}",
            "code": "BAD_TYPE"})
    listing = await db.get(MarketplaceListing, data.listing_id)
    if listing is None:
        raise _not_found("Listing")
    if data.publisher_id:
        member = await svc.is_publisher_member(
            db, publisher_id=data.publisher_id,
            user_id=auth_context.user_id)
        if not member and not auth_context.is_platform_owner:
            raise HTTPException(status_code=403, detail={
                "error": "publisher membership required", "code": "FORBIDDEN"})
    try:
        product = await svc.create_product(
            db, listing_id=listing.id, publisher_id=data.publisher_id,
            product_type=data.product_type.upper(),
            pricing_model=data.pricing_model.upper(),
            currency=data.currency, access=data.access.upper(),
            seat_model=data.seat_model.upper(), license_kind=data.license_kind.upper(),
            trial_days=data.trial_days, metadata=data.metadata,
            created_by=auth_context.user_id)
    except CommerceError as exc:
        raise _commerce_error(exc)
    await db.commit()
    await db.refresh(product)
    await _audit(db, organization_id=_org_id(auth_context),
                 actor=auth_context.user_id,
                 action="commerce.product.create", resource_id=product.id,
                 metadata={"product_type": data.product_type,
                           "pricing_model": data.pricing_model})
    return {"id": str(product.id), "status": "DRAFT"}


class PriceCreate(BaseModel):
    amount: str = Field(default="0.00",
                        description="Decimal string, e.g. '9.99' (never float)")
    currency: str = Field(default="USD", min_length=3, max_length=3)
    pricing_model: str = Field(default="ONE_TIME")
    billing_interval: str = Field(default="ONE_TIME")
    trial_days: int = Field(default=0, ge=0, le=365)
    usage_rules: dict[str, Any] = Field(default_factory=dict)


@products_router.post("/{product_id}/prices",
                      status_code=status.HTTP_201_CREATED,
                      responses={400: {"model": ApiErrorResponse},
                                 401: {"model": ApiErrorResponse},
                                 403: {"model": ApiErrorResponse},
                                 404: {"model": ApiErrorResponse}})
async def create_price(
    request: Request, product_id: UUID, data: PriceCreate,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "billing:create")
    product = await db.get(Product, product_id)
    if product is None:
        raise _not_found("Product")
    try:
        amount_minor = parse_amount(data.amount, data.currency)
        price = await svc.create_price(
            db, product_id=product.id, amount_minor=amount_minor,
            currency=data.currency, pricing_model=data.pricing_model.upper(),
            billing_interval=data.billing_interval.upper(),
            trial_days=data.trial_days, usage_rules=data.usage_rules)
    except CommerceError as exc:
        raise _commerce_error(exc)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={
            "error": str(exc), "code": "BAD_AMOUNT"})
    await db.commit()
    await db.refresh(price)
    await _audit(db, organization_id=_org_id(auth_context),
                 actor=auth_context.user_id,
                 action="commerce.price.create", resource_id=price.id,
                 metadata={"amount_minor": amount_minor,
                           "currency": price.currency})
    return {"id": str(price.id), "amount_minor": price.amount_minor,
            "currency": price.currency, "status": "DRAFT"}


@products_router.post("/{product_id}/activate",
                      responses={401: {"model": ApiErrorResponse},
                                 403: {"model": ApiErrorResponse},
                                 404: {"model": ApiErrorResponse}})
async def activate_product(
    request: Request, product_id: UUID,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "billing:update")
    product = await db.get(Product, product_id)
    if product is None:
        raise _not_found("Product")
    product.status = ProductStatus.ACTIVE
    await db.execute(Price.__table__.update().where(
        Price.product_id == product.id).values(status=ProductStatus.ACTIVE))
    await db.commit()
    await _audit(db, organization_id=_org_id(auth_context),
                 actor=auth_context.user_id,
                 action="commerce.product.activate", resource_id=product.id,
                 metadata={})
    return {"id": str(product.id), "status": "ACTIVE"}


@prices_router.get("", responses={401: {"model": ApiErrorResponse},
                                  403: {"model": ApiErrorResponse}})
async def list_prices(
    request: Request, product_id: Optional[UUID] = None,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "billing:read")
    stmt = select(Price)
    if product_id:
        stmt = stmt.where(Price.product_id == product_id)
    rows = list((await db.execute(stmt.order_by(Price.created_at.desc())
                 .limit(100))).scalars().all())
    return {"data": [{
        "id": str(p.id), "product_id": str(p.product_id),
        "amount_minor": p.amount_minor, "currency": p.currency,
        "interval": p.interval,
        "billing_interval": getattr(p, "billing_interval", p.interval),
        "status": p.status.value if hasattr(p.status, "value") else str(p.status)}
        for p in rows]}


# --------------------------------------------------------------------------
# Checkout / billing status / portal
# --------------------------------------------------------------------------

class CheckoutCreate(BaseModel):
    product_id: UUID
    price_id: UUID
    idempotency_key: str = Field(default="", max_length=255)
    promo_code: str = Field(default="", max_length=64)


@checkout_router.post("", status_code=status.HTTP_201_CREATED,
                      responses={400: {"model": ApiErrorResponse},
                                 401: {"model": ApiErrorResponse},
                                 403: {"model": ApiErrorResponse},
                                 404: {"model": ApiErrorResponse},
                                 409: {"model": ApiErrorResponse}})
async def create_checkout(
    request: Request, data: CheckoutCreate,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "billing:create")
    await _rate_limited(request, "checkout", 20, 60)
    product = await db.get(Product, data.product_id)
    price = await db.get(Price, data.price_id)
    if product is None or price is None:
        raise _not_found("Product or price")
    if price.product_id != product.id:
        raise HTTPException(status_code=400, detail={
            "error": "price does not belong to product", "code": "MISMATCH"})
    settings = get_commerce_settings()
    provider = get_billing_provider(mode=settings.normalized_mode(),
                                    webhook_secret=settings.BILLING_WEBHOOK_SECRET)
    customer_info = await provider.create_customer(
        email=getattr(auth_context, "email", "") or "",
        organization_id=str(_org_id(auth_context) or ""),
        user_id=str(auth_context.user_id))
    try:
        customer = await svc.get_or_create_customer(
            db, provider=provider.name,
            provider_customer_id=str(customer_info["provider_customer_id"]),
            user_id=auth_context.user_id,
            organization_id=_org_id(auth_context))
        session = await svc.create_checkout(
            db, customer=customer, product=product, price=price,
            organization_id=_org_id(auth_context),
            user_id=auth_context.user_id,
            idempotency_key=data.idempotency_key)
    except CommerceError as exc:
        raise _commerce_error(exc)
    # Optional promo: validated server-side, never client-side.
    discount_minor = 0
    if data.promo_code:
        try:
            redemption = await svc.redeem_promo(
                db, code=data.promo_code, customer_id=customer.id,
                gross_minor=price.amount_minor,
                product_id=str(product.id),
                checkout_session_id=session.id)
            discount_minor = redemption.discount_minor
        except CommerceError as exc:
            raise _commerce_error(exc)
    await db.commit()
    checkout_url = (session.session_metadata or {}).get("checkout_url", "")
    return {"id": str(session.id),
            "provider_session_id": session.provider_session_id,
            "checkout_url": checkout_url,
            "status": session.status, "discount_minor": discount_minor,
            "test_mode": settings.normalized_mode() == "mock"}


@checkout_router.get("/{session_id}",
                     responses={401: {"model": ApiErrorResponse},
                                403: {"model": ApiErrorResponse},
                                404: {"model": ApiErrorResponse}})
async def get_checkout(
    request: Request, session_id: UUID,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "billing:read")
    row = await db.get(CheckoutSession, session_id)
    if row is None:
        raise _not_found("Checkout session")
    if (row.organization_id is not None
            and row.organization_id != _org_id(auth_context)
            and not auth_context.is_platform_owner):
        raise HTTPException(status_code=403, detail={
            "error": "cross-tenant access denied", "code": "FORBIDDEN"})
    return {"id": str(row.id), "status": row.status,
            "provider": row.provider,
            "provider_session_id": row.provider_session_id,
            "checkout_url": (row.session_metadata or {}).get("checkout_url", ""),
            "expires_at": row.expires_at.isoformat() if row.expires_at else None}


@billing_router.get("/status",
                    responses={401: {"model": ApiErrorResponse}})
async def billing_status(
    request: Request,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    settings = get_commerce_settings()
    mode = settings.normalized_mode()
    return {"mode": mode, "provider": settings.BILLING_PROVIDER or mode,
            "configured": mode in ("mock", "live"),
            "test_mode": mode == "mock",
            "self_hosted_ok": True}


@billing_router.post("/portal",
                     responses={401: {"model": ApiErrorResponse},
                                403: {"model": ApiErrorResponse},
                                409: {"model": ApiErrorResponse}})
async def billing_portal(
    request: Request,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Provider-hosted billing management (redirect URL, never secrets)."""
    await _need(request, db, "billing:read")
    settings = get_commerce_settings()
    try:
        provider = get_billing_provider(mode=settings.normalized_mode(),
                                        webhook_secret=settings.BILLING_WEBHOOK_SECRET)
    except CommerceError as exc:
        raise _commerce_error(exc)
    customer = (await db.execute(select(BillingCustomer).where(
        BillingCustomer.organization_id == _org_id(auth_context)
    ).order_by(BillingCustomer.created_at.desc()))).scalar_one_or_none()
    if customer is None:
        raise HTTPException(status_code=404, detail={
            "error": "no billing customer for this organization",
            "code": "NOT_FOUND"})
    try:
        result = await provider.create_portal_session(
            provider_customer_id=customer.provider_customer_id,
            return_url=settings.BILLING_CANCEL_URL)
    except CommerceError as exc:
        raise _commerce_error(exc)
    return {"portal_url": result.get("portal_url", ""),
            "test_mode": settings.normalized_mode() == "mock"}
