"""MP23: marketplace domain vocabulary (dependency-free).

Listing lifecycle, publisher verification, review states, pricing /
entitlement / payout states, analytics + notification event types, sort
options, badges and registry kinds. Pure transition tables so the API,
worker and tests share one source of truth.
"""

from __future__ import annotations

import enum


class MarketplaceType(str, enum.Enum):
    PUBLIC_MARKETPLACE = "PUBLIC_MARKETPLACE"
    ORGANIZATION_MARKETPLACE = "ORGANIZATION_MARKETPLACE"
    TEAM_MARKETPLACE = "TEAM_MARKETPLACE"
    PRIVATE_MARKETPLACE = "PRIVATE_MARKETPLACE"
    LOCAL_CATALOG = "LOCAL_CATALOG"


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


#: Allowed listing transitions (source -> targets). Terminal states only
#: allow ARCHIVED; REVOKED listings keep history and never return to
#: PUBLISHED (a new version must be submitted instead).
LISTING_TRANSITIONS: dict[str, frozenset[str]] = {
    ListingStatus.DRAFT.value: frozenset({
        ListingStatus.SUBMITTED.value, ListingStatus.ARCHIVED.value}),
    ListingStatus.SUBMITTED.value: frozenset({
        ListingStatus.VALIDATING.value, ListingStatus.DRAFT.value,
        ListingStatus.ARCHIVED.value}),
    ListingStatus.VALIDATING.value: frozenset({
        ListingStatus.UNDER_REVIEW.value, ListingStatus.DRAFT.value,
        ListingStatus.REJECTED.value, ListingStatus.ARCHIVED.value}),
    ListingStatus.UNDER_REVIEW.value: frozenset({
        ListingStatus.APPROVED.value, ListingStatus.REJECTED.value,
        ListingStatus.DRAFT.value, ListingStatus.ARCHIVED.value}),
    ListingStatus.APPROVED.value: frozenset({
        ListingStatus.PUBLISHED.value, ListingStatus.DRAFT.value,
        ListingStatus.ARCHIVED.value}),
    ListingStatus.PUBLISHED.value: frozenset({
        ListingStatus.SUSPENDED.value, ListingStatus.DEPRECATED.value,
        ListingStatus.REVOKED.value, ListingStatus.ARCHIVED.value}),
    ListingStatus.SUSPENDED.value: frozenset({
        ListingStatus.PUBLISHED.value, ListingStatus.REVOKED.value,
        ListingStatus.ARCHIVED.value}),
    ListingStatus.DEPRECATED.value: frozenset({
        ListingStatus.REVOKED.value, ListingStatus.ARCHIVED.value}),
    ListingStatus.REVOKED.value: frozenset({ListingStatus.ARCHIVED.value}),
    ListingStatus.REJECTED.value: frozenset({
        ListingStatus.DRAFT.value, ListingStatus.ARCHIVED.value}),
    ListingStatus.ARCHIVED.value: frozenset(),
}


def can_transition_listing(source: str, target: str) -> bool:
    """Return True when a listing status transition is legal."""
    return target in LISTING_TRANSITIONS.get(source, frozenset())


#: Transitions that require moderation/platform authority (not the publisher).
MODERATED_TRANSITIONS: frozenset[str] = frozenset({
    ListingStatus.APPROVED.value,
    ListingStatus.REJECTED.value,
    ListingStatus.SUSPENDED.value,
    ListingStatus.REVOKED.value,
    ListingStatus.PUBLISHED.value,  # publish from APPROVED needs review proof
})


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


VERIFICATION_TRANSITIONS: dict[str, frozenset[str]] = {
    VerificationStatus.UNVERIFIED.value: frozenset({
        VerificationStatus.PENDING.value}),
    VerificationStatus.PENDING.value: frozenset({
        VerificationStatus.VERIFIED.value, VerificationStatus.OFFICIAL.value,
        VerificationStatus.UNVERIFIED.value}),
    VerificationStatus.VERIFIED.value: frozenset({
        VerificationStatus.SUSPENDED.value, VerificationStatus.REVOKED.value,
        VerificationStatus.OFFICIAL.value}),
    VerificationStatus.OFFICIAL.value: frozenset({
        VerificationStatus.SUSPENDED.value, VerificationStatus.REVOKED.value}),
    VerificationStatus.SUSPENDED.value: frozenset({
        VerificationStatus.VERIFIED.value, VerificationStatus.REVOKED.value,
        VerificationStatus.UNVERIFIED.value}),
    VerificationStatus.REVOKED.value: frozenset(),
}


