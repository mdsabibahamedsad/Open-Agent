"""MP23 API: marketplaces / listings / publishers / reviews / favorites /
advisories / reports / moderation / distribution / commerce / notifications.

Layering: marketplace distributes and manages packages; installs delegate
to the MP22 installer; execution stays in the runtimes. No endpoint here
executes agents, workflows, tools, MCP servers, browser tasks or code.

Conventions follow the MP22 router: org-scoped prefixes for tenant work,
top-level /marketplace + /publishers + /reviews + /favorites +
/security-advisories discovery paths (auth required, tenant-filtered),
RBAC via require_permission with AuthorizationError mapped to 403,
paginated lists, and the shared error contract.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from openagent.api.dependencies import (
    get_current_org_context,
    require_permission,
    require_platform_owner,
)
from openagent.core.security.rate_limit import (
    get_client_identifier,
    rate_limit_dependency,
)
from openagent.db.models.marketplace import (
    AdvisorySeverity,
    AdvisoryStatus,
    AnalyticsEventType,
    ArtifactDownload,
    ArtifactStatus,
    ArtifactType,
    BillingWebhookEvent,
    DistributionArtifact,
    DistributionLocation,
    DistributionProvider,
    Entitlement,
    EntitlementStatus,
    ListingFavorite,
    ListingReview,
    ListingStatus,
    ListingTag,
    Marketplace,
    MarketplaceAnalyticsDaily,
    MarketplaceCategory,
    MarketplaceEvent,
    MarketplaceListing,
    MarketplaceListingVersion,
    MarketplaceNotification,
    MarketplaceNotificationPref,
    MarketplacePolicy,
    MarketplaceRegistry,
    MarketplaceReport,
    MarketplaceStatus,
    MarketplaceTag,
    MarketplaceType,
    ModerationActionRecord,
    NotificationType,
    PackageRevocation,
    Payout,
    Price,
    PricingModel,
    Product,
    ProductStatus,
    ProductType,
    PublisherFollower,
    PublisherMember,
    PublisherType,
    RegistryKind,
    ReportReason,
    ReportState,
    RevenueRecord,
    ReviewReport,
    ReviewResponse,
    ReviewStatus,
    SecurityAdvisory,
    VerificationStatus,
)
from openagent.db.models.package import (
    PackageInstallation,
    PackageInstallStatus,
    PackageSignature,
    PackageValidationResult,
    PackageVersion,
    PackageVersionStatus,
    PublisherProfile,
    ReusablePackage,
)
from openagent.db.pagination import create_pagination_meta
from openagent.db.session import get_db
from openagent.marketplace import entitlements as ent_module
from openagent.marketplace import health as health_module
from openagent.marketplace import notifications as notif_module
from openagent.marketplace import policy as policy_module
from openagent.marketplace import ratings as ratings_module
from openagent.marketplace import reviews as reviews_module
from openagent.marketplace import sanitize as sanitize_module
from openagent.marketplace import search as search_module
from openagent.marketplace import telemetry as mtelemetry
from openagent.marketplace.types import (
    MODERATED_TRANSITIONS,
    ModerationAction,
    can_transition_listing,
    can_transition_verification,
)
from openagent.schemas.base import ApiErrorResponse
from openagent.services.authorization import AuthorizationError

marketplaces_router = APIRouter(
    prefix="/organizations/{organization_id}/marketplaces", tags=["marketplaces"])
marketplace_router = APIRouter(prefix="/marketplace", tags=["marketplace"])
listings_router = APIRouter(
    prefix="/organizations/{organization_id}/listings", tags=["listings"])
publishers_router = APIRouter(prefix="/publishers", tags=["publishers"])
reviews_router = APIRouter(prefix="/reviews", tags=["reviews"])
favorites_router = APIRouter(prefix="/favorites", tags=["favorites"])
advisories_router = APIRouter(prefix="/security-advisories", tags=["security-advisories"])
reports_router = APIRouter(prefix="/marketplace-reports", tags=["marketplace-reports"])
moderation_router = APIRouter(prefix="/master/marketplace", tags=["marketplace-moderation"])
distribution_router = APIRouter(
    prefix="/organizations/{organization_id}/distribution", tags=["distribution"])
commerce_router = APIRouter(
    prefix="/organizations/{organization_id}/commerce", tags=["commerce"])
publisher_router = APIRouter(
    prefix="/organizations/{organization_id}/publisher", tags=["publisher-studio"])
notifications_router = APIRouter(
    prefix="/organizations/{organization_id}/notifications", tags=["notifications"])


async def _need(request: Request, db: AsyncSession, permission: str):
    """require_permission with AuthorizationError mapped to HTTP 403."""
    try:
        return await require_permission(permission)(request, db)
    except AuthorizationError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": str(exc), "code": "FORBIDDEN"},
        )


async def _rate_limited(request: Request, endpoint: str, limit: int, window: int) -> None:
    identifier = await get_client_identifier(request)
    await rate_limit_dependency(f"{identifier}", f"marketplace:{endpoint}", limit, window)


def _not_found(resource: str = "Listing") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"error": f"{resource} not found", "code": "NOT_FOUND"},
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _get_marketplace(db: AsyncSession, marketplace_id: UUID):
    row = await db.get(Marketplace, marketplace_id)
    if row is None or row.deleted_at is not None:
        raise _not_found("Marketplace")
    return row


def _marketplace_visible(marketplace: Marketplace, organization_id: UUID) -> bool:
    """Public marketplaces are visible to all; private ones to the owner org."""
    if marketplace.type == MarketplaceType.PUBLIC_MARKETPLACE:
        return True
    return marketplace.owner_organization_id == organization_id


async def _get_publisher(db: AsyncSession, publisher_id: UUID):
    row = await db.get(PublisherProfile, publisher_id)
    if row is None:
        raise _not_found("Publisher")
    return row


async def _get_publisher_by_slug(db: AsyncSession, slug: str):
    row = (await db.execute(select(PublisherProfile).where(
        PublisherProfile.slug == slug))).scalar_one_or_none()
    if row is None:
        raise _not_found("Publisher")
    return row


async def _publisher_member_ids(db: AsyncSession, publisher_id: UUID) -> list[str]:
    rows = (await db.execute(select(PublisherMember.user_id).where(
        PublisherMember.publisher_id == publisher_id))).all()
    return [str(r[0]) for r in rows]


async def _require_publisher_member(db: AsyncSession, publisher_id: UUID,
                                    user_id: UUID, roles=("OWNER", "ADMIN", "MEMBER")):
    membership = (await db.execute(select(PublisherMember).where(
        PublisherMember.publisher_id == publisher_id,
        PublisherMember.user_id == user_id))).scalar_one_or_none()
    if membership is None or membership.role not in roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={
            "error": "Publisher membership required", "code": "NOT_PUBLISHER_MEMBER"})
    return membership


async def _get_listing(db: AsyncSession, listing_id: UUID):
    row = await db.get(MarketplaceListing, listing_id)
    if row is None or row.deleted_at is not None:
        raise _not_found()
    return row


async def _listing_accessible(db: AsyncSession, listing: MarketplaceListing,
                              organization_id: UUID,
                              user_id: Optional[UUID] = None,
                              for_install: bool = False) -> Marketplace:
    """Enforce marketplace/package tenant isolation on a listing."""
    marketplace = await _get_marketplace(db, listing.marketplace_id)
    if not _marketplace_visible(marketplace, organization_id):
        raise _not_found()  # never leak private marketplace listings
    pkg = await db.get(ReusablePackage, listing.package_id)
    if pkg is None or pkg.deleted_at is not None:
        raise _not_found()
    if pkg.organization_id is not None and pkg.organization_id != organization_id:
        # Private org packages surface only inside their own marketplace.
        if marketplace.owner_organization_id != organization_id:
            raise _not_found()
    if for_install and listing.status != ListingStatus.PUBLISHED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={
            "error": f"Listing is {listing.status.value}, not installable",
            "code": "NOT_PUBLISHED"})
    return marketplace


async def _record_event(db: AsyncSession, *, listing: Optional[MarketplaceListing],
                        event_type: str, organization_id=None, user_id=None,
                        metadata: Optional[dict] = None) -> None:
    """Write analytics event row (aggregated by worker; no private content)."""
    safe = dict(metadata or {})
    for key in ("configuration", "values", "inputs", "body", "review_body"):
        safe.pop(key, None)
    db.add(MarketplaceEvent(
        marketplace_id=listing.marketplace_id if listing else None,
        listing_id=listing.id if listing else None,
        event_type=AnalyticsEventType(event_type),
        actor_user_id=user_id,
        organization_id=organization_id,
        event_metadata=safe,
    ))
    await db.flush()


async def _notify(db: AsyncSession, *, user_ids: list[str], notif_type: str,
                  title: str, body: str = "",
                  organization_id=None, listing_id=None,
                  publisher_id=None) -> int:
    """Write notification rows honoring stored prefs (batched, bounded)."""
    if not user_ids:
        return 0
    created = 0
    for uid in list(dict.fromkeys(user_ids))[:500]:
        try:
            pref = (await db.execute(select(MarketplaceNotificationPref).where(
                MarketplaceNotificationPref.user_id == UUID(uid)))).scalars().first()
            stored = dict(pref.prefs) if pref else None
        except Exception:
            stored = None
        if not notif_module.wants(stored, notif_type):
            continue
        try:
            db.add(MarketplaceNotification(
                user_id=UUID(uid), organization_id=organization_id,
                type=NotificationType(notif_type), title=title[:255],
                body=(body or "")[:2000], listing_id=listing_id,
                publisher_id=publisher_id))
            created += 1
        except Exception:
            continue
    await db.flush()
    return created


async def _transition_listing(db: AsyncSession, listing: MarketplaceListing,
                              target: str, *, actor=None,
                              reason: str = "",
                              organization_id=None) -> MarketplaceListing:
    from openagent.packages import telemetry as ptelemetry

    source = listing.status.value
    if not can_transition_listing(source, target):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={
            "error": f"Cannot transition listing {source} -> {target}",
            "code": "BAD_TRANSITION"})
    listing.status = ListingStatus(target)
    listing.status_reason = reason[:1000]
    if target == ListingStatus.PUBLISHED.value:
        listing.published_at = _now()
    await db.flush()
    await ptelemetry.audit(
        db, organization_id=organization_id, actor_user_id=actor,
        action=f"marketplace.listing.{target.lower()}", resource_id=listing.id,
        metadata={"from": source, "reason": reason[:500]})
    event_map = {
        "SUBMITTED": "LISTING_SUBMITTED", "APPROVED": "LISTING_APPROVED",
        "REJECTED": "LISTING_REJECTED", "PUBLISHED": "LISTING_PUBLISHED",
        "SUSPENDED": "LISTING_SUSPENDED", "REVOKED": "LISTING_REVOKED",
    }
    if target in event_map:
        await ptelemetry.emit(
            db, event_type=event_map[target], aggregate_id=listing.id,
            organization_id=organization_id, user_id=actor,
            payload={"status": target, "package_id": str(listing.package_id)})
    return listing


def _listing_out(listing: MarketplaceListing, *,
                 publisher_slug: str = "", publisher_name: str = "",
                 verification: str = "UNVERIFIED",
                 installed: bool = False,
                 installed_version: str = "",
                 favorite: bool = False) -> dict:
    return {
        "id": str(listing.id), "marketplace_id": str(listing.marketplace_id),
        "package_id": str(listing.package_id),
        "publisher_id": str(listing.publisher_id),
        "publisher_slug": publisher_slug, "publisher_name": publisher_name,
        "publisher_verification": verification,
        "slug": listing.slug, "title": listing.title,
        "short_description": listing.short_description,
        "full_description": listing.full_description,
        "icon": listing.icon, "banner": listing.banner,
        "screenshots": listing.screenshots, "videos": listing.videos,
        "category": listing.category, "license": listing.license,
        "pricing_model": listing.pricing_model.value,
        "compatibility": listing.compatibility, "requirements": listing.requirements,
        "trust_level": listing.trust_level, "security_status": listing.security_status,
        "published_version_id": (str(listing.published_version_id)
                                 if listing.published_version_id else None),
        "published_version": listing.published_version,
        "status": listing.status.value, "status_reason": listing.status_reason,
        "badges": listing.badges,
        "rating_average": listing.rating_average, "rating_count": listing.rating_count,
        "rating_distribution": listing.rating_distribution,
        "verified_review_count": listing.verified_review_count,
        "install_count": listing.install_count,
        "successful_install_count": listing.successful_install_count,
        "active_install_count": listing.active_install_count,
        "favorite_count": listing.favorite_count, "view_count": listing.view_count,
        "installed": installed, "installed_version": installed_version,
        "favorite": favorite,
        "published_at": listing.published_at.isoformat() if listing.published_at else None,
        "created_at": listing.created_at.isoformat(),
        "updated_at": listing.updated_at.isoformat(),
    }


# ---------------------------------------------------------------------------
# Marketplaces
# ---------------------------------------------------------------------------

class MarketplaceCreate(BaseModel):
    slug: str = Field(min_length=1, max_length=100, pattern="^[a-z0-9]+(?:[-][a-z0-9]+)*$")
    name: str = Field(min_length=1, max_length=255)
    type: str = Field(default="PRIVATE_MARKETPLACE")
    visibility: str = Field(default="PRIVATE")
    configuration: dict[str, Any] = Field(default_factory=dict)


class MarketplaceUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    visibility: Optional[str] = None
    status: Optional[str] = None
    configuration: Optional[dict[str, Any]] = None


def _marketplace_out(marketplace: Marketplace) -> dict:
    return {
        "id": str(marketplace.id), "slug": marketplace.slug, "name": marketplace.name,
        "type": marketplace.type.value,
        "owner_organization_id": (str(marketplace.owner_organization_id)
                                  if marketplace.owner_organization_id else None),
        "visibility": marketplace.visibility, "status": marketplace.status.value,
        "configuration": marketplace.configuration,
        "created_at": marketplace.created_at.isoformat(),
        "updated_at": marketplace.updated_at.isoformat(),
    }


@marketplaces_router.get("",
                         responses={401: {"model": ApiErrorResponse},
                                    403: {"model": ApiErrorResponse}})
async def list_marketplaces(
    request: Request, organization_id: UUID,
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "marketplace:read")
    query = select(Marketplace).where(
        Marketplace.deleted_at.is_(None),
        or_(Marketplace.type == MarketplaceType.PUBLIC_MARKETPLACE,
            Marketplace.owner_organization_id == organization_id))
    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    rows = list((await db.execute(query.order_by(Marketplace.slug)
                  .limit(page_size).offset((page - 1) * page_size))).scalars().all())
    return {"data": [_marketplace_out(r) for r in rows],
            "meta": create_pagination_meta(page, page_size, total).model_dump()}


@marketplaces_router.post("", status_code=status.HTTP_201_CREATED,
                          responses={400: {"model": ApiErrorResponse},
                                     401: {"model": ApiErrorResponse},
                                     403: {"model": ApiErrorResponse},
                                     409: {"model": ApiErrorResponse}})
async def create_marketplace(
    request: Request, organization_id: UUID, data: MarketplaceCreate,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "marketplace:create")
    from openagent.packages import telemetry as ptelemetry

    try:
        mtype = MarketplaceType(data.type.upper())
    except ValueError:
        raise HTTPException(status_code=400, detail={
            "error": f"Unknown marketplace type {data.type!r}", "code": "BAD_TYPE"})
    if mtype == MarketplaceType.PUBLIC_MARKETPLACE and not auth_context.is_platform_owner:
        raise HTTPException(status_code=403, detail={
            "error": "Only platform owners create public marketplaces",
            "code": "FORBIDDEN"})
    dup = (await db.execute(select(Marketplace).where(
        Marketplace.slug == data.slug,
        Marketplace.deleted_at.is_(None)))).scalar_one_or_none()
    if dup is not None:
        raise HTTPException(status_code=409, detail={
            "error": "Marketplace slug exists", "code": "SLUG_EXISTS"})
    row = Marketplace(
        slug=data.slug, name=data.name, type=mtype,
        owner_organization_id=organization_id,
        visibility=data.visibility.upper() if mtype != MarketplaceType.PUBLIC_MARKETPLACE else "PUBLIC",
        configuration=data.configuration, created_by=auth_context.user_id)
    db.add(row)
    await db.flush()
    db.add(MarketplacePolicy(marketplace_id=row.id, name="Default policy",
                             rules=dict(policy_module.DEFAULT_POLICY_RULES)))
    await db.commit()
    await db.refresh(row)
    await ptelemetry.audit(db, organization_id=organization_id,
                           actor_user_id=auth_context.user_id,
                           action="marketplace.create", resource_id=row.id,
                           metadata={"slug": row.slug, "type": row.type.value})
    await db.commit()
    return _marketplace_out(row)


@marketplaces_router.get("/{marketplace_id}",
                         responses={401: {"model": ApiErrorResponse},
                                    403: {"model": ApiErrorResponse},
                                    404: {"model": ApiErrorResponse}})
async def get_marketplace(
    request: Request, organization_id: UUID, marketplace_id: UUID,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "marketplace:read")
    row = await _get_marketplace(db, marketplace_id)
    if not _marketplace_visible(row, organization_id):
        raise _not_found("Marketplace")
    return _marketplace_out(row)


@marketplaces_router.patch("/{marketplace_id}",
                           responses={401: {"model": ApiErrorResponse},
                                      403: {"model": ApiErrorResponse},
                                      404: {"model": ApiErrorResponse}})
async def update_marketplace(
    request: Request, organization_id: UUID, marketplace_id: UUID, data: MarketplaceUpdate,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "marketplace:update")
    from openagent.packages import telemetry as ptelemetry

    row = await _get_marketplace(db, marketplace_id)
    if row.owner_organization_id != organization_id and not auth_context.is_platform_owner:
        raise _not_found("Marketplace")
    if data.name is not None:
        row.name = data.name
    if data.visibility is not None:
        row.visibility = data.visibility.upper()
    if data.status is not None:
        try:
            row.status = MarketplaceStatus(data.status.upper())
        except ValueError:
            raise HTTPException(status_code=400, detail={
                "error": "Unknown marketplace status", "code": "BAD_STATUS"})
    if data.configuration is not None:
        row.configuration = data.configuration
    await db.commit()
    await db.refresh(row)
    await ptelemetry.audit(db, organization_id=organization_id,
                           actor_user_id=auth_context.user_id,
                           action="marketplace.update", resource_id=row.id)
    await db.commit()
    return _marketplace_out(row)


@marketplaces_router.get("/{marketplace_id}/policy",
                         responses={401: {"model": ApiErrorResponse},
                                    403: {"model": ApiErrorResponse},
                                    404: {"model": ApiErrorResponse}})
async def get_marketplace_policy(
    request: Request, organization_id: UUID, marketplace_id: UUID,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "marketplace:read")
    row = await _get_marketplace(db, marketplace_id)
    if not _marketplace_visible(row, organization_id):
        raise _not_found("Marketplace")
    policy = (await db.execute(select(MarketplacePolicy).where(
        MarketplacePolicy.marketplace_id == row.id))).scalar_one_or_none()
    if policy is None:
        return {"marketplace_id": str(row.id), "rules": policy_module.DEFAULT_POLICY_RULES,
                "is_active": True, "stored": False}
    return {"marketplace_id": str(row.id), "name": policy.name, "rules": policy.rules,
            "is_active": policy.is_active, "stored": True}


class PolicyUpdate(BaseModel):
    rules: dict[str, Any]


@marketplaces_router.put("/{marketplace_id}/policy",
                         responses={401: {"model": ApiErrorResponse},
                                    403: {"model": ApiErrorResponse},
                                    404: {"model": ApiErrorResponse}})
async def put_marketplace_policy(
    request: Request, organization_id: UUID, marketplace_id: UUID, data: PolicyUpdate,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "marketplace:manage")
    from openagent.packages import telemetry as ptelemetry

    row = await _get_marketplace(db, marketplace_id)
    if row.owner_organization_id != organization_id and not auth_context.is_platform_owner:
        raise _not_found("Marketplace")
    # Policy can only add requirements, never weaken platform security:
    # unknown keys are rejected so typos can't silently disable gates.
    allowed = set(policy_module.DEFAULT_POLICY_RULES)
    unknown = set(data.rules) - allowed
    if unknown:
        raise HTTPException(status_code=400, detail={
            "error": f"Unknown policy keys: {sorted(unknown)}", "code": "BAD_POLICY"})
    policy = (await db.execute(select(MarketplacePolicy).where(
        MarketplacePolicy.marketplace_id == row.id))).scalar_one_or_none()
    merged = dict(policy_module.DEFAULT_POLICY_RULES)
    merged.update(policy.rules if policy else {})
    merged.update(data.rules)
    if policy is None:
        policy = MarketplacePolicy(marketplace_id=row.id, name="Custom policy",
                                   rules=merged, updated_by=auth_context.user_id)
        db.add(policy)
    else:
        policy.rules = merged
        policy.updated_by = auth_context.user_id
    await db.commit()
    await ptelemetry.audit(db, organization_id=organization_id,
                           actor_user_id=auth_context.user_id,
                           action="marketplace.policy.update", resource_id=row.id)
    await db.commit()
    return {"marketplace_id": str(row.id), "rules": merged, "is_active": True}


async def _policy_rules(db: AsyncSession, marketplace_id: UUID) -> dict:
    policy = (await db.execute(select(MarketplacePolicy).where(
        MarketplacePolicy.marketplace_id == marketplace_id))).scalar_one_or_none()
    merged = dict(policy_module.DEFAULT_POLICY_RULES)
    if policy and policy.is_active:
        merged.update(policy.rules or {})
    return merged


# ---------------------------------------------------------------------------
# Discovery (public catalog over listings)
# ---------------------------------------------------------------------------

def _listing_search_base(organization_id: UUID):
    """Listings join: only PUBLISHED, non-deleted, in visible marketplaces."""
    return (select(MarketplaceListing, Marketplace, ReusablePackage)
            .join(Marketplace, Marketplace.id == MarketplaceListing.marketplace_id)
            .join(ReusablePackage, ReusablePackage.id == MarketplaceListing.package_id)
            .where(MarketplaceListing.deleted_at.is_(None),
                   Marketplace.deleted_at.is_(None),
                   MarketplaceListing.status == ListingStatus.PUBLISHED,
                   ReusablePackage.deleted_at.is_(None),
                   or_(Marketplace.type == MarketplaceType.PUBLIC_MARKETPLACE,
                       Marketplace.owner_organization_id == organization_id)))


@marketplace_router.get("/search",
                        responses={401: {"model": ApiErrorResponse},
                                   403: {"model": ApiErrorResponse},
                                   429: {"model": ApiErrorResponse}})
async def marketplace_search(
    request: Request,
    q: str = Query(""), marketplace: str = Query(""), category: str = Query(""),
    tags: str = Query(""), package_types: str = Query(""), publishers: str = Query(""),
    pricing: str = Query(""), license: str = Query(""), trust: str = Query(""),
    security_max: str = Query(""), min_rating: float = Query(0.0, ge=0.0, le=5.0),
    badges: str = Query(""), sort: str = Query("RELEVANCE"),
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "marketplace:read")
    await _rate_limited(request, "search", 120, 60)
    organization_id = auth_context.organization_id

    query = search_module.MarketplaceSearchQuery(
        text=q, marketplace_id=marketplace, category=category,
        tags=[t for t in tags.split(",") if t],
        package_types=[t for t in package_types.split(",") if t],
        publishers=[p for p in publishers.split(",") if p],
        pricing=[p for p in pricing.split(",") if p],
        license=license, trust=[t for t in trust.split(",") if t],
        security_max=security_max, min_rating=min_rating,
        badges=[b for b in badges.split(",") if b],
        sort=sort, page=page, page_size=page_size).normalized()

    stmt = _listing_search_base(organization_id)
    if query.marketplace_id:
        try:
            stmt = stmt.where(Marketplace.id == UUID(query.marketplace_id))
        except ValueError:
            raise HTTPException(status_code=400, detail={
                "error": "Invalid marketplace id", "code": "BAD_MARKETPLACE"})
    if query.category:
        stmt = stmt.where(MarketplaceListing.category == query.category)
    if query.package_types:
        stmt = stmt.where(ReusablePackage.package_type.in_(query.package_types))
    if query.publishers:
        stmt = stmt.where(MarketplaceListing.publisher_id.in_(
            [UUID(p) for p in query.publishers if _is_uuid(p)]))
    if query.pricing:
        stmt = stmt.where(MarketplaceListing.pricing_model.in_(query.pricing))
    if query.license:
        stmt = stmt.where(MarketplaceListing.license == query.license)
    if query.trust:
        stmt = stmt.where(MarketplaceListing.trust_level.in_(query.trust))
    if query.min_rating:
        stmt = stmt.where(MarketplaceListing.rating_average >= query.min_rating)
    if query.security_max:
        order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3, "UNKNOWN": 3}
        ceiling = order.get(query.security_max.upper(), 3)
        allowed = [k for k, v in order.items() if v <= ceiling]
        stmt = stmt.where(MarketplaceListing.security_status.in_(allowed))

    rows = list((await db.execute(stmt.limit(500))).all())
    # Tag filter needs the join table; apply in Python over the bounded set.
    tag_ids: set = set()
    if query.tags:
        tag_rows = (await db.execute(select(MarketplaceTag).where(
            MarketplaceTag.slug.in_([t.lower() for t in query.tags])))).scalars().all()
        tag_ids = {t.id for t in tag_rows}
        if tag_ids:
            link_rows = (await db.execute(select(ListingTag.listing_id).where(
                ListingTag.tag_id.in_(tag_ids)))).all()
            with_tags = {r[0] for r in link_rows}
            rows = [r for r in rows if r[0].id in with_tags]
        else:
            rows = []

    scored: list[tuple[float, Any, Any, Any]] = []
    for listing, marketplace, pkg in rows:
        if query.badges and not all(
                str(listing.badges.get(b.lower(), False)).lower() == "true"
                for b in query.badges):
            continue
        score = search_module.relevance_score(
            title=listing.title, description=listing.short_description,
            tags=list(pkg.tags or []), text=query.text)
        if query.text and score <= 0:
            continue
        scored.append((score, listing, marketplace, pkg))

    sort_spec = search_module.sort_key(query.sort)
    if sort_spec is None:
        scored.sort(key=lambda item: (-item[0], -(item[1].rating_average or 0.0),
                                      item[1].title.lower()))
    else:
        column, descending = sort_spec
        if column == "min_price":
            priced = await _min_prices(db, [s[1].id for s in scored])
            scored.sort(key=lambda item: (priced.get(item[1].id, 0.0),
                                          item[1].title.lower()),
                        reverse=descending)
        else:
            scored.sort(key=lambda item: (getattr(item[1], column, 0) or 0,
                                          item[1].title.lower()),
                        reverse=descending)

    total = len(scored)
    start = (query.page - 1) * query.page_size
    page_items = scored[start:start + query.page_size]
    pubs = await _publisher_lookup(
        db, {item[1].publisher_id for item in page_items})
    data = [
        {**_listing_out(
            listing, publisher_slug=pubs.get(listing.publisher_id, {}).get("slug", ""),
            publisher_name=pubs.get(listing.publisher_id, {}).get("display_name", ""),
            verification=pubs.get(listing.publisher_id, {}).get(
                "verification_status", "UNVERIFIED")),
         "marketplace_slug": marketplace.slug,
         "package_type": pkg.package_type.value,
         "relevance": round(score, 2)}
        for score, listing, marketplace, pkg in page_items
    ]
    mtelemetry.inc("marketplace_search_total")
    return {"data": data, "featured": [],
            "meta": create_pagination_meta(query.page, query.page_size, total).model_dump(),
            "provider": "marketplace-sql"}


def _is_uuid(value: str) -> bool:
    try:
        UUID(str(value))
        return True
    except ValueError:
        return False


async def _min_prices(db: AsyncSession, listing_ids: list) -> dict:
    """Cheapest active price per listing (minor units), 0.0 when free/none."""
    if not listing_ids:
        return {}
    rows = (await db.execute(
        select(Product.listing_id, func.min(Price.amount_minor))
        .join(Price, Price.product_id == Product.id)
        .where(Product.listing_id.in_(listing_ids),
               Product.status == ProductStatus.ACTIVE,
               Price.status == ProductStatus.ACTIVE)
        .group_by(Product.listing_id))).all()
    return {listing_id: float(minor or 0) for listing_id, minor in rows}


async def _publisher_lookup(db: AsyncSession, publisher_ids: set) -> dict:
    if not publisher_ids:
        return {}
    rows = (await db.execute(select(PublisherProfile).where(
        PublisherProfile.id.in_(list(publisher_ids))))).scalars().all()
    return {r.id: {"slug": r.slug, "display_name": r.display_name,
                   "verification_status": r.verification_status} for r in rows}


@marketplace_router.get("/categories",
                        responses={401: {"model": ApiErrorResponse},
                                   403: {"model": ApiErrorResponse}})
async def marketplace_categories(
    request: Request, marketplace: str = Query(""),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "marketplace:read")
    organization_id = auth_context.organization_id
    stmt = select(MarketplaceCategory).order_by(MarketplaceCategory.position,
                                                MarketplaceCategory.name)
    if marketplace:
        try:
            mid = UUID(marketplace)
        except ValueError:
            raise HTTPException(status_code=400, detail={
                "error": "Invalid marketplace id", "code": "BAD_MARKETPLACE"})
        stmt = stmt.where(or_(MarketplaceCategory.marketplace_id.is_(None),
                              MarketplaceCategory.marketplace_id == mid))
    else:
        stmt = stmt.where(MarketplaceCategory.marketplace_id.is_(None))
    rows = list((await db.execute(stmt.limit(500))).scalars().all())
    # Hide categories of private marketplaces the caller cannot see.
    if marketplace:
        row = await _get_marketplace(db, UUID(marketplace))
        if not _marketplace_visible(row, organization_id):
            raise _not_found("Marketplace")
    by_parent: dict = {}
    for row in rows:
        by_parent.setdefault(str(row.parent_id) if row.parent_id else "", []).append(row)

    def node(row) -> dict:
        return {
            "id": str(row.id), "slug": row.slug, "name": row.name,
            "description": row.description, "official": row.official,
            "children": [node(child) for child in by_parent.get(str(row.id), [])],
        }

    return {"data": [node(r) for r in by_parent.get("", [])]}


@marketplace_router.get("/featured",
                        responses={401: {"model": ApiErrorResponse},
                                   403: {"model": ApiErrorResponse}})
async def marketplace_featured(
    request: Request,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "marketplace:read")
    from openagent.marketplace.recommendations import discovery_sections

    organization_id = auth_context.organization_id
    base = _listing_search_base(organization_id)
    rows = list((await db.execute(base.limit(500))).all())
    pubs = await _publisher_lookup(db, {r[0].publisher_id for r in rows})

    def card(item) -> dict:
        listing, _, pkg = item
        return _listing_out(
            listing,
            publisher_slug=pubs.get(listing.publisher_id, {}).get("slug", ""),
            publisher_name=pubs.get(listing.publisher_id, {}).get("display_name", ""),
            verification=pubs.get(listing.publisher_id, {}).get(
                "verification_status", "UNVERIFIED"))

    def flagged(item, *kinds: str) -> bool:
        return any(str(item[0].badges.get(k.lower(), False)).lower() == "true"
                   for k in kinds)

    featured = [card(i) for i in rows if flagged(i, "featured", "editorial")][:12]
    official = [card(i) for i in rows if flagged(i, "official") or i[2].official][:12]
    new = [card(i) for i in sorted(
        rows, key=lambda i: i[0].published_at or i[0].created_at, reverse=True)[:12]]
    popular = [card(i) for i in sorted(rows, key=lambda i: i[0].install_count,
                                       reverse=True)[:12]]
    return {"sections": discovery_sections(
        featured=featured, official=official, new=new, popular=popular)}


# ---------------------------------------------------------------------------
# Listing detail / related (public discovery)
# ---------------------------------------------------------------------------

async def _listing_detail(db: AsyncSession, listing: MarketplaceListing,
                          organization_id: UUID,
                          user_id: Optional[UUID]) -> dict:
    marketplace = await _listing_accessible(db, listing, organization_id,
                                            user_id=user_id)
    pkg = await db.get(ReusablePackage, listing.package_id)
    pub = await _get_publisher(db, listing.publisher_id)
    versions = list((await db.execute(
        select(MarketplaceListingVersion).where(
            MarketplaceListingVersion.listing_id == listing.id)
        .order_by(MarketplaceListingVersion.created_at.desc()).limit(50)
    )).scalars().all())
    products = list((await db.execute(select(Product).where(
        Product.listing_id == listing.id,
        Product.status == ProductStatus.ACTIVE))).scalars().all())
    product_ids = [p.id for p in products]
    prices: list = []
    if product_ids:
        prices = list((await db.execute(select(Price).where(
            Price.product_id.in_(product_ids),
            Price.status == ProductStatus.ACTIVE))).scalars().all())
    advisories = list((await db.execute(select(SecurityAdvisory).where(
        SecurityAdvisory.listing_id == listing.id))).scalars().all())
    # Caller install state (real backend state only).
    installed_version = ""
    installation_id = None
    if pkg is not None:
        inst = (await db.execute(select(PackageInstallation).where(
            PackageInstallation.organization_id == organization_id,
            PackageInstallation.package_id == pkg.id,
            PackageInstallation.status == PackageInstallStatus.INSTALLED)
            .order_by(PackageInstallation.installed_at.desc()))).scalars().first()
        if inst is not None:
            ver = await db.get(PackageVersion, inst.version_id)
            installed_version = ver.version if ver else ""
            installation_id = str(inst.id)
    favorite = False
    if user_id is not None:
        favorite = (await db.execute(select(ListingFavorite).where(
            ListingFavorite.listing_id == listing.id,
            ListingFavorite.user_id == user_id))).scalar_one_or_none() is not None
    tags = [t.slug for t in (await db.execute(
        select(MarketplaceTag).join(
            ListingTag, ListingTag.tag_id == MarketplaceTag.id).where(
                ListingTag.listing_id == listing.id))).scalars().all()]
    return {
        **_listing_out(
            listing, publisher_slug=pub.slug, publisher_name=pub.display_name,
            verification=pub.verification_status,
            installed=bool(installed_version),
            installed_version=installed_version, favorite=favorite),
        "marketplace_slug": marketplace.slug,
        "package_type": pkg.package_type.value if pkg else "",
        "package_visibility": pkg.visibility.value if pkg else "",
        "installation_id": installation_id,
        "tags": tags,
        "versions": [{
            "version": v.version, "version_id": str(v.version_id),
            "is_current": v.is_current, "changelog": v.changelog,
            "created_at": v.created_at.isoformat()} for v in versions],
        "products": [{
            "id": str(p.id), "product_type": p.product_type.value,
            "pricing_model": p.pricing_model.value, "currency": p.currency,
            "status": p.status.value,
            "prices": [{
                "id": str(pr.id), "amount_minor": pr.amount_minor,
                "currency": pr.currency, "interval": pr.interval,
                "tiers": pr.tiers} for pr in prices if pr.product_id == p.id],
        } for p in products],
        "advisories": [{
            "id": str(a.id), "title": a.title, "severity": a.severity.value,
            "status": a.status.value, "affected_versions": a.affected_versions,
            "recommended_version": a.recommended_version} for a in advisories],
    }


@marketplace_router.get("/{slug}",
                        responses={401: {"model": ApiErrorResponse},
                                   403: {"model": ApiErrorResponse},
                                   404: {"model": ApiErrorResponse},
                                   429: {"model": ApiErrorResponse}})
async def marketplace_detail(
    request: Request, slug: str,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "marketplace:read")
    await _rate_limited(request, "detail-view", 60, 60)
    organization_id = auth_context.organization_id
    listing = (await db.execute(select(MarketplaceListing).where(
        MarketplaceListing.slug == slug,
        MarketplaceListing.deleted_at.is_(None)))).scalar_one_or_none()
    if listing is None:
        raise _not_found()
    if listing.status != ListingStatus.PUBLISHED:
        # Non-published listings are visible to publisher members + moderators.
        member_ids = await _publisher_member_ids(db, listing.publisher_id)
        if (str(auth_context.user_id) not in member_ids
                and "marketplace:manage" not in (auth_context.permissions or set())):
            raise _not_found()
    detail = await _listing_detail(db, listing, organization_id, auth_context.user_id)
    listing.view_count = (listing.view_count or 0) + 1
    await _record_event(db, listing=listing, event_type="VIEW",
                        organization_id=organization_id, user_id=auth_context.user_id)
    mtelemetry.inc("marketplace_listing_views_total")
    await db.commit()
    return detail


@marketplace_router.get("/{slug}/related",
                        responses={401: {"model": ApiErrorResponse},
                                   403: {"model": ApiErrorResponse},
                                   404: {"model": ApiErrorResponse}})
async def marketplace_related(
    request: Request, slug: str,
    limit: int = Query(8, ge=1, le=20),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "marketplace:read")
    from openagent.marketplace.recommendations import recommend_for_listing

    organization_id = auth_context.organization_id
    listing = (await db.execute(select(MarketplaceListing).where(
        MarketplaceListing.slug == slug,
        MarketplaceListing.deleted_at.is_(None)))).scalar_one_or_none()
    if listing is None:
        raise _not_found()
    await _listing_accessible(db, listing, organization_id)
    rows = list((await db.execute(
        _listing_search_base(organization_id).limit(200))).all())
    pubs = await _publisher_lookup(db, {r[0].publisher_id for r in rows})
    installed_ids = {
        r[0] for r in (await db.execute(select(PackageInstallation.package_id).where(
            PackageInstallation.organization_id == organization_id,
            PackageInstallation.status == PackageInstallStatus.INSTALLED))).all()
    }
    source_tags = [t.slug for t in (await db.execute(
        select(MarketplaceTag).join(
            ListingTag, ListingTag.tag_id == MarketplaceTag.id).where(
                ListingTag.listing_id == listing.id))).scalars().all()]
    source_pkg = await db.get(ReusablePackage, listing.package_id)
    source = {"id": str(listing.id), "package_id": str(listing.package_id),
              "publisher_id": str(listing.publisher_id),
              "category": listing.category, "tags": source_tags,
              "package_type": source_pkg.package_type.value if source_pkg else ""}
    candidates = []
    for row_listing, _, pkg in rows:
        tag_rows = (await db.execute(
            select(MarketplaceTag.slug).join(
                ListingTag, ListingTag.tag_id == MarketplaceTag.id).where(
                    ListingTag.listing_id == row_listing.id))).all()
        candidates.append({
            "id": str(row_listing.id), "package_id": str(row_listing.package_id),
            "publisher_id": str(row_listing.publisher_id),
            "category": row_listing.category, "title": row_listing.title,
            "tags": [t[0] for t in tag_rows], "package_type": pkg.package_type.value,
            "card": _listing_out(
                row_listing,
                publisher_slug=pubs.get(row_listing.publisher_id, {}).get("slug", ""),
                publisher_name=pubs.get(row_listing.publisher_id, {}).get(
                    "display_name", "")),
        })
    recs = recommend_for_listing(
        source=source, candidates=candidates,
        installed_package_ids=[str(i) for i in installed_ids], limit=limit)
    return {"data": [{"listing": r["listing"]["card"], "reasons": r["reasons"]}
                     for r in recs]}


# ---------------------------------------------------------------------------
# Listings (tenant-scoped management)
# ---------------------------------------------------------------------------

class ListingCreate(BaseModel):
    marketplace_id: UUID
    package_id: UUID
    publisher_id: UUID
    slug: str = Field(min_length=1, max_length=160, pattern="^[a-z0-9]+(?:[-][a-z0-9]+)*$")
    title: str = Field(min_length=1, max_length=255)
    short_description: str = Field(default="", max_length=500)
    full_description: str = Field(default="", max_length=20000)
    icon: str = Field(default="", max_length=500)
    banner: str = Field(default="", max_length=500)
    screenshots: list[str] = Field(default_factory=list)
    videos: list[str] = Field(default_factory=list)
    category: str = Field(default="", max_length=100)
    license: str = Field(default="", max_length=64)
    pricing_model: str = Field(default="FREE")
    tags: list[str] = Field(default_factory=list)


class ListingUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    short_description: Optional[str] = None
    full_description: Optional[str] = None
    icon: Optional[str] = None
    banner: Optional[str] = None
    screenshots: Optional[list[str]] = None
    videos: Optional[list[str]] = None
    category: Optional[str] = None
    license: Optional[str] = None
    tags: Optional[list[str]] = None


async def _sync_listing_tags(db: AsyncSession, listing_id: UUID,
                             tags: list[str]) -> None:
    """Normalize + attach tags (creates registry rows, deduped by slug)."""
    from sqlalchemy import delete as _delete

    await db.execute(_delete(ListingTag).where(
        ListingTag.listing_id == listing_id))
    for raw in dict.fromkeys([str(t).strip().lower() for t in (tags or []) if str(t).strip()]):
        slug = "".join(c if (c.isalnum() or c in ("-", "_")) else "-"
                       for c in raw)[:100].strip("-") or "tag"
        tag = (await db.execute(select(MarketplaceTag).where(
            MarketplaceTag.slug == slug))).scalar_one_or_none()
        if tag is None:
            tag = MarketplaceTag(slug=slug, name=raw[:120])
            db.add(tag)
            await db.flush()
        else:
            tag.usage_count = (tag.usage_count or 0) + 1
        db.add(ListingTag(listing_id=listing_id, tag_id=tag.id))
    await db.flush()


async def _publisher_out(db: AsyncSession, pub: PublisherProfile) -> dict:
    members = await _publisher_member_ids(db, pub.id)
    followers = (await db.execute(select(func.count(PublisherFollower.id)).where(
        PublisherFollower.publisher_id == pub.id))).scalar_one()
    listings = (await db.execute(select(func.count(MarketplaceListing.id)).where(
        MarketplaceListing.publisher_id == pub.id,
        MarketplaceListing.deleted_at.is_(None),
        MarketplaceListing.status == ListingStatus.PUBLISHED))).scalar_one()
    return {
        "id": str(pub.id), "slug": pub.slug, "display_name": pub.display_name,
        "publisher_type": pub.publisher_type, "avatar": pub.avatar, "banner": pub.banner,
        "description": pub.description, "website": pub.website,
        "social_links": pub.social_links,
        "verification_status": pub.verification_status, "verified": pub.verified,
        "verified_at": pub.verified_at.isoformat() if pub.verified_at else None,
        "trust_status": pub.trust_status,
        "organization_id": str(pub.organization_id) if pub.organization_id else None,
        "member_count": len(members), "follower_count": followers,
        "published_listings": listings,
    }


@listings_router.get("",
                     responses={401: {"model": ApiErrorResponse},
                                403: {"model": ApiErrorResponse}})
async def list_listings(
    request: Request, organization_id: UUID,
    status: str = Query(""), mine: bool = Query(False),
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "marketplace:read")
    stmt = (select(MarketplaceListing, Marketplace)
            .join(Marketplace, Marketplace.id == MarketplaceListing.marketplace_id)
            .where(MarketplaceListing.deleted_at.is_(None),
                   or_(Marketplace.type == MarketplaceType.PUBLIC_MARKETPLACE,
                       Marketplace.owner_organization_id == organization_id)))
    if mine:
        member_pub_ids = (await db.execute(select(PublisherMember.publisher_id).where(
            PublisherMember.user_id == auth_context.user_id))).scalars().all()
        stmt = stmt.where(or_(
            MarketplaceListing.created_by == auth_context.user_id,
            MarketplaceListing.publisher_id.in_(list(member_pub_ids) or [])))
    if status:
        try:
            stmt = stmt.where(MarketplaceListing.status == ListingStatus(status.upper()))
        except ValueError:
            raise HTTPException(status_code=400, detail={
                "error": "Unknown listing status", "code": "BAD_STATUS"})
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = list((await db.execute(stmt.order_by(MarketplaceListing.updated_at.desc())
                  .limit(page_size).offset((page - 1) * page_size))).all())
    pubs = await _publisher_lookup(db, {r[0].publisher_id for r in rows})
    return {"data": [
        {**_listing_out(
            listing,
            publisher_slug=pubs.get(listing.publisher_id, {}).get("slug", ""),
            publisher_name=pubs.get(listing.publisher_id, {}).get("display_name", "")),
         "marketplace_slug": marketplace.slug}
        for listing, marketplace in rows],
        "meta": create_pagination_meta(page, page_size, total).model_dump()}


@listings_router.post("", status_code=status.HTTP_201_CREATED,
                      responses={400: {"model": ApiErrorResponse},
                                 401: {"model": ApiErrorResponse},
                                 403: {"model": ApiErrorResponse},
                                 404: {"model": ApiErrorResponse},
                                 409: {"model": ApiErrorResponse}})
async def create_listing(
    request: Request, organization_id: UUID, data: ListingCreate,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "marketplace:create")
    from openagent.packages import telemetry as ptelemetry

    marketplace = await _get_marketplace(db, data.marketplace_id)
    if marketplace.owner_organization_id not in (None, organization_id):
        if marketplace.type != MarketplaceType.PUBLIC_MARKETPLACE:
            raise _not_found("Marketplace")
    pkg = await db.get(ReusablePackage, data.package_id)
    if pkg is None or pkg.deleted_at is not None:
        raise _not_found("Package")
    if pkg.organization_id is not None and pkg.organization_id != organization_id:
        raise _not_found("Package")
    pub = await _get_publisher(db, data.publisher_id)
    if pub.verification_status in ("SUSPENDED", "REVOKED"):
        raise HTTPException(status_code=409, detail={
            "error": "Publisher is suspended", "code": "PUBLISHER_SUSPENDED"})
    await _require_publisher_member(db, pub.id, auth_context.user_id)
    try:
        pricing = PricingModel(data.pricing_model.upper())
    except ValueError:
        raise HTTPException(status_code=400, detail={
            "error": "Unknown pricing model", "code": "BAD_PRICING"})
    try:
        clean = sanitize_module.validate_listing_content({
            "title": data.title, "short_description": data.short_description,
            "full_description": data.full_description, "icon": data.icon,
            "banner": data.banner, "screenshots": data.screenshots,
            "videos": data.videos})
    except sanitize_module.ContentError as exc:
        raise HTTPException(status_code=400, detail={
            "error": str(exc), "code": "BAD_CONTENT"})
    dup = (await db.execute(select(MarketplaceListing).where(
        MarketplaceListing.marketplace_id == marketplace.id,
        MarketplaceListing.slug == data.slug,
        MarketplaceListing.deleted_at.is_(None)))).scalar_one_or_none()
    if dup is not None:
        raise HTTPException(status_code=409, detail={
            "error": "Listing slug exists in this marketplace", "code": "SLUG_EXISTS"})
    listing = MarketplaceListing(
        marketplace_id=marketplace.id, package_id=pkg.id, publisher_id=pub.id,
        slug=data.slug, title=clean["title"],
        short_description=clean.get("short_description", ""),
        full_description=clean.get("full_description", ""),
        icon=clean.get("icon", ""), banner=clean.get("banner", ""),
        screenshots=clean.get("screenshots", []), videos=clean.get("videos", []),
        category=data.category, license=data.license or pkg.license,
        pricing_model=pricing, trust_level=pkg.trust.value,
        status=ListingStatus.DRAFT, created_by=auth_context.user_id)
    db.add(listing)
    await db.flush()
    await _sync_listing_tags(db, listing.id, data.tags)
    await db.commit()
    await db.refresh(listing)
    await ptelemetry.audit(db, organization_id=organization_id,
                           actor_user_id=auth_context.user_id,
                           action="marketplace.listing.create", resource_id=listing.id,
                           metadata={"slug": listing.slug})
    await ptelemetry.emit(db, event_type="LISTING_CREATED", aggregate_id=listing.id,
                          organization_id=organization_id, user_id=auth_context.user_id,
                          payload={"slug": listing.slug})
    await db.commit()
    return _listing_out(
        listing, publisher_slug=pub.slug, publisher_name=pub.display_name,
        verification=pub.verification_status)


@listings_router.get("/{listing_id}",
                     responses={401: {"model": ApiErrorResponse},
                                403: {"model": ApiErrorResponse},
                                404: {"model": ApiErrorResponse}})
async def get_listing(
    request: Request, organization_id: UUID, listing_id: UUID,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "marketplace:read")
    listing = await _get_listing(db, listing_id)
    return await _listing_detail(db, listing, organization_id, auth_context.user_id)


@listings_router.patch("/{listing_id}",
                       responses={400: {"model": ApiErrorResponse},
                                  401: {"model": ApiErrorResponse},
                                  403: {"model": ApiErrorResponse},
                                  404: {"model": ApiErrorResponse},
                                  409: {"model": ApiErrorResponse}})
async def update_listing(
    request: Request, organization_id: UUID, listing_id: UUID, data: ListingUpdate,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "marketplace:update")
    from openagent.packages import telemetry as ptelemetry

    listing = await _get_listing(db, listing_id)
    await _listing_accessible(db, listing, organization_id)
    if listing.status not in (ListingStatus.DRAFT, ListingStatus.REJECTED,
                              ListingStatus.APPROVED):
        raise HTTPException(status_code=409, detail={
            "error": f"Listing in {listing.status.value} cannot be edited",
            "code": "BAD_STATE"})
    await _require_publisher_member(db, listing.publisher_id, auth_context.user_id)
    patch = {k: v for k, v in data.model_dump().items()
             if v is not None and k != "tags"}
    if patch:
        try:
            clean = sanitize_module.validate_listing_content(patch)
        except sanitize_module.ContentError as exc:
            raise HTTPException(status_code=400, detail={
                "error": str(exc), "code": "BAD_CONTENT"})
        for key, value in clean.items():
            setattr(listing, key, value)
    if data.tags is not None:
        await _sync_listing_tags(db, listing.id, data.tags)
    await db.commit()
    await db.refresh(listing)
    await ptelemetry.audit(db, organization_id=organization_id,
                           actor_user_id=auth_context.user_id,
                           action="marketplace.listing.update", resource_id=listing.id)
    await db.commit()
    return await _listing_detail(db, listing, organization_id, auth_context.user_id)


class ListingVersionAdd(BaseModel):
    version_id: UUID
    changelog: dict[str, Any] = Field(default_factory=dict)


@listings_router.post("/{listing_id}/versions", status_code=status.HTTP_201_CREATED,
                      responses={400: {"model": ApiErrorResponse},
                                 401: {"model": ApiErrorResponse},
                                 403: {"model": ApiErrorResponse},
                                 404: {"model": ApiErrorResponse},
                                 409: {"model": ApiErrorResponse}})
async def add_listing_version(
    request: Request, organization_id: UUID, listing_id: UUID, data: ListingVersionAdd,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "marketplace:update")
    from openagent.packages import telemetry as ptelemetry

    listing = await _get_listing(db, listing_id)
    await _listing_accessible(db, listing, organization_id)
    await _require_publisher_member(db, listing.publisher_id, auth_context.user_id)
    version = await db.get(PackageVersion, data.version_id)
    if version is None or version.package_id != listing.package_id:
        raise _not_found("Package version")
    if version.status not in (PackageVersionStatus.PUBLISHED, PackageVersionStatus.DEPRECATED,
                              PackageVersionStatus.VALIDATED):
        raise HTTPException(status_code=409, detail={
            "error": f"Version {version.version} is not submittable "
                     f"({version.status.value})", "code": "BAD_VERSION_STATE"})
    allowed_keys = {"added", "changed", "fixed", "security", "breaking",
                    "dependencies", "permissions", "notes"}
    changelog = {k: data.changelog.get(k, []) for k in allowed_keys
                 if k in data.changelog}
    changelog["notes"] = str(data.changelog.get("notes", ""))[:2000]
    dup = (await db.execute(select(MarketplaceListingVersion).where(
        MarketplaceListingVersion.listing_id == listing.id,
        MarketplaceListingVersion.version_id == version.id))).scalar_one_or_none()
    if dup is not None:
        raise HTTPException(status_code=409, detail={
            "error": "Version already attached to listing", "code": "VERSION_EXISTS"})
    # Only one current version: listing-version identity stays unambiguous.
    from sqlalchemy import update as _update

    await db.execute(_update(MarketplaceListingVersion).where(
        MarketplaceListingVersion.listing_id == listing.id).values(is_current=False))
    row = MarketplaceListingVersion(
        listing_id=listing.id, version_id=version.id, version=version.version,
        changelog=changelog, is_current=True)
    db.add(row)
    listing.published_version = version.version
    listing.published_version_id = version.id
    await db.commit()
    await ptelemetry.audit(db, organization_id=organization_id,
                           actor_user_id=auth_context.user_id,
                           action="marketplace.listing.version.add",
                           resource_id=listing.id,
                           metadata={"version": version.version})
    await db.commit()
    return {"listing_id": str(listing.id), "version": version.version,
            "version_id": str(version.id), "changelog": changelog}


async def _run_listing_pipeline(db: AsyncSession, listing: MarketplaceListing,
                                marketplace: Marketplace, *,
                                actor=None, organization_id=None) -> dict:
    """Controlled publication pipeline reusing MP22 validation (no second validator)."""
    from openagent.packages import security as security_module
    from openagent.packages import telemetry as ptelemetry
    from openagent.packages import validation as validation_module

    rules = await _policy_rules(db, marketplace.id)
    pkg = await db.get(ReusablePackage, listing.package_id)
    if pkg is None:
        raise HTTPException(status_code=409, detail={
            "error": "Package missing", "code": "NO_PACKAGE"})
    current = (await db.execute(select(MarketplaceListingVersion).where(
        MarketplaceListingVersion.listing_id == listing.id,
        MarketplaceListingVersion.is_current.is_(True)))).scalar_one_or_none()
    if current is None:
        raise HTTPException(status_code=409, detail={
            "error": "Attach a version before submitting", "code": "NO_VERSION"})
    version = await db.get(PackageVersion, current.version_id)
    if version is None:
        raise HTTPException(status_code=409, detail={
            "error": "Package version missing", "code": "NO_VERSION"})
    if version.status == PackageVersionStatus.REVOKED:
        raise HTTPException(status_code=409, detail={
            "error": "Version was revoked", "code": "REVOKED_VERSION"})
    pub = await _get_publisher(db, listing.publisher_id)
    if pub.verification_status in ("SUSPENDED", "REVOKED"):
        raise HTTPException(status_code=409, detail={
            "error": "Publisher is suspended", "code": "PUBLISHER_SUSPENDED"})

    await _transition_listing(db, listing, ListingStatus.VALIDATING.value,
                              actor=actor, organization_id=organization_id)
    report = validation_module.validate_package(dict(version.manifest or {}))
    if not report["passed"]:
        await _transition_listing(db, listing, ListingStatus.DRAFT.value,
                                  actor=actor, reason="validation failed",
                                  organization_id=organization_id)
        await db.commit()
        raise HTTPException(status_code=400, detail={
            "error": "Package failed validation", "code": "VALIDATION_FAILED",
            "findings": report["findings"][:25]})
    findings = security_module.scan_manifest_dict(dict(version.manifest or {}))
    risk = security_module.risk_level(findings)
    listing.security_status = risk
    version.risk = risk
    await db.flush()
    manifest = dict(version.manifest or {})
    policy_result = policy_module.evaluate_listing_policy(
        rules=rules, package_license=pkg.license,
        dependency_licenses=[str(d.get("license", "")) for d in
                             (manifest.get("dependencies") or [])
                             if isinstance(d, dict)],
        risk=risk,
        publisher_verified=pub.verification_status in ("VERIFIED", "OFFICIAL"),
        security_scan_passed=True,
        dependencies=[{"package": d.get("package")} for d in
                      (manifest.get("dependencies") or []) if isinstance(d, dict)],
        permissions=[str(p) for r in (manifest.get("resources") or [])
                     if isinstance(r, dict)
                     for p in ((r.get("payload") or {}).get("permissions") or [])],
        package_type=pkg.package_type.value)
    if not policy_result["passed"]:
        await _transition_listing(db, listing, ListingStatus.DRAFT.value,
                                  actor=actor, reason="marketplace policy failed",
                                  organization_id=organization_id)
        await db.commit()
        raise HTTPException(status_code=400, detail={
            "error": "Marketplace policy check failed", "code": "POLICY_FAILED",
            "findings": policy_result["findings"]})
    listing.trust_level = pkg.trust.value
    await _transition_listing(db, listing, ListingStatus.UNDER_REVIEW.value,
                              actor=actor, organization_id=organization_id)
    if not rules.get("review_required", True):
        await _transition_listing(db, listing, ListingStatus.APPROVED.value,
                                  actor=actor, reason="policy: review not required",
                                  organization_id=organization_id)
    await db.commit()
    await ptelemetry.emit(db, event_type="LISTING_SUBMITTED", aggregate_id=listing.id,
                          organization_id=organization_id, user_id=actor,
                          payload={"version": version.version, "risk": risk})
    await db.commit()
    return {"status": listing.status.value, "risk": risk,
            "policy_findings": policy_result["findings"]}


@listings_router.post("/{listing_id}/submit",
                      responses={400: {"model": ApiErrorResponse},
                                 401: {"model": ApiErrorResponse},
                                 403: {"model": ApiErrorResponse},
                                 404: {"model": ApiErrorResponse},
                                 409: {"model": ApiErrorResponse},
                                 429: {"model": ApiErrorResponse}})
async def submit_listing(
    request: Request, organization_id: UUID, listing_id: UUID,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "marketplace:update")
    await _rate_limited(request, "listing-submit", 20, 3600)
    listing = await _get_listing(db, listing_id)
    marketplace = await _listing_accessible(db, listing, organization_id)
    if listing.status != ListingStatus.DRAFT:
        raise HTTPException(status_code=409, detail={
            "error": f"Only DRAFT listings can be submitted (is {listing.status.value})",
            "code": "BAD_STATE"})
    await _require_publisher_member(db, listing.publisher_id, auth_context.user_id)
    await _transition_listing(db, listing, ListingStatus.SUBMITTED.value,
                              actor=auth_context.user_id,
                              organization_id=organization_id)
    await db.commit()
    return await _run_listing_pipeline(
        db, listing, marketplace, actor=auth_context.user_id,
        organization_id=organization_id)


class ModerationInput(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


async def _moderate_listing(request: Request, db: AsyncSession, organization_id: UUID,
                            listing_id: UUID, target: str,
                            auth_context, reason: str = "") -> dict:
    from openagent.packages import telemetry as ptelemetry

    listing = await _get_listing(db, listing_id)
    marketplace = await _listing_accessible(db, listing, organization_id)
    # Moderated transitions need marketplace:manage or platform ownership.
    try:
        await _need(request, db, "marketplace:manage")
        moderator = True
    except HTTPException:
        moderator = bool(auth_context.is_platform_owner)
        if not moderator:
            raise HTTPException(status_code=403, detail={
                "error": "Moderation permission required", "code": "FORBIDDEN"})
    if target in MODERATED_TRANSITIONS and not moderator:
        raise HTTPException(status_code=403, detail={
            "error": "Moderation permission required", "code": "FORBIDDEN"})
    await _transition_listing(db, listing, target, actor=auth_context.user_id,
                              reason=reason, organization_id=organization_id)
    db.add(ModerationActionRecord(
        marketplace_id=marketplace.id, target_type="listing", target_id=listing.id,
        action=ModerationAction(target), reason=reason[:2000],
        moderator_user_id=auth_context.user_id))
    await db.commit()
    # Notify publisher members of the decision.
    member_ids = await _publisher_member_ids(db, listing.publisher_id)
    notif_map = {
        "APPROVED": "LISTING_APPROVED", "REJECTED": "LISTING_REJECTED",
        "SUSPENDED": "MODERATION_DECISION", "REVOKED": "MODERATION_DECISION",
        "PUBLISHED": "LISTING_APPROVED",
    }
    if target in notif_map:
        await _notify(
            db, user_ids=[m for m in member_ids if m != str(auth_context.user_id)],
            notif_type=notif_map[target],
            title=f"Listing '{listing.title}' → {target}",
            body=reason[:500], organization_id=organization_id,
            listing_id=listing.id, publisher_id=listing.publisher_id)
    await ptelemetry.emit(db, event_type=f"LISTING_{target}",
                          aggregate_id=listing.id,
                          organization_id=organization_id,
                          user_id=auth_context.user_id,
                          payload={"reason": reason[:500]})
    await db.commit()
    return await _listing_detail(db, listing, organization_id, auth_context.user_id)


@listings_router.post("/{listing_id}/approve",
                      responses={401: {"model": ApiErrorResponse},
                                 403: {"model": ApiErrorResponse},
                                 404: {"model": ApiErrorResponse},
                                 409: {"model": ApiErrorResponse}})
async def approve_listing(
    request: Request, organization_id: UUID, listing_id: UUID, data: ModerationInput,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    return await _moderate_listing(request, db, organization_id, listing_id,
                                   ListingStatus.APPROVED.value, auth_context,
                                   data.reason)


@listings_router.post("/{listing_id}/reject",
                      responses={401: {"model": ApiErrorResponse},
                                 403: {"model": ApiErrorResponse},
                                 404: {"model": ApiErrorResponse},
                                 409: {"model": ApiErrorResponse}})
async def reject_listing(
    request: Request, organization_id: UUID, listing_id: UUID, data: ModerationInput,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    return await _moderate_listing(request, db, organization_id, listing_id,
                                   ListingStatus.REJECTED.value, auth_context,
                                   data.reason)


@listings_router.post("/{listing_id}/request-changes",
                      responses={401: {"model": ApiErrorResponse},
                                 403: {"model": ApiErrorResponse},
                                 404: {"model": ApiErrorResponse},
                                 409: {"model": ApiErrorResponse}})
async def request_listing_changes(
    request: Request, organization_id: UUID, listing_id: UUID, data: ModerationInput,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    # Request-changes returns the listing to DRAFT with reviewer notes.
    listing = await _get_listing(db, listing_id)
    await _listing_accessible(db, listing, organization_id)
    try:
        await _need(request, db, "marketplace:manage")
    except HTTPException:
        if not auth_context.is_platform_owner:
            raise HTTPException(status_code=403, detail={
                "error": "Moderation permission required", "code": "FORBIDDEN"})
    if listing.status != ListingStatus.UNDER_REVIEW:
        raise HTTPException(status_code=409, detail={
            "error": "Only listings under review can be sent back", "code": "BAD_STATE"})
    await _transition_listing(db, listing, ListingStatus.DRAFT.value,
                              actor=auth_context.user_id,
                              reason=f"changes requested: {data.reason}",
                              organization_id=organization_id)
    member_ids = await _publisher_member_ids(db, listing.publisher_id)
    await _notify(db, user_ids=member_ids, notif_type="MODERATION_DECISION",
                  title=f"Changes requested for '{listing.title}'",
                  body=data.reason[:500], organization_id=organization_id,
                  listing_id=listing.id, publisher_id=listing.publisher_id)
    await db.commit()
    return await _listing_detail(db, listing, organization_id, auth_context.user_id)


@listings_router.post("/{listing_id}/publish",
                      responses={401: {"model": ApiErrorResponse},
                                 403: {"model": ApiErrorResponse},
                                 404: {"model": ApiErrorResponse},
                                 409: {"model": ApiErrorResponse}})
async def publish_listing(
    request: Request, organization_id: UUID, listing_id: UUID,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    listing = await _get_listing(db, listing_id)
    await _listing_accessible(db, listing, organization_id)
    if listing.status != ListingStatus.APPROVED:
        raise HTTPException(status_code=409, detail={
            "error": "Only APPROVED listings can be published", "code": "BAD_STATE"})
    # Publishing an approved listing is a publisher action (OWNER/ADMIN),
    # not moderation: approval already happened. Moderators can also publish
    # via the master console.
    await _require_publisher_member(db, listing.publisher_id, auth_context.user_id,
                                    roles=("OWNER", "ADMIN"))
    from openagent.packages import telemetry as ptelemetry

    await _transition_listing(db, listing, ListingStatus.PUBLISHED.value,
                              actor=auth_context.user_id,
                              reason="published by publisher",
                              organization_id=organization_id)
    member_ids = await _publisher_member_ids(db, listing.publisher_id)
    await _notify(db, user_ids=member_ids, notif_type="LISTING_APPROVED",
                  title=f"Listing '{listing.title}' is live",
                  body="", organization_id=organization_id,
                  listing_id=listing.id, publisher_id=listing.publisher_id)
    await ptelemetry.emit(db, event_type="LISTING_PUBLISHED",
                          aggregate_id=listing.id,
                          organization_id=organization_id,
                          user_id=auth_context.user_id,
                          payload={"version": listing.published_version})
    await db.commit()
    return await _listing_detail(db, listing, organization_id, auth_context.user_id)


@listings_router.post("/{listing_id}/suspend",
                      responses={401: {"model": ApiErrorResponse},
                                 403: {"model": ApiErrorResponse},
                                 404: {"model": ApiErrorResponse},
                                 409: {"model": ApiErrorResponse}})
async def suspend_listing(
    request: Request, organization_id: UUID, listing_id: UUID, data: ModerationInput,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    return await _moderate_listing(request, db, organization_id, listing_id,
                                   ListingStatus.SUSPENDED.value, auth_context,
                                   data.reason)


@listings_router.post("/{listing_id}/restore",
                      responses={401: {"model": ApiErrorResponse},
                                 403: {"model": ApiErrorResponse},
                                 404: {"model": ApiErrorResponse},
                                 409: {"model": ApiErrorResponse}})
async def restore_listing(
    request: Request, organization_id: UUID, listing_id: UUID, data: ModerationInput,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    return await _moderate_listing(request, db, organization_id, listing_id,
                                   ListingStatus.PUBLISHED.value, auth_context,
                                   data.reason)


@listings_router.post("/{listing_id}/deprecate",
                      responses={401: {"model": ApiErrorResponse},
                                 403: {"model": ApiErrorResponse},
                                 404: {"model": ApiErrorResponse},
                                 409: {"model": ApiErrorResponse}})
async def deprecate_listing(
    request: Request, organization_id: UUID, listing_id: UUID, data: ModerationInput,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    listing = await _get_listing(db, listing_id)
    await _listing_accessible(db, listing, organization_id)
    await _require_publisher_member(db, listing.publisher_id, auth_context.user_id,
                                    roles=("OWNER", "ADMIN"))
    await _transition_listing(db, listing, ListingStatus.DEPRECATED.value,
                              actor=auth_context.user_id, reason=data.reason,
                              organization_id=organization_id)
    await db.commit()
    return await _listing_detail(db, listing, organization_id, auth_context.user_id)


class RevokeListingInput(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)
    revoke_package_version: bool = False
    recommended_version: str = Field(default="", max_length=32)


@listings_router.post("/{listing_id}/revoke",
                      responses={401: {"model": ApiErrorResponse},
                                 403: {"model": ApiErrorResponse},
                                 404: {"model": ApiErrorResponse},
                                 409: {"model": ApiErrorResponse}})
async def revoke_listing(
    request: Request, organization_id: UUID, listing_id: UUID, data: RevokeListingInput,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Revoke a listing; optionally cascade to the package version + advisory + notify."""
    from openagent.packages import telemetry as ptelemetry

    listing = await _get_listing(db, listing_id)
    marketplace = await _listing_accessible(db, listing, organization_id)
    try:
        await _need(request, db, "marketplace:manage")
    except HTTPException:
        if not auth_context.is_platform_owner:
            raise HTTPException(status_code=403, detail={
                "error": "Moderation permission required", "code": "FORBIDDEN"})
    await _transition_listing(db, listing, ListingStatus.REVOKED.value,
                              actor=auth_context.user_id, reason=data.reason,
                              organization_id=organization_id)
    db.add(ModerationActionRecord(
        marketplace_id=marketplace.id, target_type="listing", target_id=listing.id,
        action=ModerationAction.REVOKE, reason=data.reason[:2000],
        moderator_user_id=auth_context.user_id))
    if data.revoke_package_version and listing.published_version_id:
        version = await db.get(PackageVersion, listing.published_version_id)
        if version is not None and version.status != PackageVersionStatus.REVOKED:
            version.status = PackageVersionStatus.REVOKED
            version.revoked_reason = f"marketplace revocation: {data.reason[:500]}"
            version.revoked_at = _now()
            db.add(PackageRevocation(
                package_id=listing.package_id, version_id=version.id,
                reason=data.reason[:2000], revoked_by=auth_context.user_id,
                recommended_version=data.recommended_version))
            await ptelemetry.emit(
                db, event_type="PACKAGE_REVOKED", aggregate_id=listing.package_id,
                organization_id=organization_id, user_id=auth_context.user_id,
                payload={"version": version.version, "via": "marketplace"})
    # Notify installers + followers; history is preserved, never deleted.
    installer_ids = [str(r[0]) for r in (await db.execute(
        select(PackageInstallation.installed_by).where(
            PackageInstallation.package_id == listing.package_id,
            PackageInstallation.status == PackageInstallStatus.INSTALLED))).all()
        if r[0] is not None]
    follower_ids = [str(r[0]) for r in (await db.execute(
        select(PublisherFollower.user_id).where(
            PublisherFollower.publisher_id == listing.publisher_id))).all()]
    await _notify(db, user_ids=installer_ids + follower_ids,
                  notif_type="REVOKED_PACKAGE",
                  title=f"Package revoked: {listing.title}",
                  body=(f"{data.reason[:300]} "
                        f"Recommended: {data.recommended_version or 'none'}"),
                  organization_id=organization_id, listing_id=listing.id,
                  publisher_id=listing.publisher_id)
    mtelemetry.inc("marketplace_revocation_total")
    await db.commit()
    return await _listing_detail(db, listing, organization_id, auth_context.user_id)


