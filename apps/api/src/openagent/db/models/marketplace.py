"""MP23: marketplace / publisher / review / distribution / commerce persistence.

Layering (strict):

    OpenAgent Core -> Package System (MP22) -> Registry -> Catalog ->
    Distribution -> Commerce

Marketplace tables reference MP22 package tables but never duplicate them:
listings point at ``reusable_packages`` / ``package_versions``; installs go
through the MP22 installer; execution stays in the runtime systems.

Money is stored as integer minor units. No payment secrets are ever stored
here — billing provider references only.
"""

import enum
import uuid
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
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

from openagent.db.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin


class MarketplaceType(str, enum.Enum):
    PUBLIC_MARKETPLACE = "PUBLIC_MARKETPLACE"
    ORGANIZATION_MARKETPLACE = "ORGANIZATION_MARKETPLACE"
    TEAM_MARKETPLACE = "TEAM_MARKETPLACE"
    PRIVATE_MARKETPLACE = "PRIVATE_MARKETPLACE"
    LOCAL_CATALOG = "LOCAL_CATALOG"


class MarketplaceStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    ARCHIVED = "ARCHIVED"


class ListingStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    VALIDATING = "VALIDATING"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    PUBLISHED = "PUBLISHED"
    SUSPENDED = "SUSPENDED"
    DEPRECATED = "DEPRECATED"
    REVOKED = "REVOKED"
    ARCHIVED = "ARCHIVED"
    REJECTED = "REJECTED"


class PublisherType(str, enum.Enum):
    INDIVIDUAL = "INDIVIDUAL"
    ORGANIZATION = "ORGANIZATION"
    COMPANY = "COMPANY"
    COMMUNITY = "COMMUNITY"
    OPENAGENT_OFFICIAL = "OPENAGENT_OFFICIAL"


class VerificationStatus(str, enum.Enum):
    UNVERIFIED = "UNVERIFIED"
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    OFFICIAL = "OFFICIAL"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class ReviewStatus(str, enum.Enum):
    PUBLISHED = "PUBLISHED"
    PENDING = "PENDING"
    FLAGGED = "FLAGGED"
    HIDDEN = "HIDDEN"
    REMOVED = "REMOVED"