def can_transition_verification(source: str, target: str) -> bool:
    return target in VERIFICATION_TRANSITIONS.get(source, frozenset())


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


class EntitlementStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    TRIAL = "TRIAL"


class PayoutStatus(str, enum.Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    PAID = "PAID"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


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


class BadgeKind(str, enum.Enum):
    FEATURED = "FEATURED"
    EDITORIAL = "EDITORIAL"
    OFFICIAL = "OFFICIAL"
    NEW = "NEW"
    TRENDING = "TRENDING"


class SearchSort(str, enum.Enum):
    RELEVANCE = "RELEVANCE"
    NEWEST = "NEWEST"
    UPDATED = "UPDATED"
    MOST_INSTALLED = "MOST_INSTALLED"
    MOST_USED = "MOST_USED"
    MOST_FAVORITED = "MOST_FAVORITED"
    HIGHEST_RATED = "HIGHEST_RATED"
    PRICE_LOW_TO_HIGH = "PRICE_LOW_TO_HIGH"
    PRICE_HIGH_TO_LOW = "PRICE_HIGH_TO_LOW"


class RegistryKind(str, enum.Enum):
    OFFICIAL = "OFFICIAL"
    COMMUNITY = "COMMUNITY"
    PRIVATE = "PRIVATE"
    GIT = "GIT"
    SELF_HOSTED = "SELF_HOSTED"
    ENTERPRISE = "ENTERPRISE"


#: Registry kinds the client trusts implicitly (none — explicit opt-in
#: always; official registries still require signatures per policy).
IMPLICITLY_TRUSTED_REGISTRIES: frozenset[str] = frozenset()

#: Outbox event types emitted by the marketplace domain.
MARKETPLACE_EVENTS: tuple[str, ...] = (
    "LISTING_CREATED",
    "LISTING_SUBMITTED",
    "LISTING_APPROVED",
    "LISTING_REJECTED",
    "LISTING_PUBLISHED",
    "LISTING_SUSPENDED",
    "LISTING_REVOKED",
    "PACKAGE_INSTALLED",
    "PACKAGE_UPDATED",
    "REVIEW_CREATED",
    "REVIEW_REPORTED",
    "PUBLISHER_VERIFIED",
    "SECURITY_ADVISORY_CREATED",
    "PACKAGE_REVOKED",
)

#: Metric names owned by this domain.
MARKETPLACE_METRICS: tuple[str, ...] = (
    "marketplace_listing_views_total",
    "marketplace_search_total",
    "marketplace_install_started_total",
    "marketplace_install_completed_total",
    "marketplace_install_failed_total",
    "marketplace_review_total",
    "marketplace_review_reported_total",
    "marketplace_favorite_total",
    "marketplace_advisory_total",
    "marketplace_revocation_total",
    "marketplace_webhook_rejected_total",
)

#: Sort keys mapped to listing columns (factual only; featured/organic
#: separation is enforced at query time, never inside ranking).
SORT_COLUMNS: dict[str, tuple[str, bool]] = {
    SearchSort.NEWEST.value: ("created_at", True),
    SearchSort.UPDATED.value: ("updated_at", True),
    SearchSort.MOST_INSTALLED.value: ("install_count", True),
    SearchSort.MOST_USED.value: ("successful_install_count", True),
    SearchSort.MOST_FAVORITED.value: ("favorite_count", True),
    SearchSort.HIGHEST_RATED.value: ("rating_average", True),
}

#: Metric definitions (single source for docs + UI labels).
METRIC_DEFINITIONS: dict[str, str] = {
    "install_count": "Total completed installations started from this listing.",
    "successful_install_count": "Installations that reached INSTALLED status.",
    "active_install_count": "Installations currently in INSTALLED status.",
    "rating_count": "Published, non-removed reviews counted in the aggregate.",
    "verified_review_count": "Reviews linked to a real installation record.",
    "view_count": "Detail-page views (bot-throttled, rate-limited).",
    "favorite_count": "Users who saved this listing.",
}