@listings_router.get("/{listing_id}/versions",
                     responses={401: {"model": ApiErrorResponse},
                                403: {"model": ApiErrorResponse},
                                404: {"model": ApiErrorResponse}})
async def listing_versions(
    request: Request, organization_id: UUID, listing_id: UUID,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "marketplace:read")
    listing = await _get_listing(db, listing_id)
    await _listing_accessible(db, listing, organization_id)
    rows = list((await db.execute(select(MarketplaceListingVersion).where(
        MarketplaceListingVersion.listing_id == listing.id)
        .order_by(MarketplaceListingVersion.created_at.desc()))).scalars().all())
    return {"data": [{
        "version": r.version, "version_id": str(r.version_id),
        "is_current": r.is_current, "changelog": r.changelog,
        "created_at": r.created_at.isoformat()} for r in rows]}


@listings_router.get("/{listing_id}/security",
                     responses={401: {"model": ApiErrorResponse},
                                403: {"model": ApiErrorResponse},
                                404: {"model": ApiErrorResponse}})
async def listing_security(
    request: Request, organization_id: UUID, listing_id: UUID,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "marketplace:read")
    from openagent.packages import security as security_module

    listing = await _get_listing(db, listing_id)
    await _listing_accessible(db, listing, organization_id)
    version = (await db.get(PackageVersion, listing.published_version_id)
               if listing.published_version_id else None)
    findings = (security_module.scan_manifest_dict(dict(version.manifest or {}))
                if version else [])
    advisories = list((await db.execute(select(SecurityAdvisory).where(
        SecurityAdvisory.listing_id == listing.id))).scalars().all())
    sig = None
    if version is not None:
        sig = (await db.execute(select(PackageSignature).where(
            PackageSignature.version_id == version.id))).scalar_one_or_none()
    return {
        "risk": security_module.risk_level(findings),
        "trust_level": listing.trust_level,
        "security_status": listing.security_status,
        "findings": findings,
        "signature": ("VALID" if sig and sig.verified else
                      "UNSIGNED" if sig is None else "INVALID"),
        "advisories": [{
            "id": str(a.id), "title": a.title, "severity": a.severity.value,
            "status": a.status.value, "affected_versions": a.affected_versions,
            "recommended_version": a.recommended_version} for a in advisories],
    }