class AdvisorySeverity(str, enum.Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class AdvisoryStatus(str, enum.Enum):
    AFFECTED = "AFFECTED"
    RESOLVED = "RESOLVED"
    REVOKED = "REVOKED"


class PricingModel(str, enum.Enum):
    FREE = "FREE"
    ONE_TIME = "ONE_TIME"
    SUBSCRIPTION = "SUBSCRIPTION"
    USAGE_BASED = "USAGE_BASED"
    TIERED = "TIERED"
    VOLUME = "VOLUME"
    ENTERPRISE = "ENTERPRISE"
    CUSTOM = "CUSTOM"


class ProductType(str, enum.Enum):
    SINGLE_LISTING = "SINGLE_LISTING"
    BUNDLE = "BUNDLE"
    SUPPORT_PLAN = "SUPPORT_PLAN"
    CUSTOM = "CUSTOM"
    # MP24: full product taxonomy (migration 023 adds the values).
    PACKAGE = "PACKAGE"
    SUBSCRIPTION = "SUBSCRIPTION"
    LICENSE = "LICENSE"
    CREDITS = "CREDITS"
    SERVICE = "SERVICE"
    ENTERPRISE = "ENTERPRISE"


class ProductStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class EntitlementStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    TRIAL = "TRIAL"


class RevenueStatus(str, enum.Enum):
    PENDING = "PENDING"
    SETTLED = "SETTLED"
    DISPUTED = "DISPUTED"


class PayoutStatus(str, enum.Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    PAID = "PAID"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ReportReason(str, enum.Enum):
    SPAM = "SPAM"
    ABUSE = "ABUSE"
    HARASSMENT = "HARASSMENT"
    FRAUD = "FRAUD"
    IRRELEVANT = "IRRELEVANT"
    SENSITIVE_INFORMATION = "SENSITIVE_INFORMATION"
    MANIPULATION = "MANIPULATION"
    COPYRIGHT = "COPYRIGHT"
    TRADEMARK = "TRADEMARK"
    MALICIOUS = "MALICIOUS"
    IMPERSONATION = "IMPERSONATION"
    POLICY_VIOLATION = "POLICY_VIOLATION"
    OTHER = "OTHER"


class ReportState(str, enum.Enum):
    OPEN = "OPEN"
    INVESTIGATING = "INVESTIGATING"
    ACTION_REQUIRED = "ACTION_REQUIRED"
    RESOLVED = "RESOLVED"
    DISMISSED = "DISMISSED"


class ModerationAction(str, enum.Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    SUSPEND = "SUSPEND"
    REVOKE = "REVOKE"
    REQUEST_CHANGES = "REQUEST_CHANGES"
    FLAG_PUBLISHER = "FLAG_PUBLISHER"
    FLAG_PACKAGE = "FLAG_PACKAGE"
    RESTORE = "RESTORE"
    HIDE_REVIEW = "HIDE_REVIEW"
    REMOVE_REVIEW = "REMOVE_REVIEW"
    VERIFY_PUBLISHER = "VERIFY_PUBLISHER"
    SUSPEND_PUBLISHER = "SUSPEND_PUBLISHER"
    FEATURE = "FEATURE"
    UNFEATURE = "UNFEATURE"


class AnalyticsEventType(str, enum.Enum):
    VIEW = "VIEW"
    SEARCH = "SEARCH"
    CLICK = "CLICK"
    INSTALL_STARTED = "INSTALL_STARTED"
    INSTALL_COMPLETED = "INSTALL_COMPLETED"
    INSTALL_FAILED = "INSTALL_FAILED"
    UPDATE = "UPDATE"
    UNINSTALL = "UNINSTALL"
    FAVORITE = "FAVORITE"
    SHARE = "SHARE"
    REVIEW = "REVIEW"
    REPORT = "REPORT"


class NotificationType(str, enum.Enum):
    LISTING_APPROVED = "LISTING_APPROVED"
    LISTING_REJECTED = "LISTING_REJECTED"
    REVIEW_RECEIVED = "REVIEW_RECEIVED"
    SECURITY_ISSUE = "SECURITY_ISSUE"
    PACKAGE_REVOKED = "PACKAGE_REVOKED"
    UPDATE_PUBLISHED = "UPDATE_PUBLISHED"
    PAYOUT_EVENT = "PAYOUT_EVENT"
    INSTALLED_UPDATE = "INSTALLED_UPDATE"
    SECURITY_ADVISORY = "SECURITY_ADVISORY"
    REVOKED_PACKAGE = "REVOKED_PACKAGE"
    FOLLOWED_RELEASE = "FOLLOWED_RELEASE"
    REVIEW_RESPONSE = "REVIEW_RESPONSE"
    MODERATION_DECISION = "MODERATION_DECISION"


class ArtifactType(str, enum.Enum):
    PACKAGE_ARCHIVE = "PACKAGE_ARCHIVE"
    MANIFEST = "MANIFEST"
    METADATA = "METADATA"
    SIGNATURE = "SIGNATURE"
    INTEGRITY = "INTEGRITY"
    DOCUMENTATION = "DOCUMENTATION"
    ASSET = "ASSET"


class ArtifactStatus(str, enum.Enum):
    PENDING = "PENDING"
    VERIFYING = "VERIFYING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    PUBLISHED = "PUBLISHED"


class DistributionProvider(str, enum.Enum):
    LOCAL = "LOCAL"
    OBJECT_STORAGE = "OBJECT_STORAGE"
    CDN = "CDN"
    REGISTRY = "REGISTRY"
    GITHUB_RELEASE = "GITHUB_RELEASE"
    FUTURE_CLOUD = "FUTURE_CLOUD"


class RegistryKind(str, enum.Enum):
    OFFICIAL = "OFFICIAL"
    COMMUNITY = "COMMUNITY"
    PRIVATE = "PRIVATE"
    GIT = "GIT"
    SELF_HOSTED = "SELF_HOSTED"
    ENTERPRISE = "ENTERPRISE"


class Marketplace(SoftDeleteMixin, TimestampMixin, UUIDMixin, Base):
    """A marketplace instance: public, org/team/private, or local catalog."""

    __tablename__ = "marketplaces"

    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[MarketplaceType] = mapped_column(
        SQLEnum(MarketplaceType, name="marketplace_type", create_constraint=True),
        nullable=False)
    owner_organization_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True, index=True)
    visibility: Mapped[str] = mapped_column(String(32), nullable=False, default="PUBLIC")
    status: Mapped[MarketplaceStatus] = mapped_column(
        SQLEnum(MarketplaceStatus, name="marketplace_status", create_constraint=True),
        default=MarketplaceStatus.ACTIVE, nullable=False)
    configuration: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    __table_args__ = (
        Index("ix_marketplaces_type", "type"),
        Index("ix_marketplaces_status", "status"),
        Index("ix_marketplaces_owner", "owner_organization_id"),
    )


class MarketplacePolicy(TimestampMixin, UUIDMixin, Base):
    """Declarative policy governing one marketplace instance."""

    __tablename__ = "marketplace_policies"

    marketplace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("marketplaces.id", ondelete="CASCADE"),
        nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    rules: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    updated_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class PublisherMember(TimestampMixin, UUIDMixin, Base):
    """Membership of a user in a publisher (MP22 PublisherProfile)."""

    __tablename__ = "publisher_members"

    publisher_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("publisher_profiles.id", ondelete="CASCADE"),
        nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="MEMBER")

    __table_args__ = (
        UniqueConstraint("publisher_id", "user_id", name="uq_publisher_members"),
        Index("ix_publisher_members_user", "user_id"),
    )


class PublisherFollower(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "publisher_followers"

    publisher_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("publisher_profiles.id", ondelete="CASCADE"),
        nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True)
    organization_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True, index=True)

    __table_args__ = (
        UniqueConstraint("publisher_id", "user_id", name="uq_publisher_followers"),
        Index("ix_publisher_followers_publisher", "publisher_id"),
    )