@listings_router.get("/{listing_id}/health",
                     responses={401: {"model": ApiErrorResponse},
                                403: {"model": ApiErrorResponse},
                                404: {"model": ApiErrorResponse}})
async def listing_health(
    request: Request, organization_id: UUID, listing_id: UUID,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "marketplace:read")
    listing = await _get_listing(db, listing_id)
    await _listing_accessible(db, listing, organization_id)
    advisories = list((await db.execute(select(SecurityAdvisory).where(
        SecurityAdvisory.listing_id == listing.id,
        SecurityAdvisory.status == AdvisoryStatus.AFFECTED))).scalars().all())
    latest_result = None
    if listing.published_version_id:
        latest_result = (await db.execute(
            select(PackageValidationResult)
            .where(PackageValidationResult.version_id == listing.published_version_id)
            .order_by(PackageValidationResult.created_at.desc()))).scalars().first()
    installs_total = (await db.execute(select(func.count(PackageInstallation.id)).where(
        PackageInstallation.package_id == listing.package_id))).scalar_one()
    installs_ok = (await db.execute(select(func.count(PackageInstallation.id)).where(
        PackageInstallation.package_id == listing.package_id,
        PackageInstallation.status == PackageInstallStatus.INSTALLED))).scalar_one()
    flagged = (await db.execute(select(func.count(ListingReview.id)).where(
        ListingReview.listing_id == listing.id,
        ListingReview.status.in_([ReviewStatus.FLAGGED, ReviewStatus.HIDDEN])))).scalar_one()
    total_reviews = (await db.execute(select(func.count(ListingReview.id)).where(
        ListingReview.listing_id == listing.id))).scalar_one()
    return health_module.compute_health(
        revoked=listing.status == ListingStatus.REVOKED,
        open_advisories=[{"severity": a.severity.value} for a in advisories],
        last_validation_passed=(latest_result.passed if latest_result else None),
        install_success_rate=(installs_ok / installs_total if installs_total else None),
        install_samples=installs_total,
        rating_average=listing.rating_average, rating_count=listing.rating_count,
        flagged_review_ratio=(flagged / total_reviews if total_reviews else 0.0),
        deprecated=listing.status == ListingStatus.DEPRECATED)


@listings_router.get("/{listing_id}/timeline",
                     responses={401: {"model": ApiErrorResponse},
                                403: {"model": ApiErrorResponse},
                                404: {"model": ApiErrorResponse}})
async def listing_timeline(
    request: Request, organization_id: UUID, listing_id: UUID,
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "marketplace:read")
    from openagent.core.events import Event
    from openagent.db.models.audit_log import AuditLog

    listing = await _get_listing(db, listing_id)
    await _listing_accessible(db, listing, organization_id)
    events = list((await db.execute(select(Event).where(
        Event.aggregate_id == listing.id)
        .order_by(Event.created_at.desc()).limit(page_size))).scalars().all())
    audits = list((await db.execute(select(AuditLog).where(
        AuditLog.resource_id == listing.id)
        .order_by(AuditLog.created_at.desc()).limit(page_size))).scalars().all())
    merged: list[dict[str, Any]] = sorted(
        [{"kind": "event", "type": e.event_type, "at": e.created_at.isoformat(),
          "payload": e.payload} for e in events] +
        [{"kind": "audit", "type": a.action, "at": a.created_at.isoformat(),
          "actor": str(a.actor_user_id) if a.actor_user_id else None,
          "metadata": a.metadata} for a in audits],
        key=lambda item: str(item["at"]), reverse=True)[:page_size]
    return {"data": merged,
            "meta": create_pagination_meta(page, page_size, len(merged)).model_dump()}


@listings_router.get("/{listing_id}/analytics",
                     responses={401: {"model": ApiErrorResponse},
                                403: {"model": ApiErrorResponse},
                                404: {"model": ApiErrorResponse}})
async def listing_analytics(
    request: Request, organization_id: UUID, listing_id: UUID, days: int = Query(30, ge=1, le=365),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "marketplace:read")
    listing = await _get_listing(db, listing_id)
    await _listing_accessible(db, listing, organization_id)
    member_ids = await _publisher_member_ids(db, listing.publisher_id)
    if (str(auth_context.user_id) not in member_ids
            and "marketplace:manage" not in (auth_context.permissions or set())
            and not auth_context.is_platform_owner):
        raise HTTPException(status_code=403, detail={
            "error": "Publisher or moderator access required", "code": "FORBIDDEN"})
    rows = list((await db.execute(select(MarketplaceAnalyticsDaily).where(
        MarketplaceAnalyticsDaily.listing_id == listing.id)
        .order_by(MarketplaceAnalyticsDaily.day.desc()).limit(days))).scalars().all())
    totals: dict[str, int] = {k: 0 for k in ("views", "clicks", "installs_started", "installs_completed",
                             "installs_failed", "updates", "uninstalls", "favorites",
                             "shares", "reviews")}
    series: list[dict[str, Any]] = []
    for row in reversed(rows):
        point: dict[str, Any] = {"day": row.day.isoformat()}
        for key in totals:
            value = getattr(row, key) or 0
            totals[key] += value
            point[key] = value
        series.append(point)
    return {"totals": {**totals,
                       "install_count": listing.install_count,
                       "successful_install_count": listing.successful_install_count,
                       "active_install_count": listing.active_install_count,
                       "favorite_count": listing.favorite_count,
                       "view_count": listing.view_count,
                       "rating_average": listing.rating_average,
                       "rating_count": listing.rating_count},
            "series": series}


class ListingInstallInput(BaseModel):
    version: str = Field(default="", max_length=32)
    values: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = Field(default="", max_length=100)


@listings_router.post("/{listing_id}/install",
                      responses={400: {"model": ApiErrorResponse},
                                 401: {"model": ApiErrorResponse},
                                 402: {"model": ApiErrorResponse},
                                 403: {"model": ApiErrorResponse},
                                 404: {"model": ApiErrorResponse},
                                 409: {"model": ApiErrorResponse},
                                 429: {"model": ApiErrorResponse}})