class MarketplaceCategory(TimestampMixin, UUIDMixin, Base):
    """Nested category hierarchy (NULL marketplace_id = global)."""

    __tablename__ = "marketplace_categories"

    marketplace_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("marketplaces.id", ondelete="CASCADE"),
        nullable=True, index=True)
    parent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("marketplace_categories.id", ondelete="CASCADE"),
        nullable=True, index=True)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    official: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_marketplace_categories_parent", "parent_id"),
        Index("ix_marketplace_categories_marketplace", "marketplace_id"),
    )


class MarketplaceTag(TimestampMixin, UUIDMixin, Base):
    """Normalized tag registry (prevents duplicates)."""

    __tablename__ = "marketplace_tags"

    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="package")
    usage_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class ListingTag(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "listing_tags"

    listing_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("marketplace_listings.id", ondelete="CASCADE"),
        nullable=False, index=True)
    tag_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("marketplace_tags.id", ondelete="CASCADE"),
        nullable=False, index=True)

    __table_args__ = (
        UniqueConstraint("listing_id", "tag_id", name="uq_listing_tags"),
    )


class MarketplaceListing(SoftDeleteMixin, TimestampMixin, UUIDMixin, Base):
    """First-class listing referencing an MP22 package + published version.

    Aggregates (rating_*, *_count) are maintained by review/analytics
    writers only — publishers can never edit them directly.
    """

    __tablename__ = "marketplace_listings"

    marketplace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("marketplaces.id", ondelete="CASCADE"),
        nullable=False, index=True)
    package_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reusable_packages.id", ondelete="CASCADE"),
        nullable=False, index=True)
    publisher_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("publisher_profiles.id", ondelete="RESTRICT"),
        nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    short_description: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    full_description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    icon: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    banner: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    screenshots: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)
    videos: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False, default="", index=True)
    license: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    pricing_model: Mapped[PricingModel] = mapped_column(
        SQLEnum(PricingModel, name="pricing_model", create_constraint=True),
        default=PricingModel.FREE, nullable=False, index=True)
    compatibility: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    requirements: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    trust_level: Mapped[str] = mapped_column(String(32), nullable=False, default="UNTRUSTED")
    security_status: Mapped[str] = mapped_column(String(16), nullable=False, default="UNKNOWN")
    published_version_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("package_versions.id", ondelete="SET NULL"),
        nullable=True, index=True)
    published_version: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    status: Mapped[ListingStatus] = mapped_column(
        SQLEnum(ListingStatus, name="listing_status", create_constraint=True),
        default=ListingStatus.DRAFT, nullable=False, index=True)
    status_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    badges: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    rating_average: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    rating_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rating_distribution: Mapped[Dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False)
    verified_review_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    install_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    successful_install_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    active_install_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    favorite_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    view_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("marketplace_id", "slug", name="uq_listings_marketplace_slug"),
        Index("ix_listings_package", "package_id"),
        Index("ix_listings_publisher", "publisher_id"),
        Index("ix_listings_status", "status"),
        Index("ix_listings_category", "category"),
        Index("ix_listings_rating", "rating_average", "rating_count"),
        Index("ix_listings_installs", "install_count"),
        Index("ix_listings_updated", "updated_at"),
        Index("ix_listings_published", "published_at"),
    )


class MarketplaceListingVersion(TimestampMixin, UUIDMixin, Base):
    """Explicit listing <-> package-version mapping with structured changelog."""

    __tablename__ = "marketplace_listing_versions"

    listing_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("marketplace_listings.id", ondelete="CASCADE"),
        nullable=False, index=True)
    version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("package_versions.id", ondelete="RESTRICT"),
        nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    changelog: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)

    __table_args__ = (
        UniqueConstraint("listing_id", "version_id", name="uq_listing_versions"),
        Index("ix_listing_versions_listing", "listing_id"),
    )


class ListingReview(TimestampMixin, UUIDMixin, Base):
    """A review always references the exact version installed/used."""

    __tablename__ = "listing_reviews"

    listing_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("marketplace_listings.id", ondelete="CASCADE"),
        nullable=False, index=True)
    version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("package_versions.id", ondelete="SET NULL"),
        nullable=False, index=True)
    installation_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("package_installations.id", ondelete="SET NULL"),
        nullable=True, index=True)
    reviewer_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True)
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    usage_context: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    status: Mapped[ReviewStatus] = mapped_column(
        SQLEnum(ReviewStatus, name="review_status", create_constraint=True),
        default=ReviewStatus.PUBLISHED, nullable=False, index=True)
    status_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    verified_use: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    helpful_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    __table_args__ = (
        UniqueConstraint("listing_id", "reviewer_user_id", "version_id",
                         name="uq_reviews_listing_user_version"),
        Index("ix_reviews_listing", "listing_id", "status"),
        Index("ix_reviews_reviewer", "reviewer_user_id"),
    )


class ReviewResponse(TimestampMixin, UUIDMixin, Base):
    """Single publisher response per review."""

    __tablename__ = "review_responses"

    review_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("listing_reviews.id", ondelete="CASCADE"),
        nullable=False, unique=True, index=True)
    responder_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True, index=True)
    publisher_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("publisher_profiles.id", ondelete="CASCADE"),
        nullable=False, index=True)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")


class ReviewReport(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "review_reports"

    review_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("listing_reviews.id", ondelete="CASCADE"),
        nullable=False, index=True)
    reporter_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True, index=True)
    reason: Mapped[ReportReason] = mapped_column(
        SQLEnum(ReportReason, name="report_reason", create_constraint=True),
        nullable=False, index=True)
    details: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[ReportState] = mapped_column(
        SQLEnum(ReportState, name="report_state", create_constraint=True),
        default=ReportState.OPEN, nullable=False, index=True)


class ListingFavorite(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "listing_favorites"

    listing_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("marketplace_listings.id", ondelete="CASCADE"),
        nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True)
    organization_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True, index=True)

    __table_args__ = (
        UniqueConstraint("listing_id", "user_id", name="uq_listing_favorites"),
    )


class MarketplaceEvent(TimestampMixin, UUIDMixin, Base):
    """Raw analytics event. Aggregated by worker; never exposes private content."""

    __tablename__ = "marketplace_events"

    marketplace_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("marketplaces.id", ondelete="CASCADE"),
        nullable=True, index=True)
    listing_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("marketplace_listings.id", ondelete="CASCADE"),
        nullable=True, index=True)
    event_type: Mapped[AnalyticsEventType] = mapped_column(
        SQLEnum(AnalyticsEventType, name="analytics_event_type", create_constraint=True),
        nullable=False, index=True)
    actor_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True, index=True)
    organization_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True, index=True)
    event_metadata: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    __table_args__ = (
        Index("ix_marketplace_events_listing", "listing_id", "event_type", "created_at"),
    )