async def install_listing(
    request: Request, organization_id: UUID, listing_id: UUID, data: ListingInstallInput,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Marketplace install: entitlement gate -> artifact verify -> MP22 installer."""
    await _need(request, db, "package:execute")
    await _rate_limited(request, "listing-install", 30, 3600)
    from openagent.packages import installer as installer_module

    listing = await _get_listing(db, listing_id)
    await _listing_accessible(db, listing, organization_id, for_install=True)
    version = None
    if data.version:
        version = (await db.execute(select(PackageVersion).where(
            PackageVersion.package_id == listing.package_id,
            PackageVersion.version == data.version))).scalar_one_or_none()
        if version is None:
            raise _not_found("Package version")
    elif listing.published_version_id:
        version = await db.get(PackageVersion, listing.published_version_id)
    if version is None:
        raise HTTPException(status_code=409, detail={
            "error": "Listing has no published version", "code": "NO_VERSION"})
    if version.status == PackageVersionStatus.REVOKED:
        raise HTTPException(status_code=409, detail={
            "error": "Version was revoked", "code": "REVOKED"})
    # Commercial gate (free listings always pass; never grants runtime perms).
    ents = list((await db.execute(select(Entitlement).where(
        Entitlement.listing_id == listing.id,
        Entitlement.status.in_([EntitlementStatus.ACTIVE, EntitlementStatus.TRIAL])))).scalars().all())
    allowed, code, message = ent_module.can_install_listing(
        pricing_model=listing.pricing_model.value,
        entitlements=[{"organization_id": str(e.organization_id) if e.organization_id else "",
                       "user_id": str(e.user_id) if e.user_id else "",
                       "status": e.status.value,
                       "valid_from": e.valid_from.isoformat() if e.valid_from else "",
                       "valid_until": e.valid_until.isoformat() if e.valid_until else ""}
                      for e in ents],
        organization_id=str(organization_id), user_id=str(auth_context.user_id),
        commerce_configured=await _commerce_configured(db))
    if not allowed:
        status_code = 402 if code in ("NEED_ENTITLEMENT", "COMMERCE_DISABLED") else 403
        raise HTTPException(status_code=status_code, detail={
            "error": message, "code": code,
            "pricing_model": listing.pricing_model.value})
    # Distribution integrity: verify artifact when one is published.
    artifact = (await db.execute(select(DistributionArtifact).where(
        DistributionArtifact.version_id == version.id,
        DistributionArtifact.artifact_type == ArtifactType.PACKAGE_ARCHIVE,
        DistributionArtifact.status == ArtifactStatus.PUBLISHED)
        .order_by(DistributionArtifact.created_at.desc()))).scalars().first()
    signature_status = "UNSIGNED"
    if artifact is not None:
        from openagent.marketplace.distribution import LocalArtifactStorage

        stored = await LocalArtifactStorage().get(artifact.storage_key)
        if stored is None or len(stored) != artifact.size_bytes:
            raise HTTPException(status_code=409, detail={
                "error": "Distribution artifact unavailable or truncated",
                "code": "ARTIFACT_UNAVAILABLE"})
        from openagent.marketplace.distribution import sha256_bytes

        if sha256_bytes(stored) != artifact.sha256:
            raise HTTPException(status_code=409, detail={
                "error": "Distribution artifact corrupted (hash mismatch)",
                "code": "ARTIFACT_CORRUPT"})
        signature_status = artifact.signature_status
    else:
        sig = (await db.execute(select(PackageSignature).where(
            PackageSignature.version_id == version.id))).scalar_one_or_none()
        signature_status = ("VALID" if sig and sig.verified else "UNSIGNED")
    await _record_event(db, listing=listing, event_type="INSTALL_STARTED",
                        organization_id=organization_id, user_id=auth_context.user_id,
                        metadata={"version": version.version})
    listing.install_count = (listing.install_count or 0) + 1
    mtelemetry.inc("marketplace_install_started_total")
    try:
        installation = await installer_module.install(
            db, organization_id=organization_id, version_id=version.id,
            installed_by=auth_context.user_id, values=data.values,
            idempotency_key=data.idempotency_key)
    except installer_module.InstallationError as exc:
        listing.install_count = max(0, (listing.install_count or 1) - 1)
        await _record_event(db, listing=listing, event_type="INSTALL_FAILED",
                            organization_id=organization_id,
                            user_id=auth_context.user_id,
                            metadata={"version": version.version, "error": str(exc)})
        mtelemetry.inc("marketplace_install_failed_total")
        await db.commit()
        http_status = 400 if exc.code in ("VALIDATION_FAILED", "NOT_PUBLISHED") else 409
        raise HTTPException(status_code=http_status,
                            detail={"error": str(exc), "code": exc.code})
    listing.successful_install_count = (listing.successful_install_count or 0) + 1
    listing.active_install_count = (listing.active_install_count or 0) + 1
    await _record_event(db, listing=listing, event_type="INSTALL_COMPLETED",
                        organization_id=organization_id, user_id=auth_context.user_id,
                        metadata={"version": version.version,
                                  "installation_id": str(installation.id)})
    mtelemetry.inc("marketplace_install_completed_total")
    await db.commit()
    return {"id": str(installation.id), "status": installation.status.value,
            "version": version.version, "version_id": str(version.id),
            "signature": signature_status, "error": installation.error}


async def _commerce_configured(db: AsyncSession) -> bool:
    """True when at least one billing provider row is configured.

    No provider rows exist in this phase (MP24), so paid listings report
    COMMERCE_DISABLED honestly instead of pretending to sell.
    """
    return False


# ---------------------------------------------------------------------------
# Publishers
# ---------------------------------------------------------------------------

class PublisherCreate(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)
    slug: str = Field(min_length=1, max_length=120, pattern="^[a-z0-9]+(?:[-][a-z0-9]+)*$")
    publisher_type: str = Field(default="INDIVIDUAL")
    description: str = Field(default="", max_length=2000)
    website: str = Field(default="", max_length=500)
    avatar: str = Field(default="", max_length=500)
    banner: str = Field(default="", max_length=500)
    social_links: dict[str, Any] = Field(default_factory=dict)
    organization_id: Optional[UUID] = None


class PublisherUpdate(BaseModel):
    display_name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    description: Optional[str] = None
    website: Optional[str] = None
    avatar: Optional[str] = None
    banner: Optional[str] = None
    social_links: Optional[dict[str, Any]] = None


@publishers_router.get("",
                       responses={401: {"model": ApiErrorResponse},
                                  403: {"model": ApiErrorResponse}})
async def list_publishers(
    request: Request, q: str = Query(""),
    verification: str = Query(""),
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "publisher:read")
    stmt = select(PublisherProfile)
    count_stmt = select(func.count(PublisherProfile.id))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(PublisherProfile.display_name.ilike(like),
                              PublisherProfile.slug.ilike(like)))
        count_stmt = count_stmt.where(or_(PublisherProfile.display_name.ilike(like),
                                          PublisherProfile.slug.ilike(like)))
    if verification:
        try:
            stmt = stmt.where(PublisherProfile.verification_status ==
                              VerificationStatus(verification.upper()).value)
            count_stmt = count_stmt.where(
                PublisherProfile.verification_status ==
                VerificationStatus(verification.upper()).value)
        except ValueError:
            raise HTTPException(status_code=400, detail={
                "error": "Unknown verification status", "code": "BAD_STATUS"})
    total = (await db.execute(count_stmt)).scalar_one()
    rows = list((await db.execute(stmt.order_by(PublisherProfile.display_name)
                  .limit(page_size).offset((page - 1) * page_size))).scalars().all())
    return {"data": [await _publisher_out(db, r) for r in rows],
            "meta": create_pagination_meta(page, page_size, total).model_dump()}


@publishers_router.post("", status_code=status.HTTP_201_CREATED,
                        responses={400: {"model": ApiErrorResponse},
                                   401: {"model": ApiErrorResponse},
                                   403: {"model": ApiErrorResponse},
                                   409: {"model": ApiErrorResponse}})
async def create_publisher(
    request: Request, data: PublisherCreate,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "publisher:create")
    from openagent.packages import telemetry as ptelemetry

    try:
        ptype = PublisherType(data.publisher_type.upper())
    except ValueError:
        raise HTTPException(status_code=400, detail={
            "error": "Unknown publisher type", "code": "BAD_TYPE"})
    if ptype == PublisherType.OPENAGENT_OFFICIAL and not auth_context.is_platform_owner:
        raise HTTPException(status_code=403, detail={
            "error": "Only platform owners create official publishers",
            "code": "FORBIDDEN"})
    if data.website:
        sanitize_module.check_url(data.website, field="website")
    if data.avatar:
        sanitize_module.check_url(data.avatar, field="avatar")
    if data.banner:
        sanitize_module.check_url(data.banner, field="banner")
    dup = (await db.execute(select(PublisherProfile).where(
        PublisherProfile.slug == data.slug))).scalar_one_or_none()
    if dup is not None:
        raise HTTPException(status_code=409, detail={
            "error": "Publisher slug exists", "code": "SLUG_EXISTS"})
    pub = PublisherProfile(
        organization_id=data.organization_id, user_id=auth_context.user_id,
        display_name=sanitize_module.strip_html(data.display_name),
        slug=data.slug, publisher_type=ptype.value,
        description=sanitize_module.validate_body(data.description or "",
                                                  field="description"),
        website=data.website, avatar=data.avatar, banner=data.banner,
        social_links={str(k)[:64]: str(v)[:500]
                      for k, v in (data.social_links or {}).items()})
    for link in pub.social_links.values():
        sanitize_module.check_url(link, field="social_links")
    db.add(pub)
    await db.flush()
    db.add(PublisherMember(publisher_id=pub.id, user_id=auth_context.user_id,
                           role="OWNER"))
    await db.commit()
    await db.refresh(pub)
    await ptelemetry.audit(db, organization_id=auth_context.organization_id,
                           actor_user_id=auth_context.user_id,
                           action="marketplace.publisher.create", resource_id=pub.id,
                           metadata={"slug": pub.slug})
    await db.commit()
    return await _publisher_out(db, pub)


@publishers_router.get("/{slug}",
                       responses={401: {"model": ApiErrorResponse},
                                  403: {"model": ApiErrorResponse},
                                  404: {"model": ApiErrorResponse}})
async def get_publisher(
    request: Request, slug: str,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "publisher:read")
    pub = await _get_publisher_by_slug(db, slug)
    out = await _publisher_out(db, pub)
    listings = list((await db.execute(select(MarketplaceListing).where(
        MarketplaceListing.publisher_id == pub.id,
        MarketplaceListing.deleted_at.is_(None),
        MarketplaceListing.status == ListingStatus.PUBLISHED)
        .order_by(MarketplaceListing.updated_at.desc()).limit(50))).scalars().all())
    out["listings"] = [
        {**_listing_out(
            listing, publisher_slug=pub.slug, publisher_name=pub.display_name,
            verification=pub.verification_status),
         "marketplace_slug": (await _get_marketplace(db, listing.marketplace_id)).slug}
        for listing in listings]
    out["following"] = (await db.execute(select(PublisherFollower).where(
        PublisherFollower.publisher_id == pub.id,
        PublisherFollower.user_id == auth_context.user_id))).scalar_one_or_none() is not None
    ratings = [r.rating_average for r in listings if r.rating_count]
    out["average_rating"] = round(sum(ratings) / len(ratings), 2) if ratings else 0.0
    return out


@publishers_router.patch("/{slug}",
                         responses={400: {"model": ApiErrorResponse},
                                    401: {"model": ApiErrorResponse},
                                    403: {"model": ApiErrorResponse},
                                    404: {"model": ApiErrorResponse}})
async def update_publisher(
    request: Request, slug: str, data: PublisherUpdate,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "publisher:update")
    from openagent.packages import telemetry as ptelemetry

    pub = await _get_publisher_by_slug(db, slug)
    await _require_publisher_member(db, pub.id, auth_context.user_id,
                                    roles=("OWNER", "ADMIN"))
    if data.display_name is not None:
        pub.display_name = sanitize_module.strip_html(data.display_name)
    if data.description is not None:
        pub.description = sanitize_module.validate_body(data.description,
                                                        field="description")
    if data.website is not None:
        if data.website:
            sanitize_module.check_url(data.website, field="website")
        pub.website = data.website
    if data.avatar is not None:
        if data.avatar:
            sanitize_module.check_url(data.avatar, field="avatar")
        pub.avatar = data.avatar
    if data.banner is not None:
        if data.banner:
            sanitize_module.check_url(data.banner, field="banner")
        pub.banner = data.banner
    if data.social_links is not None:
        for link in data.social_links.values():
            sanitize_module.check_url(str(link), field="social_links")
        pub.social_links = {str(k)[:64]: str(v)[:500]
                            for k, v in data.social_links.items()}
    await db.commit()
    await db.refresh(pub)
    await ptelemetry.audit(db, organization_id=auth_context.organization_id,
                           actor_user_id=auth_context.user_id,
                           action="marketplace.publisher.update", resource_id=pub.id)
    await db.commit()
    return await _publisher_out(db, pub)


class PublisherMemberAdd(BaseModel):
    user_id: UUID
    role: str = Field(default="MEMBER")


@publishers_router.post("/{slug}/members",
                        responses={400: {"model": ApiErrorResponse},
                                   401: {"model": ApiErrorResponse},
                                   403: {"model": ApiErrorResponse},
                                   404: {"model": ApiErrorResponse},
                                   409: {"model": ApiErrorResponse}})
async def add_publisher_member(
    request: Request, slug: str, data: PublisherMemberAdd,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "publisher:update")
    pub = await _get_publisher_by_slug(db, slug)
    await _require_publisher_member(db, pub.id, auth_context.user_id,
                                    roles=("OWNER", "ADMIN"))
    if data.role not in ("OWNER", "ADMIN", "MEMBER"):
        raise HTTPException(status_code=400, detail={
            "error": "Unknown member role", "code": "BAD_ROLE"})
    dup = (await db.execute(select(PublisherMember).where(
        PublisherMember.publisher_id == pub.id,
        PublisherMember.user_id == data.user_id))).scalar_one_or_none()
    if dup is not None:
        raise HTTPException(status_code=409, detail={
            "error": "Already a member", "code": "ALREADY_MEMBER"})
    db.add(PublisherMember(publisher_id=pub.id, user_id=data.user_id,
                           role=data.role))
    await db.commit()
    return {"publisher_id": str(pub.id), "user_id": str(data.user_id),
            "role": data.role}


@publishers_router.delete("/{slug}/members/{user_id}",
                          status_code=status.HTTP_204_NO_CONTENT,
                          responses={401: {"model": ApiErrorResponse},
                                     403: {"model": ApiErrorResponse},
                                     404: {"model": ApiErrorResponse}})
async def remove_publisher_member(
    request: Request, slug: str, user_id: UUID,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "publisher:update")
    pub = await _get_publisher_by_slug(db, slug)
    await _require_publisher_member(db, pub.id, auth_context.user_id,
                                    roles=("OWNER", "ADMIN"))
    row = (await db.execute(select(PublisherMember).where(
        PublisherMember.publisher_id == pub.id,
        PublisherMember.user_id == user_id))).scalar_one_or_none()
    if row is None:
        raise _not_found("Publisher member")
    owners = (await db.execute(select(func.count(PublisherMember.id)).where(
        PublisherMember.publisher_id == pub.id,
        PublisherMember.role == "OWNER"))).scalar_one()
    if row.role == "OWNER" and owners <= 1:
        raise HTTPException(status_code=409, detail={
            "error": "Cannot remove the last owner", "code": "LAST_OWNER"})
    await db.delete(row)
    await db.commit()


@publishers_router.post("/{slug}/verification/request",
                        responses={401: {"model": ApiErrorResponse},
                                   403: {"model": ApiErrorResponse},
                                   404: {"model": ApiErrorResponse},
                                   409: {"model": ApiErrorResponse}})
async def request_verification(
    request: Request, slug: str,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "publisher:update")
    pub = await _get_publisher_by_slug(db, slug)
    await _require_publisher_member(db, pub.id, auth_context.user_id,
                                    roles=("OWNER", "ADMIN"))
    if pub.verification_status not in ("UNVERIFIED",):
        raise HTTPException(status_code=409, detail={
            "error": f"Cannot request from {pub.verification_status}",
            "code": "BAD_STATE"})
    if not can_transition_verification(pub.verification_status, "PENDING"):
        raise HTTPException(status_code=409, detail={
            "error": "Illegal verification transition", "code": "BAD_TRANSITION"})
    pub.verification_status = VerificationStatus.PENDING.value
    await db.commit()
    return {"slug": pub.slug, "verification_status": pub.verification_status}


class VerificationDecision(BaseModel):
    target: str = Field(pattern="^(VERIFIED|OFFICIAL|UNVERIFIED|SUSPENDED|REVOKED)$")
    reason: str = Field(min_length=1, max_length=2000)


@publishers_router.post("/{slug}/verification/decide",
                        responses={401: {"model": ApiErrorResponse},
                                   403: {"model": ApiErrorResponse},
                                   404: {"model": ApiErrorResponse},
                                   409: {"model": ApiErrorResponse}})
async def decide_verification(
    request: Request, slug: str, data: VerificationDecision,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Verification decision: publisher:manage or platform owner, audited."""
    from openagent.packages import telemetry as ptelemetry

    try:
        await _need(request, db, "publisher:manage")
    except HTTPException:
        if not auth_context.is_platform_owner:
            raise HTTPException(status_code=403, detail={
                "error": "Publisher moderation permission required",
                "code": "FORBIDDEN"})
    pub = await _get_publisher_by_slug(db, slug)
    if not can_transition_verification(pub.verification_status, data.target):
        raise HTTPException(status_code=409, detail={
            "error": f"Illegal verification transition "
                     f"{pub.verification_status} -> {data.target}",
            "code": "BAD_TRANSITION"})
    pub.verification_status = VerificationStatus(data.target).value
    pub.verified = data.target in ("VERIFIED", "OFFICIAL")
    pub.verified_by = auth_context.user_id
    pub.verified_at = _now() if pub.verified else None
    if data.target in ("SUSPENDED", "REVOKED"):
        pub.suspended_reason = data.reason[:1000]
    await db.commit()
    db.add(ModerationActionRecord(
        target_type="publisher", target_id=pub.id,
        action=(ModerationAction.VERIFY_PUBLISHER
                if data.target in ("VERIFIED", "OFFICIAL")
                else ModerationAction.SUSPEND_PUBLISHER),
        reason=data.reason[:2000], moderator_user_id=auth_context.user_id))
    await ptelemetry.audit(db, organization_id=auth_context.organization_id,
                           actor_user_id=auth_context.user_id,
                           action="marketplace.publisher.verify", resource_id=pub.id,
                           metadata={"target": data.target, "reason": data.reason[:500]})
    await ptelemetry.emit(db, event_type="PUBLISHER_VERIFIED", aggregate_id=pub.id,
                          organization_id=auth_context.organization_id,
                          user_id=auth_context.user_id,
                          payload={"status": data.target})
    await db.commit()
    return await _publisher_out(db, pub)


@publishers_router.post("/{slug}/follow",
                        responses={401: {"model": ApiErrorResponse},
                                   403: {"model": ApiErrorResponse},
                                   404: {"model": ApiErrorResponse},
                                   409: {"model": ApiErrorResponse},
                                   429: {"model": ApiErrorResponse}})
async def follow_publisher(
    request: Request, slug: str,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "publisher:read")
    await _rate_limited(request, "follow", 60, 3600)
    pub = await _get_publisher_by_slug(db, slug)
    dup = (await db.execute(select(PublisherFollower).where(
        PublisherFollower.publisher_id == pub.id,
        PublisherFollower.user_id == auth_context.user_id))).scalar_one_or_none()
    if dup is not None:
        raise HTTPException(status_code=409, detail={
            "error": "Already following", "code": "ALREADY_FOLLOWING"})
    db.add(PublisherFollower(
        publisher_id=pub.id, user_id=auth_context.user_id,
        organization_id=auth_context.organization_id))
    await db.commit()
    return {"following": True, "publisher_id": str(pub.id)}


@publishers_router.delete("/{slug}/follow",
                          responses={401: {"model": ApiErrorResponse},
                                     403: {"model": ApiErrorResponse},
                                     404: {"model": ApiErrorResponse}})
async def unfollow_publisher(
    request: Request, slug: str,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "publisher:read")
    pub = await _get_publisher_by_slug(db, slug)
    row = (await db.execute(select(PublisherFollower).where(
        PublisherFollower.publisher_id == pub.id,
        PublisherFollower.user_id == auth_context.user_id))).scalar_one_or_none()
    if row is None:
        raise _not_found("Follow")
    await db.delete(row)
    await db.commit()
    return {"following": False}


@publishers_router.get("/{slug}/analytics",
                       responses={401: {"model": ApiErrorResponse},
                                  403: {"model": ApiErrorResponse},
                                  404: {"model": ApiErrorResponse}})
async def publisher_analytics(
    request: Request, slug: str, days: int = Query(30, ge=1, le=365),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Aggregated publisher analytics (no individual user activity exposed)."""
    await _need(request, db, "publisher:read")
    pub = await _get_publisher_by_slug(db, slug)
    member_ids = await _publisher_member_ids(db, pub.id)
    if (str(auth_context.user_id) not in member_ids
            and "marketplace:manage" not in (auth_context.permissions or set())
            and not auth_context.is_platform_owner):
        raise HTTPException(status_code=403, detail={
            "error": "Publisher or moderator access required", "code": "FORBIDDEN"})
    listings = list((await db.execute(select(MarketplaceListing).where(
        MarketplaceListing.publisher_id == pub.id,
        MarketplaceListing.deleted_at.is_(None)))).scalars().all())
    listing_ids = [r.id for r in listings]
    daily = []
    if listing_ids:
        daily = list((await db.execute(select(MarketplaceAnalyticsDaily).where(
            MarketplaceAnalyticsDaily.listing_id.in_(listing_ids))
            .order_by(MarketplaceAnalyticsDaily.day.desc())
            .limit(days * max(1, len(listing_ids))))).scalars().all())
    totals = {k: 0 for k in ("views", "clicks", "installs_started", "installs_completed",
                             "installs_failed", "updates", "uninstalls", "favorites",
                             "shares", "reviews")}
    by_day: dict[str, dict] = {}
    for row in daily:
        point = by_day.setdefault(row.day.isoformat(), dict(totals))
        for key in totals:
            value = getattr(row, key) or 0
            totals[key] += value
            point[key] += value
    per_listing = [{
        "listing_id": str(r.id), "slug": r.slug, "title": r.title,
        "status": r.status.value, "install_count": r.install_count,
        "successful_install_count": r.successful_install_count,
        "active_install_count": r.active_install_count,
        "favorite_count": r.favorite_count, "view_count": r.view_count,
        "rating_average": r.rating_average, "rating_count": r.rating_count,
    } for r in listings]
    return {"totals": totals, "series": [
        {"day": day, **values} for day, values in sorted(by_day.items())],
        "per_listing": per_listing}


@publishers_router.get("/{slug}/reviews",
                       responses={401: {"model": ApiErrorResponse},
                                  403: {"model": ApiErrorResponse},
                                  404: {"model": ApiErrorResponse}})
async def publisher_reviews(
    request: Request, slug: str,
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "review:read")
    pub = await _get_publisher_by_slug(db, slug)
    member_ids = await _publisher_member_ids(db, pub.id)
    if (str(auth_context.user_id) not in member_ids
            and "review:manage" not in (auth_context.permissions or set())
            and not auth_context.is_platform_owner):
        raise HTTPException(status_code=403, detail={
            "error": "Publisher or moderator access required", "code": "FORBIDDEN"})
    listing_ids = [r[0] for r in (await db.execute(select(MarketplaceListing.id).where(
        MarketplaceListing.publisher_id == pub.id))).all()]
    if not listing_ids:
        return {"data": [], "meta": create_pagination_meta(page, page_size, 0).model_dump()}
    total = (await db.execute(select(func.count(ListingReview.id)).where(
        ListingReview.listing_id.in_(listing_ids)))).scalar_one()
    rows = list((await db.execute(select(ListingReview).where(
        ListingReview.listing_id.in_(listing_ids))
        .order_by(ListingReview.created_at.desc())
        .limit(page_size).offset((page - 1) * page_size))).scalars().all())
    return {"data": [_review_out(r) for r in rows],
            "meta": create_pagination_meta(page, page_size, total).model_dump()}


# ---------------------------------------------------------------------------
# Reviews
# ---------------------------------------------------------------------------

def _review_out(review: ListingReview, *, response: Optional[dict] = None) -> dict:
    return {
        "id": str(review.id), "listing_id": str(review.listing_id),
        "version_id": str(review.version_id),
        "installation_id": (str(review.installation_id)
                            if review.installation_id else None),
        "reviewer_user_id": str(review.reviewer_user_id),
        "organization_id": str(review.organization_id),
        "rating": review.rating, "title": review.title, "body": review.body,
        "usage_context": review.usage_context, "status": review.status.value,
        "status_reason": review.status_reason, "verified_use": review.verified_use,
        "helpful_count": review.helpful_count,
        "response": response,
        "created_at": review.created_at.isoformat(),
        "updated_at": review.updated_at.isoformat(),
    }


class ReviewCreate(BaseModel):
    listing_id: UUID
    version_id: Optional[UUID] = None
    installation_id: Optional[UUID] = None
    rating: int = Field(ge=1, le=5)
    title: str = Field(default="", max_length=255)
    body: str = Field(min_length=1, max_length=20000)
    usage_context: str = Field(default="", max_length=500)


@reviews_router.get("",
                    responses={401: {"model": ApiErrorResponse},
                               403: {"model": ApiErrorResponse}})
async def list_reviews(
    request: Request, listing_id: UUID = Query(...),
    status_filter: str = Query("PUBLISHED"),
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "review:read")
    listing = await _get_listing(db, listing_id)
    await _listing_accessible(db, listing, auth_context.organization_id)
    try:
        wanted = ReviewStatus(status_filter.upper())
    except ValueError:
        raise HTTPException(status_code=400, detail={
            "error": "Unknown review status", "code": "BAD_STATUS"})
    stmt = select(ListingReview).where(ListingReview.listing_id == listing.id)
    # Non-published reviews are visible only to their author + moderators.
    if wanted == ReviewStatus.PUBLISHED:
        stmt = stmt.where(ListingReview.status == ReviewStatus.PUBLISHED)
    elif ("review:manage" not in (auth_context.permissions or set())
            and not auth_context.is_platform_owner):
        stmt = stmt.where(
            ListingReview.status == wanted,
            ListingReview.reviewer_user_id == auth_context.user_id)
    else:
        stmt = stmt.where(ListingReview.status == wanted)
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = list((await db.execute(stmt.order_by(ListingReview.created_at.desc())
                  .limit(page_size).offset((page - 1) * page_size))).scalars().all())
    responses = {}
    if rows:
        resp_rows = list((await db.execute(select(ReviewResponse).where(
            ReviewResponse.review_id.in_([r.id for r in rows])))).scalars().all())
        responses = {r.review_id: {"body": r.body,
                                   "created_at": r.created_at.isoformat()} for r in resp_rows}
    return {"data": [_review_out(r, response=responses.get(r.id)) for r in rows],
            "meta": create_pagination_meta(page, page_size, total).model_dump(),
            "summary": {"rating_average": listing.rating_average,
                        "rating_count": listing.rating_count,
                        "rating_distribution": listing.rating_distribution,
                        "verified_review_count": listing.verified_review_count}}


async def _recompute_rating(db: AsyncSession, listing_id: UUID) -> None:
    """Recompute aggregates from valid reviews only (publisher-immutable)."""
    rows = list((await db.execute(select(ListingReview.rating,
                                         ListingReview.verified_use).where(
        ListingReview.listing_id == listing_id,
        ListingReview.status == ReviewStatus.PUBLISHED))).all())
    agg = ratings_module.aggregate(
        [r[0] for r in rows], [bool(r[1]) for r in rows])
    listing = await db.get(MarketplaceListing, listing_id)
    if listing is not None:
        listing.rating_average = agg["rating_average"]
        listing.rating_count = agg["rating_count"]
        listing.rating_distribution = agg["rating_distribution"]
        listing.verified_review_count = agg["verified_review_count"]
        await db.flush()


@reviews_router.post("", status_code=status.HTTP_201_CREATED,
                     responses={400: {"model": ApiErrorResponse},
                                401: {"model": ApiErrorResponse},
                                403: {"model": ApiErrorResponse},
                                404: {"model": ApiErrorResponse},
                                409: {"model": ApiErrorResponse},
                                422: {"model": ApiErrorResponse},
                                429: {"model": ApiErrorResponse}})
async def create_review(
    request: Request, data: ReviewCreate,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "review:create")
    await _rate_limited(request, "review-create", 10, 3600)
    from openagent.packages import telemetry as ptelemetry

    organization_id = auth_context.organization_id
    listing = await _get_listing(db, data.listing_id)
    await _listing_accessible(db, listing, organization_id)
    if listing.status != ListingStatus.PUBLISHED:
        raise HTTPException(status_code=409, detail={
            "error": "Only published listings can be reviewed", "code": "NOT_PUBLISHED"})
    try:
        clean_title, clean_body = sanitize_module.validate_review_text(
            data.title, data.body)
    except sanitize_module.ContentError as exc:
        raise HTTPException(status_code=400, detail={
            "error": str(exc), "code": "BAD_CONTENT"})
    # Resolve the exact version installed/used (reviews always pin a version).
    version_id = data.version_id
    installation = None
    if data.installation_id:
        installation = await db.get(PackageInstallation, data.installation_id)
        if (installation is None
                or installation.organization_id != organization_id
                or installation.package_id != listing.package_id):
            raise HTTPException(status_code=422, detail={
                "error": "Installation does not belong to this listing/org",
                "code": "BAD_INSTALLATION"})
        version_id = installation.version_id
    if version_id is None:
        if listing.published_version_id:
            version_id = listing.published_version_id
        else:
            raise HTTPException(status_code=422, detail={
                "error": "installation_id or published version required",
                "code": "NO_VERSION"})
    version = await db.get(PackageVersion, version_id)
    if version is None or version.package_id != listing.package_id:
        raise HTTPException(status_code=422, detail={
            "error": "Version does not belong to this listing", "code": "BAD_VERSION"})
    eligible, verified_use, _reason = reviews_module.check_eligibility(
        has_installation=installation is not None,
        documented_usage=len(data.usage_context or "") >= 20)
    if not eligible:
        raise HTTPException(status_code=422, detail={
            "error": "Review requires an installation or documented usage "
                     "(usage_context >= 20 chars)", "code": "NOT_ELIGIBLE"})
    member_ids = await _publisher_member_ids(db, listing.publisher_id)
    self_review = reviews_module.check_self_review(
        reviewer_user_id=str(auth_context.user_id), publisher_member_ids=member_ids)
    since = reviews_module.velocity_window_start()
    recent = (await db.execute(select(func.count(ListingReview.id)).where(
        ListingReview.reviewer_user_id == auth_context.user_id,
        ListingReview.created_at >= since))).scalar_one()
    velocity_exceeded, _ = reviews_module.check_velocity(recent_count=recent)
    spam = reviews_module.check_spam_signals(title=clean_title, body=clean_body)
    status_value, status_reason = reviews_module.decide_initial_status(
        eligible=eligible, self_review=self_review,
        velocity_exceeded=velocity_exceeded, spam_signals=spam)
    review = ListingReview(
        listing_id=listing.id, version_id=version.id,
        installation_id=installation.id if installation else None,
        reviewer_user_id=auth_context.user_id, organization_id=organization_id,
        rating=data.rating, title=clean_title, body=clean_body,
        usage_context=(data.usage_context or "")[:500],
        status=ReviewStatus(status_value), status_reason=status_reason,
        verified_use=verified_use)
    db.add(review)
    try:
        await db.flush()
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=409, detail={
            "error": "You already reviewed this version", "code": "DUPLICATE_REVIEW"})
    if review.status == ReviewStatus.PUBLISHED:
        await _recompute_rating(db, listing.id)
    await _record_event(db, listing=listing, event_type="REVIEW",
                        organization_id=organization_id, user_id=auth_context.user_id,
                        metadata={"version": version.version, "rating": data.rating})
    mtelemetry.inc("marketplace_review_total")
    await ptelemetry.audit(db, organization_id=organization_id,
                           actor_user_id=auth_context.user_id,
                           action="marketplace.review.create", resource_id=review.id,
                           metadata={"listing_id": str(listing.id),
                                     "rating": data.rating,
                                     "verified_use": verified_use})
    await ptelemetry.emit(db, event_type="REVIEW_CREATED", aggregate_id=listing.id,
                          organization_id=organization_id, user_id=auth_context.user_id,
                          payload={"review_id": str(review.id), "rating": data.rating})
    # Notify publisher members (not the reviewer).
    await _notify(db, user_ids=[m for m in member_ids if m != str(auth_context.user_id)],
                  notif_type="REVIEW_RECEIVED",
                  title=f"New review for '{listing.title}' ({data.rating}/5)",
                  body=clean_title[:200], organization_id=organization_id,
                  listing_id=listing.id, publisher_id=listing.publisher_id)
    await db.commit()
    await db.refresh(review)
    return _review_out(review)


class ReviewUpdate(BaseModel):
    rating: Optional[int] = Field(default=None, ge=1, le=5)
    title: Optional[str] = Field(default=None, max_length=255)
    body: Optional[str] = Field(default=None, min_length=1, max_length=20000)


@reviews_router.patch("/{review_id}",
                      responses={400: {"model": ApiErrorResponse},
                                 401: {"model": ApiErrorResponse},
                                 403: {"model": ApiErrorResponse},
                                 404: {"model": ApiErrorResponse}})
async def update_review(
    request: Request, review_id: UUID, data: ReviewUpdate,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "review:update")
    review = await db.get(ListingReview, review_id)
    if review is None:
        raise _not_found("Review")
    if review.reviewer_user_id != auth_context.user_id:
        raise HTTPException(status_code=403, detail={
            "error": "Only the author can edit a review", "code": "FORBIDDEN"})
    if review.status not in (ReviewStatus.PUBLISHED, ReviewStatus.PENDING):
        raise HTTPException(status_code=409, detail={
            "error": f"Review in {review.status.value} cannot be edited",
            "code": "BAD_STATE"})
    if data.rating is not None:
        review.rating = data.rating
    if data.title is not None:
        review.title = sanitize_module.strip_html(data.title)[:255]
    if data.body is not None:
        try:
            _, clean_body = sanitize_module.validate_review_text("", data.body)
        except sanitize_module.ContentError as exc:
            raise HTTPException(status_code=400, detail={
                "error": str(exc), "code": "BAD_CONTENT"})
        review.body = clean_body
    await db.commit()
    if review.status == ReviewStatus.PUBLISHED:
        await _recompute_rating(db, review.listing_id)
        await db.commit()
    await db.refresh(review)
    return _review_out(review)


@reviews_router.delete("/{review_id}", status_code=status.HTTP_204_NO_CONTENT,
                       responses={401: {"model": ApiErrorResponse},
                                  403: {"model": ApiErrorResponse},
                                  404: {"model": ApiErrorResponse}})
async def delete_review(
    request: Request, review_id: UUID,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "review:update")
    review = await db.get(ListingReview, review_id)
    if review is None:
        raise _not_found("Review")
    if review.reviewer_user_id != auth_context.user_id:
        try:
            await _need(request, db, "review:manage")
        except HTTPException:
            if not auth_context.is_platform_owner:
                raise HTTPException(status_code=403, detail={
                    "error": "Not your review", "code": "FORBIDDEN"})
    await db.delete(review)
    await db.commit()
    await _recompute_rating(db, review.listing_id)
    await db.commit()


class ReviewRespond(BaseModel):
    body: str = Field(min_length=1, max_length=5000)


@reviews_router.post("/{review_id}/respond",
                     responses={400: {"model": ApiErrorResponse},
                                401: {"model": ApiErrorResponse},
                                403: {"model": ApiErrorResponse},
                                404: {"model": ApiErrorResponse},
                                409: {"model": ApiErrorResponse},
                                429: {"model": ApiErrorResponse}})
async def respond_review(
    request: Request, review_id: UUID, data: ReviewRespond,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "review:update")
    await _rate_limited(request, "review-respond", 20, 3600)
    from openagent.packages import telemetry as ptelemetry

    review = await db.get(ListingReview, review_id)
    if review is None:
        raise _not_found("Review")
    listing = await _get_listing(db, review.listing_id)
    await _require_publisher_member(db, listing.publisher_id, auth_context.user_id)
    existing = (await db.execute(select(ReviewResponse).where(
        ReviewResponse.review_id == review.id))).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail={
            "error": "A response already exists", "code": "ALREADY_RESPONDED"})
    try:
        _, clean_body = sanitize_module.validate_review_text("", data.body)
    except sanitize_module.ContentError as exc:
        raise HTTPException(status_code=400, detail={
            "error": str(exc), "code": "BAD_CONTENT"})
    row = ReviewResponse(review_id=review.id, responder_user_id=auth_context.user_id,
                         publisher_id=listing.publisher_id, body=clean_body)
    db.add(row)
    await db.commit()
    await ptelemetry.audit(db, organization_id=auth_context.organization_id,
                           actor_user_id=auth_context.user_id,
                           action="marketplace.review.respond", resource_id=review.id)
    await _notify(db, user_ids=[str(review.reviewer_user_id)],
                  notif_type="REVIEW_RESPONSE",
                  title=f"Publisher responded to your review of '{listing.title}'",
                  body=clean_body[:300],
                  organization_id=review.organization_id,
                  listing_id=listing.id, publisher_id=listing.publisher_id)
    await db.commit()
    return {"review_id": str(review.id), "body": clean_body}


class ReviewReportInput(BaseModel):
    reason: str
    details: str = Field(default="", max_length=2000)


@reviews_router.post("/{review_id}/report", status_code=status.HTTP_201_CREATED,
                     responses={400: {"model": ApiErrorResponse},
                                401: {"model": ApiErrorResponse},
                                403: {"model": ApiErrorResponse},
                                404: {"model": ApiErrorResponse},
                                429: {"model": ApiErrorResponse}})
async def report_review(
    request: Request, review_id: UUID, data: ReviewReportInput,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "review:read")
    await _rate_limited(request, "review-report", 20, 3600)
    from openagent.packages import telemetry as ptelemetry

    review = await db.get(ListingReview, review_id)
    if review is None:
        raise _not_found("Review")
    try:
        reason = ReportReason(data.reason.upper())
    except ValueError:
        raise HTTPException(status_code=400, detail={
            "error": "Unknown report reason", "code": "BAD_REASON"})
    listing = await _get_listing(db, review.listing_id)
    await _listing_accessible(db, listing, auth_context.organization_id)
    db.add(ReviewReport(
        review_id=review.id, reporter_user_id=auth_context.user_id,
        reason=reason, details=sanitize_module.strip_html(data.details)[:2000]))
    open_reports = (await db.execute(select(func.count(ReviewReport.id)).where(
        ReviewReport.review_id == review.id,
        ReviewReport.status.in_([ReportState.OPEN, ReportState.INVESTIGATING])))).scalar_one()
    if open_reports + 1 >= 3 and review.status == ReviewStatus.PUBLISHED:
        review.status = ReviewStatus.FLAGGED
        review.status_reason = f"auto-flagged after {open_reports + 1} reports"
        await _recompute_rating(db, review.listing_id)
    await _record_event(db, listing=listing, event_type="REPORT",
                        organization_id=auth_context.organization_id,
                        user_id=auth_context.user_id,
                        metadata={"review_id": str(review.id), "reason": reason.value})
    mtelemetry.inc("marketplace_review_reported_total")
    await ptelemetry.emit(db, event_type="REVIEW_REPORTED", aggregate_id=listing.id,
                          organization_id=auth_context.organization_id,
                          user_id=auth_context.user_id,
                          payload={"review_id": str(review.id)})
    await db.commit()
    return {"reported": True, "review_status": review.status.value}


class ReviewModerate(BaseModel):
    action: str = Field(pattern="^(HIDE|REMOVE|RESTORE)$")
    reason: str = Field(min_length=1, max_length=2000)


@reviews_router.post("/{review_id}/moderate",
                     responses={401: {"model": ApiErrorResponse},
                                403: {"model": ApiErrorResponse},
                                404: {"model": ApiErrorResponse}})
async def moderate_review(
    request: Request, review_id: UUID, data: ReviewModerate,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Moderate a review. HIDE/REMOVE require a recorded reason (never silent)."""
    from openagent.packages import telemetry as ptelemetry

    try:
        await _need(request, db, "review:manage")
    except HTTPException:
        if not auth_context.is_platform_owner:
            raise HTTPException(status_code=403, detail={
                "error": "Review moderation permission required", "code": "FORBIDDEN"})
    review = await db.get(ListingReview, review_id)
    if review is None:
        raise _not_found("Review")
    listing = await _get_listing(db, review.listing_id)
    mapping = {"HIDE": (ReviewStatus.HIDDEN, ModerationAction.HIDE_REVIEW),
               "REMOVE": (ReviewStatus.REMOVED, ModerationAction.REMOVE_REVIEW),
               "RESTORE": (ReviewStatus.PUBLISHED, ModerationAction.RESTORE)}
    target, mod_action = mapping[data.action]
    review.status = target
    review.status_reason = data.reason[:1000]
    db.add(ModerationActionRecord(
        target_type="review", target_id=review.id, action=mod_action,
        reason=data.reason[:2000], moderator_user_id=auth_context.user_id))
    await _recompute_rating(db, review.listing_id)
    await ptelemetry.audit(db, organization_id=auth_context.organization_id,
                           actor_user_id=auth_context.user_id,
                           action=f"marketplace.review.{data.action.lower()}",
                           resource_id=review.id,
                           metadata={"reason": data.reason[:500]})
    await _notify(db, user_ids=[str(review.reviewer_user_id)],
                  notif_type="MODERATION_DECISION",
                  title=f"Moderation decision on your review: {data.action}",
                  body=data.reason[:500], organization_id=review.organization_id,
                  listing_id=listing.id)
    await db.commit()
    return _review_out(review)


# ---------------------------------------------------------------------------
# Favorites
# ---------------------------------------------------------------------------

@favorites_router.get("",
                      responses={401: {"model": ApiErrorResponse},
                                 403: {"model": ApiErrorResponse}})
async def list_favorites(
    request: Request,
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "marketplace:read")
    stmt = (select(ListingFavorite, MarketplaceListing)
            .join(MarketplaceListing,
                  MarketplaceListing.id == ListingFavorite.listing_id)
            .where(ListingFavorite.user_id == auth_context.user_id,
                   MarketplaceListing.deleted_at.is_(None)))
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = list((await db.execute(stmt.order_by(ListingFavorite.created_at.desc())
                  .limit(page_size).offset((page - 1) * page_size))).all())
    pubs = await _publisher_lookup(db, {r[1].publisher_id for r in rows})
    return {"data": [
        _listing_out(
            listing,
            publisher_slug=pubs.get(listing.publisher_id, {}).get("slug", ""),
            publisher_name=pubs.get(listing.publisher_id, {}).get("display_name", ""),
            favorite=True)
        for _, listing in rows],
        "meta": create_pagination_meta(page, page_size, total).model_dump()}


class FavoriteAdd(BaseModel):
    listing_id: UUID


@favorites_router.post("", status_code=status.HTTP_201_CREATED,
                       responses={401: {"model": ApiErrorResponse},
                                  403: {"model": ApiErrorResponse},
                                  404: {"model": ApiErrorResponse},
                                  409: {"model": ApiErrorResponse},
                                  429: {"model": ApiErrorResponse}})
async def add_favorite(
    request: Request, data: FavoriteAdd,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "marketplace:read")
    await _rate_limited(request, "favorite", 60, 3600)
    listing = await _get_listing(db, data.listing_id)
    await _listing_accessible(db, listing, auth_context.organization_id)
    dup = (await db.execute(select(ListingFavorite).where(
        ListingFavorite.listing_id == listing.id,
        ListingFavorite.user_id == auth_context.user_id))).scalar_one_or_none()
    if dup is not None:
        raise HTTPException(status_code=409, detail={
            "error": "Already favorited", "code": "ALREADY_FAVORITED"})
    db.add(ListingFavorite(
        listing_id=listing.id, user_id=auth_context.user_id,
        organization_id=auth_context.organization_id))
    listing.favorite_count = (listing.favorite_count or 0) + 1
    await _record_event(db, listing=listing, event_type="FAVORITE",
                        organization_id=auth_context.organization_id,
                        user_id=auth_context.user_id)
    mtelemetry.inc("marketplace_favorite_total")
    await db.commit()
    return {"favorited": True, "listing_id": str(listing.id)}


@favorites_router.delete("/{listing_id}",
                         responses={401: {"model": ApiErrorResponse},
                                    403: {"model": ApiErrorResponse},
                                    404: {"model": ApiErrorResponse}})
async def remove_favorite(
    request: Request, listing_id: UUID,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "marketplace:read")
    row = (await db.execute(select(ListingFavorite).where(
        ListingFavorite.listing_id == listing_id,
        ListingFavorite.user_id == auth_context.user_id))).scalar_one_or_none()
    if row is None:
        raise _not_found("Favorite")
    listing = await _get_listing(db, listing_id)
    await db.delete(row)
    listing.favorite_count = max(0, (listing.favorite_count or 1) - 1)
    await db.commit()
    return {"favorited": False}


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

@notifications_router.get("",
                          responses={401: {"model": ApiErrorResponse},
                                     403: {"model": ApiErrorResponse}})
async def list_notifications(
    request: Request, organization_id: UUID,
    unread_only: bool = Query(False),
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "marketplace:read")
    stmt = select(MarketplaceNotification).where(
        MarketplaceNotification.user_id == auth_context.user_id)
    if unread_only:
        stmt = stmt.where(MarketplaceNotification.read.is_(False))
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = list((await db.execute(stmt.order_by(MarketplaceNotification.created_at.desc())
                  .limit(page_size).offset((page - 1) * page_size))).scalars().all())
    unread = (await db.execute(select(func.count(MarketplaceNotification.id)).where(
        MarketplaceNotification.user_id == auth_context.user_id,
        MarketplaceNotification.read.is_(False)))).scalar_one()
    return {"data": [{
        "id": str(n.id), "type": n.type.value, "title": n.title, "body": n.body,
        "listing_id": str(n.listing_id) if n.listing_id else None,
        "publisher_id": str(n.publisher_id) if n.publisher_id else None,
        "read": n.read, "created_at": n.created_at.isoformat()} for n in rows],
        "meta": create_pagination_meta(page, page_size, total).model_dump(),
        "unread_count": unread}


@notifications_router.post("/{notification_id}/read",
                           responses={401: {"model": ApiErrorResponse},
                                      403: {"model": ApiErrorResponse},
                                      404: {"model": ApiErrorResponse}})
async def read_notification(
    request: Request, organization_id: UUID, notification_id: UUID,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "marketplace:read")
    row = await db.get(MarketplaceNotification, notification_id)
    if row is None or row.user_id != auth_context.user_id:
        raise _not_found("Notification")
    row.read = True
    await db.commit()
    return {"id": str(row.id), "read": True}


@notifications_router.get("/prefs",
                          responses={401: {"model": ApiErrorResponse},
                                     403: {"model": ApiErrorResponse}})
async def get_notification_prefs(
    request: Request, organization_id: UUID,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "marketplace:read")
    pref = (await db.execute(select(MarketplaceNotificationPref).where(
        MarketplaceNotificationPref.user_id == auth_context.user_id,
        MarketplaceNotificationPref.organization_id == organization_id)
    )).scalar_one_or_none()
    return {"prefs": notif_module.prefs_for(dict(pref.prefs) if pref else None)}


class PrefsUpdate(BaseModel):
    prefs: dict[str, bool]


@notifications_router.put("/prefs",
                          responses={401: {"model": ApiErrorResponse},
                                     403: {"model": ApiErrorResponse}})
async def put_notification_prefs(
    request: Request, organization_id: UUID, data: PrefsUpdate,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "marketplace:read")
    merged = notif_module.prefs_for(None)
    for key, value in data.prefs.items():
        if key in merged and isinstance(value, bool):
            merged[key] = value
    pref = (await db.execute(select(MarketplaceNotificationPref).where(
        MarketplaceNotificationPref.user_id == auth_context.user_id,
        MarketplaceNotificationPref.organization_id == organization_id)
    )).scalar_one_or_none()
    if pref is None:
        pref = MarketplaceNotificationPref(
            user_id=auth_context.user_id, organization_id=organization_id,
            prefs=merged)
        db.add(pref)
    else:
        pref.prefs = merged
    await db.commit()
    return {"prefs": merged}


# ---------------------------------------------------------------------------
# Security advisories
# ---------------------------------------------------------------------------

class AdvisoryCreate(BaseModel):
    package_id: Optional[UUID] = None
    listing_id: Optional[UUID] = None
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=10000)
    affected_versions: str = Field(default="", max_length=255)
    severity: str = Field(default="MEDIUM")
    recommended_action: str = Field(default="Update", max_length=2000)
    recommended_version: str = Field(default="", max_length=32)


def _advisory_out(advisory: SecurityAdvisory) -> dict:
    return {
        "id": str(advisory.id),
        "package_id": str(advisory.package_id) if advisory.package_id else None,
        "listing_id": str(advisory.listing_id) if advisory.listing_id else None,
        "title": advisory.title, "description": advisory.description,
        "affected_versions": advisory.affected_versions,
        "severity": advisory.severity.value, "status": advisory.status.value,
        "recommended_action": advisory.recommended_action,
        "recommended_version": advisory.recommended_version,
        "published_at": advisory.published_at.isoformat() if advisory.published_at else None,
        "created_at": advisory.created_at.isoformat(),
    }


@advisories_router.get("",
                       responses={401: {"model": ApiErrorResponse},
                                  403: {"model": ApiErrorResponse}})
async def list_advisories(
    request: Request, status: str = Query(""), severity: str = Query(""),
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "marketplace:read")
    stmt = select(SecurityAdvisory)
    count_stmt = select(func.count(SecurityAdvisory.id))
    if status:
        try:
            wanted = AdvisoryStatus(status.upper())
        except ValueError:
            raise HTTPException(status_code=400, detail={
                "error": "Unknown advisory status", "code": "BAD_STATUS"})
        stmt = stmt.where(SecurityAdvisory.status == wanted)
        count_stmt = count_stmt.where(SecurityAdvisory.status == wanted)
    if severity:
        try:
            wanted_sev = AdvisorySeverity(severity.upper())
        except ValueError:
            raise HTTPException(status_code=400, detail={
                "error": "Unknown severity", "code": "BAD_SEVERITY"})
        stmt = stmt.where(SecurityAdvisory.severity == wanted_sev)
        count_stmt = count_stmt.where(SecurityAdvisory.severity == wanted_sev)
    total = (await db.execute(count_stmt)).scalar_one()
    rows = list((await db.execute(stmt.order_by(SecurityAdvisory.created_at.desc())
                  .limit(page_size).offset((page - 1) * page_size))).scalars().all())
    return {"data": [_advisory_out(r) for r in rows],
            "meta": create_pagination_meta(page, page_size, total).model_dump()}


@advisories_router.post("", status_code=status.HTTP_201_CREATED,
                        responses={400: {"model": ApiErrorResponse},
                                   401: {"model": ApiErrorResponse},
                                   403: {"model": ApiErrorResponse},
                                   404: {"model": ApiErrorResponse}})
async def create_advisory(
    request: Request, data: AdvisoryCreate,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    from openagent.packages import telemetry as ptelemetry

    try:
        await _need(request, db, "marketplace:manage")
    except HTTPException:
        if not auth_context.is_platform_owner:
            raise HTTPException(status_code=403, detail={
                "error": "Advisory moderation permission required",
                "code": "FORBIDDEN"})
    try:
        severity = AdvisorySeverity(data.severity.upper())
    except ValueError:
        raise HTTPException(status_code=400, detail={
            "error": "Unknown severity", "code": "BAD_SEVERITY"})
    if data.affected_versions:
        from openagent.packages.versioning import validate_constraint

        try:
            validate_constraint(data.affected_versions)
        except Exception:
            raise HTTPException(status_code=400, detail={
                "error": "affected_versions must be a version constraint "
                         "like '< 2.1.0'", "code": "BAD_CONSTRAINT"})
    listing = None
    if data.listing_id:
        listing = await _get_listing(db, data.listing_id)
    package_id = data.package_id or (listing.package_id if listing else None)
    if package_id is None:
        raise HTTPException(status_code=400, detail={
            "error": "package_id or listing_id required", "code": "NO_PACKAGE"})
    row = SecurityAdvisory(
        package_id=package_id, listing_id=listing.id if listing else None,
        publisher_id=listing.publisher_id if listing else None,
        title=sanitize_module.strip_html(data.title)[:255],
        description=sanitize_module.validate_body(data.description or "",
                                                  field="description"),
        affected_versions=data.affected_versions, severity=severity,
        recommended_action=data.recommended_action[:2000],
        recommended_version=data.recommended_version,
        published_by=auth_context.user_id, published_at=_now())
    db.add(row)
    await db.commit()
    await db.refresh(row)
    mtelemetry.inc("marketplace_advisory_total")
    await ptelemetry.audit(db, organization_id=auth_context.organization_id,
                           actor_user_id=auth_context.user_id,
                           action="marketplace.advisory.create", resource_id=row.id,
                           metadata={"severity": severity.value})
    await ptelemetry.emit(db, event_type="SECURITY_ADVISORY_CREATED",
                          aggregate_id=row.id,
                          organization_id=auth_context.organization_id,
                          user_id=auth_context.user_id,
                          payload={"severity": severity.value,
                                   "affected": data.affected_versions})
    await db.commit()
    return _advisory_out(row)


@advisories_router.get("/{advisory_id}",
                       responses={401: {"model": ApiErrorResponse},
                                  403: {"model": ApiErrorResponse},
                                  404: {"model": ApiErrorResponse}})
async def get_advisory(
    request: Request, advisory_id: UUID,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "marketplace:read")
    row = await db.get(SecurityAdvisory, advisory_id)
    if row is None:
        raise _not_found("Advisory")
    return _advisory_out(row)


class AdvisoryStatusUpdate(BaseModel):
    status: str = Field(pattern="^(AFFECTED|RESOLVED|REVOKED)$")


@advisories_router.patch("/{advisory_id}",
                         responses={401: {"model": ApiErrorResponse},
                                    403: {"model": ApiErrorResponse},
                                    404: {"model": ApiErrorResponse}})
async def update_advisory(
    request: Request, advisory_id: UUID, data: AdvisoryStatusUpdate,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    try:
        await _need(request, db, "marketplace:manage")
    except HTTPException:
        if not auth_context.is_platform_owner:
            raise HTTPException(status_code=403, detail={
                "error": "Advisory moderation permission required",
                "code": "FORBIDDEN"})
    row = await db.get(SecurityAdvisory, advisory_id)
    if row is None:
        raise _not_found("Advisory")
    row.status = AdvisoryStatus(data.status)
    await db.commit()
    return _advisory_out(row)


@advisories_router.get("/{advisory_id}/affected",
                       responses={401: {"model": ApiErrorResponse},
                                  403: {"model": ApiErrorResponse},
                                  404: {"model": ApiErrorResponse}})
async def advisory_affected(
    request: Request, advisory_id: UUID,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """My org's installations whose version matches the affected spec."""
    from openagent.packages.versioning import satisfies

    await _need(request, db, "marketplace:read")
    organization_id = auth_context.organization_id
    row = await db.get(SecurityAdvisory, advisory_id)
    if row is None:
        raise _not_found("Advisory")
    installs: list = []
    if row.package_id:
        installs = list((await db.execute(select(PackageInstallation).where(
            PackageInstallation.organization_id == organization_id,
            PackageInstallation.package_id == row.package_id))).scalars().all())
    affected: list[dict[str, Any]] = []
    for inst in installs:
        ver = await db.get(PackageVersion, inst.version_id)
        if ver is None:
            continue
        matches = True
        if row.affected_versions:
            try:
                matches = satisfies(ver.version, row.affected_versions)
            except Exception:
                matches = False
        if matches:
            listing = None
            if row.listing_id:
                listing = await db.get(MarketplaceListing, row.listing_id)
            affected.append({
                "installation_id": str(inst.id),
                "version": ver.version, "status": inst.status.value,
                "listing_slug": listing.slug if listing else "",
                "recommended_version": row.recommended_version,
            })
    return {"data": affected, "advisory": _advisory_out(row)}


# ---------------------------------------------------------------------------
# Reports (package / publisher / review / security issue)
# ---------------------------------------------------------------------------

class ReportCreate(BaseModel):
    target_type: str = Field(pattern="^(package|publisher|review|listing)$")
    target_id: Optional[UUID] = None
    target_slug: str = Field(default="", max_length=255)
    reason: str
    details: str = Field(default="", max_length=5000)


@reports_router.post("", status_code=status.HTTP_201_CREATED,
                     responses={400: {"model": ApiErrorResponse},
                                401: {"model": ApiErrorResponse},
                                403: {"model": ApiErrorResponse},
                                429: {"model": ApiErrorResponse}})
async def create_report(
    request: Request, data: ReportCreate,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "marketplace:read")
    await _rate_limited(request, "report", 20, 3600)
    try:
        reason = ReportReason(data.reason.upper())
    except ValueError:
        raise HTTPException(status_code=400, detail={
            "error": "Unknown report reason", "code": "BAD_REASON"})
    row = MarketplaceReport(
        target_type=data.target_type, target_id=data.target_id,
        target_slug=data.target_slug[:255],
        reason=reason, details=sanitize_module.strip_html(data.details)[:5000],
        reporter_user_id=auth_context.user_id,
        reporter_organization_id=auth_context.organization_id)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {"id": str(row.id), "status": row.status.value}


@reports_router.get("",
                    responses={401: {"model": ApiErrorResponse},
                               403: {"model": ApiErrorResponse}})
async def list_reports(
    request: Request, status: str = Query(""),
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    try:
        await _need(request, db, "marketplace:manage")
    except HTTPException:
        if not auth_context.is_platform_owner:
            raise HTTPException(status_code=403, detail={
                "error": "Moderation permission required", "code": "FORBIDDEN"})
    stmt = select(MarketplaceReport)
    count_stmt = select(func.count(MarketplaceReport.id))
    if status:
        try:
            wanted = ReportState(status.upper())
        except ValueError:
            raise HTTPException(status_code=400, detail={
                "error": "Unknown report state", "code": "BAD_STATUS"})
        stmt = stmt.where(MarketplaceReport.status == wanted)
        count_stmt = count_stmt.where(MarketplaceReport.status == wanted)
    total = (await db.execute(count_stmt)).scalar_one()
    rows = list((await db.execute(stmt.order_by(MarketplaceReport.created_at.desc())
                  .limit(page_size).offset((page - 1) * page_size))).scalars().all())
    return {"data": [{
        "id": str(r.id), "target_type": r.target_type,
        "target_id": str(r.target_id) if r.target_id else None,
        "target_slug": r.target_slug, "reason": r.reason.value,
        "details": r.details, "status": r.status.value,
        "resolution": r.resolution, "created_at": r.created_at.isoformat(),
    } for r in rows],
        "meta": create_pagination_meta(page, page_size, total).model_dump()}


class ReportTriage(BaseModel):
    status: str = Field(pattern="^(INVESTIGATING|ACTION_REQUIRED|RESOLVED|DISMISSED)$")
    resolution: dict[str, Any] = Field(default_factory=dict)


@reports_router.post("/{report_id}/triage",
                     responses={400: {"model": ApiErrorResponse},
                                401: {"model": ApiErrorResponse},
                                403: {"model": ApiErrorResponse},
                                404: {"model": ApiErrorResponse}})
async def triage_report(
    request: Request, report_id: UUID, data: ReportTriage,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    from openagent.packages import telemetry as ptelemetry

    try:
        await _need(request, db, "marketplace:manage")
    except HTTPException:
        if not auth_context.is_platform_owner:
            raise HTTPException(status_code=403, detail={
                "error": "Moderation permission required", "code": "FORBIDDEN"})
    row = await db.get(MarketplaceReport, report_id)
    if row is None:
        raise _not_found("Report")
    row.status = ReportState(data.status)
    row.resolution = data.resolution
    await db.commit()
    await ptelemetry.audit(db, organization_id=auth_context.organization_id,
                           actor_user_id=auth_context.user_id,
                           action="marketplace.report.triage", resource_id=row.id,
                           metadata={"status": data.status})
    await db.commit()
    return {"id": str(row.id), "status": row.status.value}


# ---------------------------------------------------------------------------
# Distribution
# ---------------------------------------------------------------------------

@distribution_router.get("/artifacts",
                         responses={401: {"model": ApiErrorResponse},
                                    403: {"model": ApiErrorResponse}})
async def list_artifacts(
    request: Request, organization_id: UUID, version_id: UUID = Query(...),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "package:read")
    version = await db.get(PackageVersion, version_id)
    if version is None:
        raise _not_found("Package version")
    pkg = await db.get(ReusablePackage, version.package_id)
    if pkg and pkg.organization_id not in (None, organization_id):
        raise _not_found("Package version")
    rows = list((await db.execute(select(DistributionArtifact).where(
        DistributionArtifact.version_id == version.id)
        .order_by(DistributionArtifact.created_at.desc()))).scalars().all())
    return {"data": [{
        "id": str(a.id), "artifact_type": a.artifact_type.value,
        "storage_provider": a.storage_provider.value,
        "filename": a.filename, "size_bytes": a.size_bytes, "mime": a.mime,
        "sha256": a.sha256, "signature_status": a.signature_status,
        "status": a.status.value,
        "verified_at": a.verified_at.isoformat() if a.verified_at else None,
        "created_at": a.created_at.isoformat()} for a in rows]}


@distribution_router.post("/artifacts", status_code=status.HTTP_201_CREATED,
                          responses={400: {"model": ApiErrorResponse},
                                     401: {"model": ApiErrorResponse},
                                     403: {"model": ApiErrorResponse},
                                     404: {"model": ApiErrorResponse},
                                     409: {"model": ApiErrorResponse},
                                     413: {"model": ApiErrorResponse}})
async def upload_artifact(
    request: Request, organization_id: UUID,
    version_id: UUID = Query(...),
    artifact_type: str = Query("PACKAGE_ARCHIVE"),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Upload + verify a distribution artifact (multipart file field `file`).

    The artifact is stored PENDING, verified server-side (size, hash,
    archive safety, manifest match, signature), and only then marked
    VERIFIED. Nothing unverified is ever distributed.
    """
    await _need(request, db, "package:update")
    from openagent.marketplace.distribution import (
        LocalArtifactStorage,
        check_safe_member,
        content_key,
        sha256_bytes,
        verify_archive,
    )
    from openagent.packages import telemetry as ptelemetry

    try:
        atype = ArtifactType(artifact_type.upper())
    except ValueError:
        raise HTTPException(status_code=400, detail={
            "error": "Unknown artifact type", "code": "BAD_TYPE"})
    version = await db.get(PackageVersion, version_id)
    if version is None:
        raise _not_found("Package version")
    pkg = await db.get(ReusablePackage, version.package_id)
    if pkg is None or (pkg.organization_id not in (None, organization_id)
                       and not auth_context.is_platform_owner):
        raise _not_found("Package version")
    form = await request.form()
    upload = form.get("file")
    if upload is None or not hasattr(upload, "read"):
        raise HTTPException(status_code=400, detail={
            "error": "Multipart field 'file' required", "code": "NO_FILE"})
    data = await upload.read()  # type: ignore[union-attr]
    filename = str(getattr(upload, "filename", "") or "artifact")
    if check_safe_member(filename.split("/")[-1]):
        raise HTTPException(status_code=400, detail={
            "error": "Unsafe filename", "code": "BAD_FILENAME"})
    MAX_UPLOAD = 100 * 1024 * 1024
    if len(data) > MAX_UPLOAD:
        raise HTTPException(status_code=413, detail={
            "error": "Artifact exceeds 100MB", "code": "TOO_LARGE"})
    if len(data) == 0:
        raise HTTPException(status_code=400, detail={
            "error": "Empty artifact", "code": "EMPTY_FILE"})
    digest = sha256_bytes(data)
    key = content_key("artifacts", digest, filename)
    storage = LocalArtifactStorage()
    stored = await storage.put(key, data, mime="application/octet-stream")
    row = DistributionArtifact(
        version_id=version.id, artifact_type=atype,
        storage_provider=DistributionProvider.LOCAL, storage_key=key,
        filename=filename[:255], size_bytes=stored.size_bytes,
        mime="application/octet-stream", sha256=digest,
        status=ArtifactStatus.VERIFYING, created_by=auth_context.user_id)
    db.add(row)
    await db.flush()
    # Server-side verification before anything is distributable.
    problems: list[str] = []
    signature_status = "UNSIGNED"
    if atype == ArtifactType.PACKAGE_ARCHIVE:
        result = verify_archive(data, filename=filename)
        problems.extend(result["problems"])
        sig = (await db.execute(select(PackageSignature).where(
            PackageSignature.version_id == version.id))).scalar_one_or_none()
        if sig is not None and sig.signature:
            from openagent.packages import signing as signing_module

            manifest_ok = (signing_module.verify_content_hash(
                dict(version.manifest or {}), version.content_hash)
                if version.content_hash else True)
            if sig.verified and manifest_ok:
                signature_status = "VALID"
            else:
                signature_status = "INVALID"
                problems.append("package signature invalid")
    row.signature_status = signature_status
    if problems:
        row.status = ArtifactStatus.REJECTED
        row.artifact_metadata = {"problems": problems[:10]}
    else:
        row.status = ArtifactStatus.VERIFIED
        row.verified_at = _now()
        row.artifact_metadata = {"files_verified": True}
    await db.commit()
    await db.refresh(row)
    await ptelemetry.audit(db, organization_id=organization_id,
                           actor_user_id=auth_context.user_id,
                           action="marketplace.artifact.upload", resource_id=row.id,
                           metadata={"sha256": digest, "status": row.status.value})
    await db.commit()
    return {"id": str(row.id), "sha256": digest, "size_bytes": row.size_bytes,
            "status": row.status.value, "signature": signature_status,
            "problems": row.artifact_metadata.get("problems", [])}


@distribution_router.get("/artifacts/{artifact_id}/download",
                         responses={401: {"model": ApiErrorResponse},
                                    403: {"model": ApiErrorResponse},
                                    404: {"model": ApiErrorResponse},
                                    409: {"model": ApiErrorResponse}})
async def download_artifact(
    request: Request, organization_id: UUID, artifact_id: UUID,
    listing_id: Optional[UUID] = None,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    from fastapi.responses import Response

    from openagent.marketplace.distribution import (
        LocalArtifactStorage,
        sha256_bytes,
    )

    await _need(request, db, "package:read")
    row = await db.get(DistributionArtifact, artifact_id)
    if row is None:
        raise _not_found("Artifact")
    if row.status != ArtifactStatus.VERIFIED and row.status != ArtifactStatus.PUBLISHED:
        raise HTTPException(status_code=409, detail={
            "error": f"Artifact is {row.status.value}, not downloadable",
            "code": "NOT_VERIFIED"})
    stored = await LocalArtifactStorage().get(row.storage_key)
    if stored is None or sha256_bytes(stored) != row.sha256:
        raise HTTPException(status_code=409, detail={
            "error": "Artifact corrupted in storage", "code": "ARTIFACT_CORRUPT"})
    db.add(ArtifactDownload(
        artifact_id=row.id, organization_id=organization_id,
        user_id=auth_context.user_id, listing_id=listing_id,
        bytes_served=len(stored)))
    await db.commit()
    return Response(content=stored, media_type=row.mime,
                    headers={"Content-Disposition":
                             f"attachment; filename={row.filename!r}",
                             "X-Artifact-SHA256": row.sha256,
                             "X-Signature-Status": row.signature_status})


class ArtifactLocationAdd(BaseModel):
    provider: str
    url_or_ref: str = Field(min_length=1, max_length=1000)
    region: str = Field(default="", max_length=64)
    is_primary: bool = False


@distribution_router.post("/artifacts/{artifact_id}/locations",
                          status_code=status.HTTP_201_CREATED,
                          responses={400: {"model": ApiErrorResponse},
                                     401: {"model": ApiErrorResponse},
                                     403: {"model": ApiErrorResponse},
                                     404: {"model": ApiErrorResponse}})
async def add_artifact_location(
    request: Request, organization_id: UUID, artifact_id: UUID,
    data: ArtifactLocationAdd,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "marketplace:manage")
    row = await db.get(DistributionArtifact, artifact_id)
    if row is None:
        raise _not_found("Artifact")
    try:
        provider = DistributionProvider(data.provider.upper())
    except ValueError:
        raise HTTPException(status_code=400, detail={
            "error": "Unknown distribution provider", "code": "BAD_PROVIDER"})
    ref = data.url_or_ref.strip()
    if ref.lower().startswith(("javascript:", "data:", "file:")):
        raise HTTPException(status_code=400, detail={
            "error": "Unsafe location reference", "code": "BAD_URL"})
    if provider in (DistributionProvider.CDN, DistributionProvider.OBJECT_STORAGE,
                    DistributionProvider.GITHUB_RELEASE, DistributionProvider.REGISTRY):
        sanitize_module.check_url(ref, field="url_or_ref")
    if data.is_primary:
        from sqlalchemy import update as _update_loc

        await db.execute(_update_loc(DistributionLocation).where(
            DistributionLocation.artifact_id == row.id).values(is_primary=False))
    loc = DistributionLocation(artifact_id=row.id, provider=provider,
                               url_or_ref=ref[:1000], region=data.region,
                               is_primary=data.is_primary)
    db.add(loc)
    await db.commit()
    return {"id": str(loc.id), "provider": provider.value, "is_primary": data.is_primary}


# ---------------------------------------------------------------------------
# Commerce (interfaces; no real payment processing in this phase)
# ---------------------------------------------------------------------------

class ProductCreate(BaseModel):
    listing_id: UUID
    product_type: str = Field(default="SINGLE_LISTING")
    pricing_model: str = Field(default="FREE")
    currency: str = Field(default="USD", min_length=3, max_length=3)
    metadata: dict[str, Any] = Field(default_factory=dict)


def _product_out(product: Product, prices: list) -> dict:
    return {
        "id": str(product.id), "listing_id": str(product.listing_id),
        "product_type": product.product_type.value,
        "pricing_model": product.pricing_model.value,
        "currency": product.currency, "status": product.status.value,
        "metadata": product.product_metadata,
        "prices": [{
            "id": str(p.id), "amount_minor": p.amount_minor,
            "currency": p.currency, "interval": p.interval,
            "tiers": p.tiers, "status": p.status.value} for p in prices],
    }


async def _require_product_access(db: AsyncSession, product_id: UUID,
                                  user_id: UUID) -> tuple[Product, MarketplaceListing]:
    product = await db.get(Product, product_id)
    if product is None:
        raise _not_found("Product")
    listing = await _get_listing(db, product.listing_id)
    await _require_publisher_member(db, listing.publisher_id, user_id)
    return product, listing


@commerce_router.get("/products",
                     responses={401: {"model": ApiErrorResponse},
                                403: {"model": ApiErrorResponse}})
async def list_products(
    request: Request, organization_id: UUID, listing_id: Optional[UUID] = None,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "marketplace:read")
    stmt = select(Product)
    if listing_id:
        listing = await _get_listing(db, listing_id)
        await _listing_accessible(db, listing, organization_id)
        stmt = stmt.where(Product.listing_id == listing.id)
    else:
        # Only products on listings visible to this org.
        visible = select(MarketplaceListing.id)
        stmt = stmt.where(Product.listing_id.in_(visible))
    rows = list((await db.execute(stmt.order_by(Product.created_at.desc())
                  .limit(100))).scalars().all())
    prices = {}
    if rows:
        for row in (await db.execute(select(Price).where(
                Price.product_id.in_([r.id for r in rows])))).scalars().all():
            prices.setdefault(row.product_id, []).append(row)
    return {"data": [_product_out(r, prices.get(r.id, [])) for r in rows]}


@commerce_router.post("/products", status_code=status.HTTP_201_CREATED,
                      responses={400: {"model": ApiErrorResponse},
                                 401: {"model": ApiErrorResponse},
                                 403: {"model": ApiErrorResponse},
                                 404: {"model": ApiErrorResponse}})
async def create_product(
    request: Request, organization_id: UUID, data: ProductCreate,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "marketplace:update")
    from openagent.packages import telemetry as ptelemetry

    listing = await _get_listing(db, data.listing_id)
    await _listing_accessible(db, listing, organization_id)
    await _require_publisher_member(db, listing.publisher_id, auth_context.user_id,
                                    roles=("OWNER", "ADMIN"))
    try:
        ptype = ProductType(data.product_type.upper())
        pricing = PricingModel(data.pricing_model.upper())
    except ValueError:
        raise HTTPException(status_code=400, detail={
            "error": "Unknown product/pricing type", "code": "BAD_TYPE"})
    if pricing != PricingModel.FREE:
        # Paid products require the listing to agree; commerce itself stays
        # interface-only until MP24 (no provider configured).
        listing.pricing_model = pricing
    product = Product(
        listing_id=listing.id, product_type=ptype, pricing_model=pricing,
        currency=data.currency.upper(), status=ProductStatus.DRAFT,
        product_metadata=data.metadata, created_by=auth_context.user_id)
    db.add(product)
    await db.commit()
    await db.refresh(product)
    await ptelemetry.audit(db, organization_id=organization_id,
                           actor_user_id=auth_context.user_id,
                           action="marketplace.product.create", resource_id=product.id,
                           metadata={"pricing_model": pricing.value})
    await db.commit()
    return _product_out(product, [])


class PriceCreate(BaseModel):
    amount_minor: int = Field(ge=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    interval: str = Field(default="ONE_TIME")
    tiers: list[dict[str, Any]] = Field(default_factory=list)


@commerce_router.post("/products/{product_id}/prices",
                      status_code=status.HTTP_201_CREATED,
                      responses={400: {"model": ApiErrorResponse},
                                 401: {"model": ApiErrorResponse},
                                 403: {"model": ApiErrorResponse},
                                 404: {"model": ApiErrorResponse}})
async def create_price(
    request: Request, organization_id: UUID, product_id: UUID, data: PriceCreate,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Pricing changes are versioned rows + audited (never silent edits)."""
    await _need(request, db, "marketplace:update")
    from openagent.packages import telemetry as ptelemetry

    product, _listing = await _require_product_access(db, product_id,
                                                      auth_context.user_id)
    if data.interval.upper() not in ("ONE_TIME", "MONTH", "YEAR"):
        raise HTTPException(status_code=400, detail={
            "error": "Unknown price interval", "code": "BAD_INTERVAL"})
    price = Price(product_id=product.id, amount_minor=data.amount_minor,
                  currency=data.currency.upper(), interval=data.interval.upper(),
                  tiers=data.tiers, status=ProductStatus.DRAFT)
    db.add(price)
    await db.commit()
    await db.refresh(price)
    await ptelemetry.audit(db, organization_id=organization_id,
                           actor_user_id=auth_context.user_id,
                           action="marketplace.price.create", resource_id=price.id,
                           metadata={"amount_minor": data.amount_minor,
                                     "currency": price.currency})
    await db.commit()
    return {"id": str(price.id), "amount_minor": price.amount_minor,
            "currency": price.currency, "interval": price.interval,
            "status": price.status.value}


@commerce_router.post("/products/{product_id}/activate",
                      responses={401: {"model": ApiErrorResponse},
                                 403: {"model": ApiErrorResponse},
                                 404: {"model": ApiErrorResponse}})
async def activate_product(
    request: Request, organization_id: UUID, product_id: UUID,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "marketplace:update")
    product, _listing = await _require_product_access(db, product_id,
                                                      auth_context.user_id)
    product.status = ProductStatus.ACTIVE
    from sqlalchemy import update as _update_price

    await db.execute(_update_price(Price).where(
        Price.product_id == product.id).values(status=ProductStatus.ACTIVE))
    await db.commit()
    return {"id": str(product.id), "status": product.status.value}


class EntitlementGrant(BaseModel):
    product_id: UUID
    organization_id: Optional[UUID] = None
    user_id: Optional[UUID] = None
    valid_until: Optional[datetime] = None
    source: str = Field(default="manual", max_length=64)


@commerce_router.get("/entitlements",
                     responses={401: {"model": ApiErrorResponse},
                                403: {"model": ApiErrorResponse}})
async def list_entitlements(
    request: Request, organization_id: UUID,
    mine: bool = Query(True),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "marketplace:read")
    stmt = select(Entitlement)
    if mine:
        stmt = stmt.where(or_(
            Entitlement.organization_id == organization_id,
            Entitlement.user_id == auth_context.user_id))
    else:
        try:
            await _need(request, db, "marketplace:manage")
        except HTTPException:
            if not auth_context.is_platform_owner:
                raise HTTPException(status_code=403, detail={
                    "error": "Moderation permission required", "code": "FORBIDDEN"})
    rows = list((await db.execute(stmt.order_by(Entitlement.created_at.desc())
                  .limit(200))).scalars().all())
    return {"data": [{
        "id": str(e.id),
        "organization_id": str(e.organization_id) if e.organization_id else None,
        "user_id": str(e.user_id) if e.user_id else None,
        "product_id": str(e.product_id), "listing_id": str(e.listing_id),
        "status": e.status.value,
        "valid_from": e.valid_from.isoformat() if e.valid_from else None,
        "valid_until": e.valid_until.isoformat() if e.valid_until else None,
        "source": e.source} for e in rows]}


@commerce_router.post("/entitlements", status_code=status.HTTP_201_CREATED,
                      responses={400: {"model": ApiErrorResponse},
                                 401: {"model": ApiErrorResponse},
                                 403: {"model": ApiErrorResponse},
                                 404: {"model": ApiErrorResponse}})
async def grant_entitlement(
    request: Request, organization_id: UUID, data: EntitlementGrant,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Manual entitlement grant (publisher owner/admin or platform).

    Verified-provider grants arrive via webhooks in MP24; this path is
    explicit, permission-gated and audited.
    """
    await _need(request, db, "marketplace:update")
    from openagent.packages import telemetry as ptelemetry

    product = await db.get(Product, data.product_id)
    if product is None:
        raise _not_found("Product")
    listing = await _get_listing(db, product.listing_id)
    try:
        await _require_publisher_member(db, listing.publisher_id, auth_context.user_id,
                                        roles=("OWNER", "ADMIN"))
    except HTTPException:
        if not auth_context.is_platform_owner:
            raise
    target_org = data.organization_id or organization_id
    row = Entitlement(
        organization_id=target_org, user_id=data.user_id,
        product_id=product.id, listing_id=listing.id,
        status=EntitlementStatus.ACTIVE, valid_from=_now(),
        valid_until=data.valid_until, source=data.source[:64])
    db.add(row)
    await db.commit()
    await ptelemetry.audit(db, organization_id=organization_id,
                           actor_user_id=auth_context.user_id,
                           action="marketplace.entitlement.grant", resource_id=row.id,
                           metadata={"product_id": str(product.id),
                                     "source": row.source})
    await db.commit()
    return {"id": str(row.id), "status": row.status.value,
            "source": row.source}


@commerce_router.post("/webhooks/{provider}",
                      responses={400: {"model": ApiErrorResponse},
                                 503: {"model": ApiErrorResponse},
                                 429: {"model": ApiErrorResponse}})
async def billing_webhook(
    request: Request, provider: str,
    db: AsyncSession = Depends(get_db),
):
    """Billing webhook intake. Unsigned/unknown-provider events are rejected;
    accepted events are persisted idempotently for MP24 providers to process.

    No auth context here by design (providers call us) — security comes
    from signature + timestamp + replay protection, never from trust.
    """
    from openagent.marketplace.billing import (
        verify_webhook_signature,
        verify_webhook_timestamp,
    )

    await _rate_limited(request, "billing-webhook", 60, 60)
    raw = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}
    # No billing provider is configured in this phase: reject honestly.
    configured = dict(getattr(request.app.state, "billing_providers", {}) or {})
    secret = configured.get(provider, {}).get("webhook_secret", "")
    if not secret:
        raise HTTPException(status_code=503, detail={
            "error": f"No billing provider {provider!r} configured; "
                     "commerce webhooks unavailable", "code": "NO_PROVIDER"})
    signature = (headers.get("x-signature") or headers.get("stripe-signature")
                 or headers.get("x-webhook-signature") or "")
    if not verify_webhook_signature(secret=secret, raw_body=raw, signature=signature):
        mtelemetry.inc("marketplace_webhook_rejected_total")
        raise HTTPException(status_code=400, detail={
            "error": "Invalid webhook signature", "code": "BAD_SIGNATURE"})
    timestamp = (headers.get("x-timestamp") or headers.get("stripe-timestamp") or "0")
    if not verify_webhook_timestamp(timestamp):
        mtelemetry.inc("marketplace_webhook_rejected_total")
        raise HTTPException(status_code=400, detail={
            "error": "Stale webhook timestamp (replay guard)", "code": "STALE_TIMESTAMP"})
    try:
        import json as _json

        payload = _json.loads(raw.decode() or "{}")
    except Exception:
        raise HTTPException(status_code=400, detail={
            "error": "Invalid JSON payload", "code": "BAD_PAYLOAD"})
    event_id = str(payload.get("id") or headers.get("x-event-id") or "")
    if not event_id:
        raise HTTPException(status_code=400, detail={
            "error": "Missing event id", "code": "NO_EVENT_ID"})
    idem = f"{provider}:{event_id}"
    existing = (await db.execute(select(BillingWebhookEvent).where(
        BillingWebhookEvent.idempotency_key == idem))).scalar_one_or_none()
    if existing is not None:
        return {"received": True, "duplicate": True, "processed": existing.processed}
    db.add(BillingWebhookEvent(
        provider=provider, event_id=event_id,
        event_type=str(payload.get("type", ""))[:128], payload=payload,
        signature_valid=True, processed=False, idempotency_key=idem))
    await db.commit()
    return {"received": True, "duplicate": False, "processed": False}


@commerce_router.get("/revenue",
                     responses={401: {"model": ApiErrorResponse},
                                403: {"model": ApiErrorResponse}})
async def publisher_revenue(
    request: Request, organization_id: UUID, publisher_id: UUID = Query(...),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Revenue records (real rows only; empty until verified billing events)."""
    await _need(request, db, "publisher:read")
    await _require_publisher_member(db, publisher_id, auth_context.user_id)
    rows = list((await db.execute(select(RevenueRecord).where(
        RevenueRecord.publisher_id == publisher_id)
        .order_by(RevenueRecord.created_at.desc()).limit(200))).scalars().all())
    totals = {"gross_minor": 0, "fee_minor": 0, "net_minor": 0, "count": len(rows)}
    for row in rows:
        totals["gross_minor"] += row.gross_minor
        totals["fee_minor"] += row.fee_minor
        totals["net_minor"] += row.net_minor
    return {"data": [{
        "id": str(r.id),
        "product_id": str(r.product_id) if r.product_id else None,
        "transaction_reference": r.transaction_reference,
        "gross_minor": r.gross_minor, "fee_minor": r.fee_minor,
        "net_minor": r.net_minor, "currency": r.currency,
        "status": r.status.value, "created_at": r.created_at.isoformat(),
    } for r in rows], "totals": totals,
        "note": "Revenue appears only from verified billing events; none are fabricated."}


@commerce_router.get("/payouts",
                     responses={401: {"model": ApiErrorResponse},
                                403: {"model": ApiErrorResponse}})
async def publisher_payouts(
    request: Request, organization_id: UUID, publisher_id: UUID = Query(...),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "publisher:read")
    await _require_publisher_member(db, publisher_id, auth_context.user_id)
    rows = list((await db.execute(select(Payout).where(
        Payout.publisher_id == publisher_id)
        .order_by(Payout.created_at.desc()).limit(200))).scalars().all())
    return {"data": [{
        "id": str(p.id), "amount_minor": p.amount_minor, "currency": p.currency,
        "status": p.status.value, "provider_reference": p.provider_reference,
        "created_at": p.created_at.isoformat()} for p in rows],
        "note": "Payouts require a configured billing provider (MP24)."}


# ---------------------------------------------------------------------------
# Publisher studio (my publishers: packages, listings, analytics, reviews, security)
# ---------------------------------------------------------------------------

@publisher_router.get("/profile",
                      responses={401: {"model": ApiErrorResponse},
                                 403: {"model": ApiErrorResponse}})
async def studio_profile(
    request: Request, organization_id: UUID,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "publisher:read")
    member_rows = list((await db.execute(select(PublisherMember).where(
        PublisherMember.user_id == auth_context.user_id))).scalars().all())
    pubs = []
    for membership in member_rows:
        pub = await db.get(PublisherProfile, membership.publisher_id)
        if pub is None:
            continue
        out = await _publisher_out(db, pub)
        out["my_role"] = membership.role
        pubs.append(out)
    return {"data": pubs}


@publisher_router.get("/listings",
                      responses={401: {"model": ApiErrorResponse},
                                 403: {"model": ApiErrorResponse}})
async def studio_listings(
    request: Request, organization_id: UUID,
    status: str = Query(""),
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "publisher:read")
    member_pub_ids = [r[0] for r in (await db.execute(
        select(PublisherMember.publisher_id).where(
            PublisherMember.user_id == auth_context.user_id))).all()]
    if not member_pub_ids:
        return {"data": [], "meta": create_pagination_meta(page, page_size, 0).model_dump()}
    stmt = select(MarketplaceListing).where(
        MarketplaceListing.publisher_id.in_(member_pub_ids),
        MarketplaceListing.deleted_at.is_(None))
    count_stmt = select(func.count(MarketplaceListing.id)).where(
        MarketplaceListing.publisher_id.in_(member_pub_ids),
        MarketplaceListing.deleted_at.is_(None))
    if status:
        try:
            wanted = ListingStatus(status.upper())
        except ValueError:
            raise HTTPException(status_code=400, detail={
                "error": "Unknown listing status", "code": "BAD_STATUS"})
        stmt = stmt.where(MarketplaceListing.status == wanted)
        count_stmt = count_stmt.where(MarketplaceListing.status == wanted)
    total = (await db.execute(count_stmt)).scalar_one()
    rows = list((await db.execute(stmt.order_by(MarketplaceListing.updated_at.desc())
                  .limit(page_size).offset((page - 1) * page_size))).scalars().all())
    pubs = await _publisher_lookup(db, {r.publisher_id for r in rows})
    return {"data": [
        {**_listing_out(
            r, publisher_slug=pubs.get(r.publisher_id, {}).get("slug", ""),
            publisher_name=pubs.get(r.publisher_id, {}).get("display_name", "")),
         "marketplace_slug": (await _get_marketplace(db, r.marketplace_id)).slug}
        for r in rows],
        "meta": create_pagination_meta(page, page_size, total).model_dump()}


@publisher_router.get("/packages",
                      responses={401: {"model": ApiErrorResponse},
                                 403: {"model": ApiErrorResponse}})
async def studio_packages(
    request: Request, organization_id: UUID,
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Packages backing my listings (links into the MP22 package system)."""
    await _need(request, db, "package:read")
    member_pub_ids = [r[0] for r in (await db.execute(
        select(PublisherMember.publisher_id).where(
            PublisherMember.user_id == auth_context.user_id))).all()]
    package_ids = [r[0] for r in (await db.execute(
        select(MarketplaceListing.package_id).where(
            MarketplaceListing.publisher_id.in_(member_pub_ids or []),
            MarketplaceListing.deleted_at.is_(None)))).all()]
    if not package_ids:
        return {"data": [], "meta": create_pagination_meta(page, page_size, 0).model_dump()}
    total = len(set(package_ids))
    pkgs = list((await db.execute(select(ReusablePackage).where(
        ReusablePackage.id.in_(list(set(package_ids)))))).scalars().all())
    return {"data": [{
        "id": str(p.id), "slug": p.slug, "name": p.name,
        "package_type": p.package_type.value, "visibility": p.visibility.value,
        "trust": p.trust.value, "official": p.official,
        "latest_version": p.latest_version} for p in pkgs],
        "meta": create_pagination_meta(page, page_size, total).model_dump()}


@publisher_router.get("/analytics",
                      responses={401: {"model": ApiErrorResponse},
                                 403: {"model": ApiErrorResponse}})
async def studio_analytics(
    request: Request, organization_id: UUID, days: int = Query(30, ge=1, le=365),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "publisher:read")
    member_pub_ids = [r[0] for r in (await db.execute(
        select(PublisherMember.publisher_id).where(
            PublisherMember.user_id == auth_context.user_id))).all()]
    listings = list((await db.execute(select(MarketplaceListing).where(
        MarketplaceListing.publisher_id.in_(member_pub_ids or []),
        MarketplaceListing.deleted_at.is_(None)))).scalars().all())
    listing_ids = [r.id for r in listings]
    daily = []
    if listing_ids:
        daily = list((await db.execute(select(MarketplaceAnalyticsDaily).where(
            MarketplaceAnalyticsDaily.listing_id.in_(listing_ids))
            .order_by(MarketplaceAnalyticsDaily.day.desc())
            .limit(days * max(1, len(listing_ids))))).scalars().all())
    totals = {k: 0 for k in ("views", "clicks", "installs_started", "installs_completed",
                             "installs_failed", "updates", "uninstalls", "favorites",
                             "shares", "reviews")}
    by_day: dict[str, dict] = {}
    for row in daily:
        point = by_day.setdefault(row.day.isoformat(), dict(totals))
        for key in totals:
            value = getattr(row, key) or 0
            totals[key] += value
            point[key] += value
    agg = {
        "install_count": sum(r.install_count or 0 for r in listings),
        "successful_install_count": sum(r.successful_install_count or 0 for r in listings),
        "active_install_count": sum(r.active_install_count or 0 for r in listings),
        "favorite_count": sum(r.favorite_count or 0 for r in listings),
        "view_count": sum(r.view_count or 0 for r in listings),
    }
    return {"totals": {**totals, **agg},
            "series": [{"day": day, **values} for day, values in sorted(by_day.items())],
            "listings": len(listings)}


@publisher_router.get("/reviews",
                      responses={401: {"model": ApiErrorResponse},
                                 403: {"model": ApiErrorResponse}})
async def studio_reviews(
    request: Request, organization_id: UUID,
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _need(request, db, "review:read")
    member_pub_ids = [r[0] for r in (await db.execute(
        select(PublisherMember.publisher_id).where(
            PublisherMember.user_id == auth_context.user_id))).all()]
    listing_ids = [r[0] for r in (await db.execute(select(MarketplaceListing.id).where(
        MarketplaceListing.publisher_id.in_(member_pub_ids or [])))).all()]
    if not listing_ids:
        return {"data": [], "meta": create_pagination_meta(page, page_size, 0).model_dump()}
    total = (await db.execute(select(func.count(ListingReview.id)).where(
        ListingReview.listing_id.in_(listing_ids)))).scalar_one()
    rows = list((await db.execute(select(ListingReview).where(
        ListingReview.listing_id.in_(listing_ids))
        .order_by(ListingReview.created_at.desc())
        .limit(page_size).offset((page - 1) * page_size))).scalars().all())
    return {"data": [_review_out(r) for r in rows],
            "meta": create_pagination_meta(page, page_size, total).model_dump()}


@publisher_router.get("/security",
                      responses={401: {"model": ApiErrorResponse},
                                 403: {"model": ApiErrorResponse}})
async def studio_security(
    request: Request, organization_id: UUID,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Security posture across my listings: advisories + latest scan state."""
    await _need(request, db, "publisher:read")
    member_pub_ids = [r[0] for r in (await db.execute(
        select(PublisherMember.publisher_id).where(
            PublisherMember.user_id == auth_context.user_id))).all()]
    listings = list((await db.execute(select(MarketplaceListing).where(
        MarketplaceListing.publisher_id.in_(member_pub_ids or []),
        MarketplaceListing.deleted_at.is_(None)))).scalars().all())
    listing_ids = [r.id for r in listings]
    advisories = []
    if listing_ids:
        advisories = list((await db.execute(select(SecurityAdvisory).where(
            SecurityAdvisory.listing_id.in_(listing_ids))
            .order_by(SecurityAdvisory.created_at.desc()).limit(100))).scalars().all())
    return {"data": [{
        "listing_id": str(r.id), "slug": r.slug, "title": r.title,
        "status": r.status.value, "security_status": r.security_status,
        "trust_level": r.trust_level,
        "published_version": r.published_version} for r in listings],
        "advisories": [_advisory_out(a) for a in advisories]}


# ---------------------------------------------------------------------------
# Master console (platform owners only; every action audited)
# ---------------------------------------------------------------------------

@moderation_router.get("/overview",
                       responses={401: {"model": ApiErrorResponse},
                                  403: {"model": ApiErrorResponse}})
async def master_overview(
    request: Request,
    platform_user = Depends(require_platform_owner()),
    db: AsyncSession = Depends(get_db),
):
    _ = request
    published = (await db.execute(select(func.count(MarketplaceListing.id)).where(
        MarketplaceListing.status == ListingStatus.PUBLISHED,
        MarketplaceListing.deleted_at.is_(None)))).scalar_one()
    pending = (await db.execute(select(func.count(MarketplaceListing.id)).where(
        MarketplaceListing.status.in_([ListingStatus.SUBMITTED,
                                       ListingStatus.VALIDATING,
                                       ListingStatus.UNDER_REVIEW]),
        MarketplaceListing.deleted_at.is_(None)))).scalar_one()
    alerts = (await db.execute(select(func.count(SecurityAdvisory.id)).where(
        SecurityAdvisory.status == AdvisoryStatus.AFFECTED))).scalar_one()
    revoked = (await db.execute(select(func.count(MarketplaceListing.id)).where(
        MarketplaceListing.status == ListingStatus.REVOKED))).scalar_one()
    publishers = (await db.execute(select(func.count(PublisherProfile.id)))).scalar_one()
    private_mkts = (await db.execute(select(func.count(Marketplace.id)).where(
        Marketplace.type != MarketplaceType.PUBLIC_MARKETPLACE,
        Marketplace.deleted_at.is_(None)))).scalar_one()
    events = (await db.execute(select(func.count(MarketplaceEvent.id)))).scalar_one()
    return {"published_listings": published, "pending_reviews": pending,
            "security_alerts": alerts, "revoked_packages": revoked,
            "publishers": publishers, "private_marketplaces": private_mkts,
            "marketplace_events": events}


@moderation_router.get("/queue",
                       responses={401: {"model": ApiErrorResponse},
                                  403: {"model": ApiErrorResponse}})
async def master_queue(
    request: Request, kind: str = Query("listings"),
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    platform_user = Depends(require_platform_owner()),
    db: AsyncSession = Depends(get_db),
):
    _ = request
    _ = platform_user
    stmt: Any = None
    count_stmt: Any = None
    serialize: Any = None
    if kind == "listings":
        stmt = select(MarketplaceListing).where(
            MarketplaceListing.status.in_([ListingStatus.SUBMITTED,
                                           ListingStatus.VALIDATING,
                                           ListingStatus.UNDER_REVIEW]),
            MarketplaceListing.deleted_at.is_(None))
        count_stmt = select(func.count(MarketplaceListing.id)).where(
            MarketplaceListing.status.in_([ListingStatus.SUBMITTED,
                                           ListingStatus.VALIDATING,
                                           ListingStatus.UNDER_REVIEW]),
            MarketplaceListing.deleted_at.is_(None))
        serialize = lambda r: {  # noqa: E731
            "id": str(r.id), "slug": r.slug, "title": r.title,
            "status": r.status.value, "marketplace_id": str(r.marketplace_id),
            "publisher_id": str(r.publisher_id), "updated_at": r.updated_at.isoformat()}
    elif kind == "reports":
        stmt = select(MarketplaceReport).where(
            MarketplaceReport.status.in_([ReportState.OPEN, ReportState.INVESTIGATING,
                                          ReportState.ACTION_REQUIRED]))
        count_stmt = select(func.count(MarketplaceReport.id)).where(
            MarketplaceReport.status.in_([ReportState.OPEN, ReportState.INVESTIGATING,
                                          ReportState.ACTION_REQUIRED]))
        serialize = lambda r: {  # noqa: E731
            "id": str(r.id), "target_type": r.target_type,
            "target_id": str(r.target_id) if r.target_id else None,
            "reason": r.reason.value, "status": r.status.value,
            "created_at": r.created_at.isoformat()}
    elif kind == "reviews":
        stmt = select(ListingReview).where(
            ListingReview.status.in_([ReviewStatus.PENDING, ReviewStatus.FLAGGED]))
        count_stmt = select(func.count(ListingReview.id)).where(
            ListingReview.status.in_([ReviewStatus.PENDING, ReviewStatus.FLAGGED]))
        serialize = lambda r: _review_out(r)  # noqa: E731
    elif kind == "advisories":
        stmt = select(SecurityAdvisory).where(
            SecurityAdvisory.status == AdvisoryStatus.AFFECTED)
        count_stmt = select(func.count(SecurityAdvisory.id)).where(
            SecurityAdvisory.status == AdvisoryStatus.AFFECTED)
        serialize = lambda r: _advisory_out(r)  # noqa: E731
    elif kind == "revoked":
        stmt = select(MarketplaceListing).where(
            MarketplaceListing.status == ListingStatus.REVOKED)
        count_stmt = select(func.count(MarketplaceListing.id)).where(
            MarketplaceListing.status == ListingStatus.REVOKED)
        serialize = lambda r: {  # noqa: E731
            "id": str(r.id), "slug": r.slug, "title": r.title,
            "status": r.status.value, "status_reason": r.status_reason}
    else:
        raise HTTPException(status_code=400, detail={
            "error": "Unknown queue kind", "code": "BAD_QUEUE"})
    total = (await db.execute(count_stmt)).scalar_one()
    order_col = {"listings": MarketplaceListing.updated_at,
                 "revoked": MarketplaceListing.updated_at,
                 "reports": MarketplaceReport.created_at,
                 "reviews": ListingReview.created_at,
                 "advisories": SecurityAdvisory.created_at}[kind]
    rows = list((await db.execute(stmt.order_by(order_col.desc())
                  .limit(page_size).offset((page - 1) * page_size))).scalars().all())
    return {"data": [serialize(r) for r in rows],
            "meta": create_pagination_meta(page, page_size, total).model_dump()}


class MasterAction(BaseModel):
    target_type: str = Field(pattern="^(listing|publisher|review|report)$")
    target_id: UUID
    action: str
    reason: str = Field(min_length=1, max_length=2000)
    metadata: dict[str, Any] = Field(default_factory=dict)


@moderation_router.post("/action",
                        responses={400: {"model": ApiErrorResponse},
                                   401: {"model": ApiErrorResponse},
                                   403: {"model": ApiErrorResponse},
                                   404: {"model": ApiErrorResponse},
                                   409: {"model": ApiErrorResponse}})
async def master_action(
    request: Request, data: MasterAction,
    platform_user = Depends(require_platform_owner()),
    db: AsyncSession = Depends(get_db),
):
    """Generic audited moderation action (platform owners only)."""
    from openagent.packages import telemetry as ptelemetry

    _ = request
    action = data.action.upper()
    try:
        mod_action = ModerationAction(action)
    except ValueError:
        raise HTTPException(status_code=400, detail={
            "error": f"Unknown moderation action {data.action!r}",
            "code": "BAD_ACTION"})
    summary: dict[str, Any] = {"action": action}
    if data.target_type == "listing":
        listing = await _get_listing(db, data.target_id)
        if action in ("FEATURE", "UNFEATURE"):
            badges = dict(listing.badges or {})
            badges["featured"] = action == "FEATURE"
            badges["featured_reason"] = data.reason[:500] if action == "FEATURE" else ""
            badges["featured_by"] = str(platform_user.id)
            listing.badges = badges
            summary["featured"] = action == "FEATURE"
        else:
            transitions = {
                "APPROVE": ListingStatus.APPROVED.value,
                "REJECT": ListingStatus.REJECTED.value,
                "SUSPEND": ListingStatus.SUSPENDED.value,
                "REVOKE": ListingStatus.REVOKED.value,
                "RESTORE": ListingStatus.PUBLISHED.value,
            }
            if action not in transitions:
                raise HTTPException(status_code=400, detail={
                    "error": f"Action {action} not valid for listings",
                    "code": "BAD_ACTION"})
            target = transitions[action]
            await _transition_listing(db, listing, target,
                                      actor=platform_user.id, reason=data.reason,
                                      organization_id=None)
            summary["status"] = target
    elif data.target_type == "publisher":
        pub = await _get_publisher(db, data.target_id)
        verify_map = {"VERIFY_PUBLISHER": "VERIFIED", "SUSPEND_PUBLISHER": "SUSPENDED"}
        if action not in verify_map:
            raise HTTPException(status_code=400, detail={
                "error": f"Action {action} not valid for publishers",
                "code": "BAD_ACTION"})
        if not can_transition_verification(pub.verification_status, verify_map[action]):
            raise HTTPException(status_code=409, detail={
                "error": "Illegal verification transition", "code": "BAD_TRANSITION"})
        pub.verification_status = VerificationStatus(verify_map[action]).value
        pub.verified = verify_map[action] == "VERIFIED"
        pub.verified_by = platform_user.id
        pub.verified_at = _now() if pub.verified else None
        summary["verification_status"] = verify_map[action]
        await ptelemetry.emit(db, event_type="PUBLISHER_VERIFIED",
                              aggregate_id=pub.id, user_id=platform_user.id,
                              payload={"status": verify_map[action]})
    elif data.target_type == "review":
        review = await db.get(ListingReview, data.target_id)
        if review is None:
            raise _not_found("Review")
        review_map = {"HIDE_REVIEW": ReviewStatus.HIDDEN,
                      "REMOVE_REVIEW": ReviewStatus.REMOVED,
                      "RESTORE": ReviewStatus.PUBLISHED}
        if action not in review_map:
            raise HTTPException(status_code=400, detail={
                "error": f"Action {action} not valid for reviews",
                "code": "BAD_ACTION"})
        review.status = review_map[action]
        review.status_reason = data.reason[:1000]
        await _recompute_rating(db, review.listing_id)
        summary["status"] = review_map[action].value
    elif data.target_type == "report":
        report = await db.get(MarketplaceReport, data.target_id)
        if report is None:
            raise _not_found("Report")
        report.status = ReportState.RESOLVED
        report.resolution = {"action": action, "reason": data.reason[:1000],
                             **data.metadata}
        summary["status"] = "RESOLVED"
    db.add(ModerationActionRecord(
        target_type=data.target_type, target_id=data.target_id,
        action=mod_action, reason=data.reason[:2000],
        moderator_user_id=platform_user.id, action_metadata=data.metadata))
    await ptelemetry.audit(db, organization_id=None,
                           actor_user_id=platform_user.id,
                           action=f"marketplace.master.{action.lower()}",
                           resource_id=data.target_id,
                           metadata={"target_type": data.target_type,
                                     "reason": data.reason[:500]})
    await db.commit()
    return summary


@moderation_router.get("/events",
                       responses={401: {"model": ApiErrorResponse},
                                  403: {"model": ApiErrorResponse}})
async def master_events(
    request: Request, event_type: str = Query(""),
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    platform_user = Depends(require_platform_owner()),
    db: AsyncSession = Depends(get_db),
):
    _ = request
    _ = platform_user
    stmt = select(MarketplaceEvent)
    count_stmt = select(func.count(MarketplaceEvent.id))
    if event_type:
        try:
            wanted = AnalyticsEventType(event_type.upper())
        except ValueError:
            raise HTTPException(status_code=400, detail={
                "error": "Unknown event type", "code": "BAD_EVENT"})
        stmt = stmt.where(MarketplaceEvent.event_type == wanted)
        count_stmt = count_stmt.where(MarketplaceEvent.event_type == wanted)
    total = (await db.execute(count_stmt)).scalar_one()
    rows = list((await db.execute(stmt.order_by(MarketplaceEvent.created_at.desc())
                  .limit(page_size).offset((page - 1) * page_size))).scalars().all())
    return {"data": [{
        "id": str(e.id), "event_type": e.event_type.value,
        "listing_id": str(e.listing_id) if e.listing_id else None,
        "organization_id": str(e.organization_id) if e.organization_id else None,
        "metadata": e.event_metadata, "created_at": e.created_at.isoformat(),
    } for e in rows],
        "meta": create_pagination_meta(page, page_size, total).model_dump()}


class CategoryCreate(BaseModel):
    slug: str = Field(min_length=1, max_length=100, pattern="^[a-z0-9]+(?:[-][a-z0-9]+)*$")
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    parent_id: Optional[UUID] = None
    marketplace_id: Optional[UUID] = None
    position: int = 0


def _registry_out(registry: MarketplaceRegistry,
                  by_slug: Optional[dict] = None) -> dict:
    from openagent.marketplace.registry import mirror_chain

    return {
        "id": str(registry.id), "slug": registry.slug, "name": registry.name,
        "kind": registry.kind.value, "url_or_ref": registry.url_or_ref,
        "trust_level": registry.trust_level, "is_public": registry.is_public,
        "verification_policy": registry.verification_policy,
        "signature_policy": registry.signature_policy,
        "mirror_of": registry.mirror_of, "enabled": registry.enabled,
        "mirror_chain": mirror_chain(
            {"slug": registry.slug, "mirror_of": registry.mirror_of},
            by_slug or {}),
        "created_at": registry.created_at.isoformat(),
    }


@marketplace_router.get("/registries",
                        responses={401: {"model": ApiErrorResponse},
                                   403: {"model": ApiErrorResponse}})
async def list_registries(
    request: Request,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Configured registries. Trust is explicit per registry; none is implicit."""
    await _need(request, db, "marketplace:read")
    rows = list((await db.execute(select(MarketplaceRegistry).where(
        MarketplaceRegistry.enabled.is_(True))
        .order_by(MarketplaceRegistry.slug).limit(100))).scalars().all())
    by_slug = {r.slug: {"slug": r.slug, "mirror_of": r.mirror_of} for r in rows}
    visible = [r for r in rows
               if r.is_public or auth_context.is_platform_owner]
    return {"data": [_registry_out(r, by_slug) for r in visible]}


class RegistryCreate(BaseModel):
    slug: str = Field(min_length=1, max_length=100, pattern="^[a-z0-9]+(?:[-][a-z0-9]+)*$")
    name: str = Field(min_length=1, max_length=255)
    kind: str = Field(default="COMMUNITY")
    url_or_ref: str = Field(default="", max_length=1000)
    trust_level: str = Field(default="UNTRUSTED")
    is_public: bool = False
    verification_policy: dict[str, Any] = Field(default_factory=dict)
    signature_policy: dict[str, Any] = Field(default_factory=dict)
    mirror_of: str = Field(default="", max_length=100)


@moderation_router.post("/registries", status_code=status.HTTP_201_CREATED,
                        responses={400: {"model": ApiErrorResponse},
                                   401: {"model": ApiErrorResponse},
                                   403: {"model": ApiErrorResponse},
                                   409: {"model": ApiErrorResponse}})
async def master_create_registry(
    request: Request, data: RegistryCreate,
    platform_user=Depends(require_platform_owner()),
    db: AsyncSession = Depends(get_db),
):
    from openagent.packages import telemetry as ptelemetry

    _ = request
    try:
        kind = RegistryKind(data.kind.upper())
    except ValueError:
        raise HTTPException(status_code=400, detail={
            "error": "Unknown registry kind", "code": "BAD_KIND"})
    if data.url_or_ref:
        ref = data.url_or_ref.strip()
        if ref.lower().startswith(("javascript:", "data:", "file:")):
            raise HTTPException(status_code=400, detail={
                "error": "Unsafe registry reference", "code": "BAD_URL"})
        if kind in (RegistryKind.COMMUNITY, RegistryKind.OFFICIAL,
                    RegistryKind.ENTERPRISE):
            sanitize_module.check_url(ref, field="url_or_ref")
    dup = (await db.execute(select(MarketplaceRegistry).where(
        MarketplaceRegistry.slug == data.slug))).scalar_one_or_none()
    if dup is not None:
        raise HTTPException(status_code=409, detail={
            "error": "Registry slug exists", "code": "SLUG_EXISTS"})
    row = MarketplaceRegistry(
        slug=data.slug, name=sanitize_module.strip_html(data.name)[:255],
        kind=kind, url_or_ref=data.url_or_ref.strip()[:1000],
        trust_level=data.trust_level.upper(), is_public=data.is_public,
        verification_policy=data.verification_policy,
        signature_policy=data.signature_policy, mirror_of=data.mirror_of)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    await ptelemetry.audit(db, organization_id=None,
                           actor_user_id=platform_user.id,
                           action="marketplace.registry.create",
                           resource_id=row.id,
                           metadata={"slug": row.slug, "kind": kind.value})
    await db.commit()
    return _registry_out(row)


@moderation_router.post("/categories", status_code=status.HTTP_201_CREATED,
                        responses={400: {"model": ApiErrorResponse},
                                   401: {"model": ApiErrorResponse},
                                   403: {"model": ApiErrorResponse},
                                   409: {"model": ApiErrorResponse}})
async def master_create_category(
    request: Request, data: CategoryCreate,
    platform_user = Depends(require_platform_owner()),
    db: AsyncSession = Depends(get_db),
):
    _ = request
    _ = platform_user
    if data.parent_id:
        parent = await db.get(MarketplaceCategory, data.parent_id)
        if parent is None:
            raise _not_found("Parent category")
    dup = (await db.execute(select(MarketplaceCategory).where(
        MarketplaceCategory.slug == data.slug,
        MarketplaceCategory.marketplace_id == data.marketplace_id
    ))).scalars().all()
    if dup:
        raise HTTPException(status_code=409, detail={
            "error": "Category slug exists in this scope", "code": "SLUG_EXISTS"})
    row = MarketplaceCategory(
        marketplace_id=data.marketplace_id, parent_id=data.parent_id,
        slug=data.slug, name=sanitize_module.strip_html(data.name)[:120],
        description=sanitize_module.strip_html(data.description)[:2000],
        position=data.position, official=data.marketplace_id is None)
    db.add(row)
    await db.commit()
    return {"id": str(row.id), "slug": row.slug, "name": row.name}