class MarketplaceAnalyticsDaily(TimestampMixin, UUIDMixin, Base):
    """Pre-aggregated per-listing per-day counters (worker-maintained)."""

    __tablename__ = "marketplace_analytics_daily"

    listing_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("marketplace_listings.id", ondelete="CASCADE"),
        nullable=False, index=True)
    day: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    views: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    clicks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    installs_started: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    installs_completed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    installs_failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updates: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    uninstalls: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    favorites: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    shares: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reviews: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    __table_args__ = (
        UniqueConstraint("listing_id", "day", name="uq_analytics_listing_day"),
    )


class SecurityAdvisory(TimestampMixin, UUIDMixin, Base):
    """First-class advisory: affected versions, severity, recommended action."""

    __tablename__ = "security_advisories"

    package_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reusable_packages.id", ondelete="CASCADE"),
        nullable=True, index=True)
    listing_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("marketplace_listings.id", ondelete="SET NULL"),
        nullable=True, index=True)
    publisher_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("publisher_profiles.id", ondelete="SET NULL"),
        nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    affected_versions: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    severity: Mapped[AdvisorySeverity] = mapped_column(
        SQLEnum(AdvisorySeverity, name="advisory_severity", create_constraint=True),
        nullable=False, index=True)
    status: Mapped[AdvisoryStatus] = mapped_column(
        SQLEnum(AdvisoryStatus, name="advisory_status", create_constraint=True),
        default=AdvisoryStatus.AFFECTED, nullable=False, index=True)
    recommended_action: Mapped[str] = mapped_column(Text, nullable=False, default="Update")
    recommended_version: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    published_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_advisories_package", "package_id"),
        Index("ix_advisories_status", "status"),
    )


class PackageRevocation(TimestampMixin, UUIDMixin, Base):
    """Revocation record: keeps history, blocks installs, drives notify."""

    __tablename__ = "package_revocations"

    package_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reusable_packages.id", ondelete="CASCADE"),
        nullable=False, index=True)
    version_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("package_versions.id", ondelete="SET NULL"),
        nullable=True, index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    revoked_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    recommended_version: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    notify_issued: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class DistributionArtifact(TimestampMixin, UUIDMixin, Base):
    """Content-addressed distribution artifact (storage_key = sha256 path)."""

    __tablename__ = "distribution_artifacts"

    version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("package_versions.id", ondelete="CASCADE"),
        nullable=False, index=True)
    artifact_type: Mapped[ArtifactType] = mapped_column(
        SQLEnum(ArtifactType, name="artifact_type", create_constraint=True),
        nullable=False, index=True)
    storage_provider: Mapped[DistributionProvider] = mapped_column(
        SQLEnum(DistributionProvider, name="distribution_provider", create_constraint=True),
        default=DistributionProvider.LOCAL, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    mime: Mapped[str] = mapped_column(String(127), nullable=False, default="application/zip")
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    signature: Mapped[str] = mapped_column(Text, nullable=False, default="")
    signature_status: Mapped[str] = mapped_column(String(16), nullable=False, default="UNKNOWN")
    status: Mapped[ArtifactStatus] = mapped_column(
        SQLEnum(ArtifactStatus, name="artifact_status", create_constraint=True),
        default=ArtifactStatus.PENDING, nullable=False, index=True)
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    artifact_metadata: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    __table_args__ = (
        Index("ix_artifacts_version", "version_id", "artifact_type"),
        Index("ix_artifacts_status", "status"),
    )


class DistributionLocation(TimestampMixin, UUIDMixin, Base):
    """Where an artifact is available (mirror / CDN / registry ref)."""

    __tablename__ = "distribution_locations"

    artifact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("distribution_artifacts.id", ondelete="CASCADE"),
        nullable=False, index=True)
    provider: Mapped[DistributionProvider] = mapped_column(
        SQLEnum(DistributionProvider, name="distribution_provider", create_constraint=True),
        nullable=False)
    url_or_ref: Mapped[str] = mapped_column(String(1000), nullable=False)
    region: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class ArtifactDownload(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "artifact_downloads"

    artifact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("distribution_artifacts.id", ondelete="CASCADE"),
        nullable=False, index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True)
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True, index=True)
    listing_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("marketplace_listings.id", ondelete="SET NULL"),
        nullable=True, index=True)
    bytes_served: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class MarketplaceReport(TimestampMixin, UUIDMixin, Base):
    """Generic report: package / publisher / review / security issue."""

    __tablename__ = "marketplace_reports"

    marketplace_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("marketplaces.id", ondelete="CASCADE"),
        nullable=True, index=True)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    target_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True)
    target_slug: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    reason: Mapped[ReportReason] = mapped_column(
        SQLEnum(ReportReason, name="report_reason", create_constraint=True),
        nullable=False, index=True)
    details: Mapped[str] = mapped_column(Text, nullable=False, default="")
    reporter_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True, index=True)
    reporter_organization_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True)
    status: Mapped[ReportState] = mapped_column(
        SQLEnum(ReportState, name="report_state", create_constraint=True),
        default=ReportState.OPEN, nullable=False, index=True)
    resolution: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class ModerationActionRecord(TimestampMixin, UUIDMixin, Base):
    """Audited moderation action (never silent)."""

    __tablename__ = "moderation_actions"

    marketplace_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("marketplaces.id", ondelete="CASCADE"),
        nullable=True, index=True)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    target_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True)
    action: Mapped[ModerationAction] = mapped_column(
        SQLEnum(ModerationAction, name="moderation_action", create_constraint=True),
        nullable=False, index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    moderator_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True, index=True)
    action_metadata: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class Product(TimestampMixin, UUIDMixin, Base):
    """Commercial product attached to a listing (MP24: full product model)."""

    __tablename__ = "marketplace_products"

    listing_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("marketplace_listings.id", ondelete="CASCADE"),
        nullable=False, index=True)
    publisher_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("publisher_profiles.id", ondelete="SET NULL"),
        nullable=True, index=True)
    product_type: Mapped[ProductType] = mapped_column(
        SQLEnum(ProductType, name="product_type", create_constraint=True),
        nullable=False)
    pricing_model: Mapped[PricingModel] = mapped_column(
        SQLEnum(PricingModel, name="pricing_model", create_constraint=True),
        default=PricingModel.FREE, nullable=False, index=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    status: Mapped[ProductStatus] = mapped_column(
        SQLEnum(ProductStatus, name="product_status", create_constraint=True),
        default=ProductStatus.DRAFT, nullable=False, index=True)
    # MP24: commercial access level (FREE/PAID/PRIVATE/SUBSCRIPTION_ONLY/
    # ENTITLEMENT_REQUIRED), seat model, commercial license kind, trial.
    access: Mapped[str] = mapped_column(String(32), nullable=False, default="FREE")
    seat_model: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    license_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    trial_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    product_metadata: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class Price(TimestampMixin, UUIDMixin, Base):
    """A price point on a product. Amounts in integer minor units."""

    __tablename__ = "marketplace_prices"

    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("marketplace_products.id", ondelete="CASCADE"),
        nullable=False, index=True)
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    interval: Mapped[str] = mapped_column(String(16), nullable=False, default="ONE_TIME")
    # MP24: pricing model mirror, billing interval, trial, usage rules,
    # quantity bounds. ``tiers`` keeps provider price refs.
    pricing_model: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    billing_interval: Mapped[str] = mapped_column(
        String(16), nullable=False, default="ONE_TIME")
    trial_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    usage_rules: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    min_quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    max_quantity: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    tiers: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[ProductStatus] = mapped_column(
        SQLEnum(ProductStatus, name="product_status", create_constraint=True),
        default=ProductStatus.DRAFT, nullable=False)


class Entitlement(TimestampMixin, UUIDMixin, Base):
    """Commercial entitlement: org/user -> product. Never grants runtime perms."""

    __tablename__ = "marketplace_entitlements"

    organization_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True, index=True)
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True, index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("marketplace_products.id", ondelete="CASCADE"),
        nullable=False, index=True)
    listing_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("marketplace_listings.id", ondelete="CASCADE"),
        nullable=False, index=True)
    status: Mapped[EntitlementStatus] = mapped_column(
        SQLEnum(EntitlementStatus, name="entitlement_status", create_constraint=True),
        default=EntitlementStatus.ACTIVE, nullable=False, index=True)
    valid_from: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="manual")
    # MP24: feature grant, quantity tracking, org inheritance, source ref.
    feature: Mapped[str] = mapped_column(
        String(255), nullable=False, default="package.install")
    features: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)
    quantity: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    inherited: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    source_reference: Mapped[str] = mapped_column(
        String(255), nullable=False, default="")
    entitlement_metadata: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    __table_args__ = (
        Index("ix_entitlements_product_org", "product_id", "organization_id"),
        Index("ix_entitlements_status", "status"),
    )


class RevenueRecord(TimestampMixin, UUIDMixin, Base):
    """Publisher revenue line. Created only from verified billing events."""

    __tablename__ = "marketplace_revenue"

    publisher_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("publisher_profiles.id", ondelete="CASCADE"),
        nullable=False, index=True)
    product_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("marketplace_products.id", ondelete="SET NULL"),
        nullable=True, index=True)
    transaction_reference: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    gross_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fee_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    net_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    status: Mapped[RevenueStatus] = mapped_column(
        SQLEnum(RevenueStatus, name="revenue_status", create_constraint=True),
        default=RevenueStatus.PENDING, nullable=False, index=True)


class Payout(TimestampMixin, UUIDMixin, Base):
    """Payout instruction. No bank credentials stored here, ever."""

    __tablename__ = "marketplace_payouts"

    publisher_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("publisher_profiles.id", ondelete="CASCADE"),
        nullable=False, index=True)
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    status: Mapped[PayoutStatus] = mapped_column(
        SQLEnum(PayoutStatus, name="payout_status", create_constraint=True),
        default=PayoutStatus.PENDING, nullable=False, index=True)
    provider_reference: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # MP24: destination handle (never raw credentials), provider, hold.
    destination_reference: Mapped[str] = mapped_column(
        String(255), nullable=False, default="")
    provider: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    hold_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    requested_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True)
    processed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True)
    payout_metadata: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class BillingWebhookEvent(TimestampMixin, UUIDMixin, Base):
    """Persisted billing webhook with replay + idempotency protection."""

    __tablename__ = "billing_webhook_events"

    provider: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    event_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    payload: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    signature_valid: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    processed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    # MP24: retry + dead-letter tracking for failed webhook application.
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    dead_letter: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class MarketplaceNotification(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "marketplace_notifications"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True)
    organization_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True, index=True)
    type: Mapped[NotificationType] = mapped_column(
        SQLEnum(NotificationType, name="notification_type", create_constraint=True),
        nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    listing_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("marketplace_listings.id", ondelete="SET NULL"),
        nullable=True, index=True)
    publisher_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("publisher_profiles.id", ondelete="SET NULL"),
        nullable=True)
    read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)

    __table_args__ = (
        Index("ix_notifications_user_read", "user_id", "read"),
    )


class MarketplaceNotificationPref(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "marketplace_notification_prefs"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True)
    organization_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True, index=True)
    prefs: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "organization_id", name="uq_notification_prefs"),
    )


class MarketplaceRegistry(TimestampMixin, UUIDMixin, Base):
    """Configured package registry (official/community/private/git/...)."""

    __tablename__ = "marketplace_registries"

    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[RegistryKind] = mapped_column(
        SQLEnum(RegistryKind, name="registry_kind", create_constraint=True),
        nullable=False, index=True)
    url_or_ref: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    trust_level: Mapped[str] = mapped_column(String(32), nullable=False, default="UNTRUSTED")
    is_public: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    verification_policy: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    signature_policy: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    mirror_of: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # MP24: full registry model — type, endpoint, visibility, auth, status.
    registry_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="PRIVATE")
    endpoint: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    visibility: Mapped[str] = mapped_column(String(32), nullable=False, default="PRIVATE")
    auth_type: Mapped[str] = mapped_column(String(32), nullable=False, default="PUBLIC")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")
    last_sync_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True)
    organization_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True, index=True)
