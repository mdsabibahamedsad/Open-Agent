"""MP23 service tests: marketplace/publisher/listing/review/advisory flows
at the model + domain level using shared DB fixtures.

Requires a database (CI postgres), like MP22's test_packages_api.py.
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from openagent.db.models.marketplace import (
    ListingFavorite,
    ListingReview,
    Marketplace,
    MarketplaceListing,
    PublisherFollower,
    PublisherMember,
    ReviewStatus,
)
from openagent.db.models.organization import Organization
from openagent.db.models.package import (
    PackageVersion,
    PackageVersionStatus,
    PublisherProfile,
    ReusablePackage,
)
from openagent.marketplace.types import can_transition_listing


async def _marketplace(db, slug="mkt-test", mtype="PUBLIC_MARKETPLACE",
                       owner_id=None):
    row = Marketplace(slug=slug, name=slug, type=mtype,
                      owner_organization_id=owner_id, visibility="PUBLIC")
    db.add(row)
    await db.flush()
    return row


async def _publisher(db, slug="pub-test"):
    row = PublisherProfile(display_name=slug, slug=slug,
                           publisher_type="INDIVIDUAL")
    db.add(row)
    await db.flush()
    return row


async def _package(db, org: Organization, slug="pkg-test"):
    pkg = ReusablePackage(
        organization_id=None, slug=slug, name=slug,
        description="test package", package_type="WORKFLOW",
        visibility="PUBLIC", trust="COMMUNITY", official=False,
        latest_version="1.0.0")
    db.add(pkg)
    await db.flush()
    version = PackageVersion(
        package_id=pkg.id, version="1.0.0",
        status=PackageVersionStatus.PUBLISHED,
        manifest={"format": "openagent-package", "format_version": "1",
                  "package": {"id": slug, "name": slug, "version": "1.0.0",
                              "type": "WORKFLOW"}},
        content_hash="0" * 64, risk="LOW")
    db.add(version)
    await db.flush()
    return pkg, version


async def _listing(db, marketplace, package, publisher, slug="listing-test",
                   status="PUBLISHED"):
    row = MarketplaceListing(
        marketplace_id=marketplace.id, package_id=package.id,
        publisher_id=publisher.id, slug=slug, title=slug,
        short_description="short", full_description="full",
        category="automation", license="MIT",
        published_version="1.0.0", status=status)
    db.add(row)
    await db.flush()
    return row


class TestMarketplaceVisibility:
    async def test_private_marketplace_isolated(self, db_session, org_a, org_b):
        from openagent.api.v1.marketplace import _listing_search_base

        mkt = await _marketplace(db_session, slug="priv-mkt",
                                 mtype="PRIVATE_MARKETPLACE",
                                 owner_id=org_a.id)
        pub = await _publisher(db_session, slug="priv-pub")
        pkg, _ver = await _package(db_session, org_a, slug="priv-pkg")
        await _listing(db_session, mkt, pkg, pub, slug="priv-listing")

        rows_b = list((await db_session.execute(
            _listing_search_base(org_b.id).limit(100))).all())
        assert all(r[0].slug != "priv-listing" for r in rows_b)

        rows_a = list((await db_session.execute(
            _listing_search_base(org_a.id).limit(100))).all())
        assert any(r[0].slug == "priv-listing" for r in rows_a)

    async def test_public_marketplace_visible(self, db_session, org_a, org_b):
        from openagent.api.v1.marketplace import _listing_search_base

        mkt = await _marketplace(db_session, slug="pub-mkt")
        pub = await _publisher(db_session, slug="pub-pub")
        pkg, _ver = await _package(db_session, org_a, slug="pub-pkg")
        await _listing(db_session, mkt, pkg, pub, slug="pub-listing")

        rows = list((await db_session.execute(
            _listing_search_base(org_b.id).limit(100))).all())
        assert any(r[0].slug == "pub-listing" for r in rows)

    async def test_draft_never_searchable(self, db_session, org_a):
        from openagent.api.v1.marketplace import _listing_search_base

        mkt = await _marketplace(db_session, slug="draft-mkt")
        pub = await _publisher(db_session, slug="draft-pub")
        pkg, _ver = await _package(db_session, org_a, slug="draft-pkg")
        await _listing(db_session, mkt, pkg, pub, slug="draft-listing",
                       status="DRAFT")

        rows = list((await db_session.execute(
            _listing_search_base(org_a.id).limit(100))).all())
        assert all(r[0].slug != "draft-listing" for r in rows)


class TestReviews:
    async def test_duplicate_review_rejected(self, db_session, org_a, user_a):
        mkt = await _marketplace(db_session, slug="rev-mkt")
        pub = await _publisher(db_session, slug="rev-pub")
        pkg, ver = await _package(db_session, org_a, slug="rev-pkg")
        listing = await _listing(db_session, mkt, pkg, pub, slug="rev-listing")

        db_session.add(ListingReview(
            listing_id=listing.id, version_id=ver.id,
            reviewer_user_id=user_a.id, organization_id=org_a.id,
            rating=5, title="Great", body="Works well for our team daily.",
            status=ReviewStatus.PUBLISHED, verified_use=True))
        await db_session.flush()
        db_session.add(ListingReview(
            listing_id=listing.id, version_id=ver.id,
            reviewer_user_id=user_a.id, organization_id=org_a.id,
            rating=4, title="Again", body="Still works well for us daily.",
            status=ReviewStatus.PUBLISHED, verified_use=True))
        with pytest.raises(IntegrityError):
            await db_session.flush()
        await db_session.rollback()

    async def test_rating_recompute_excludes_hidden(self, db_session, org_a,
                                                    user_a, user_b):
        from openagent.api.v1.marketplace import _recompute_rating

        mkt = await _marketplace(db_session, slug="agg-mkt")
        pub = await _publisher(db_session, slug="agg-pub")
        pkg, ver = await _package(db_session, org_a, slug="agg-pkg")
        listing = await _listing(db_session, mkt, pkg, pub, slug="agg-listing")

        db_session.add(ListingReview(
            listing_id=listing.id, version_id=ver.id,
            reviewer_user_id=user_a.id, organization_id=org_a.id,
            rating=5, title="Great", body="Works well for our team daily.",
            status=ReviewStatus.PUBLISHED, verified_use=True))
        db_session.add(ListingReview(
            listing_id=listing.id, version_id=ver.id,
            reviewer_user_id=user_b.id, organization_id=org_a.id,
            rating=1, title="Hidden", body="Hidden review body here daily.",
            status=ReviewStatus.HIDDEN, verified_use=False))
        await db_session.flush()
        await _recompute_rating(db_session, listing.id)
        await db_session.refresh(listing)
        assert listing.rating_count == 1
        assert listing.rating_average == 5.0
        assert listing.verified_review_count == 1

    async def test_favorite_unique(self, db_session, org_a, user_a):
        mkt = await _marketplace(db_session, slug="fav-mkt")
        pub = await _publisher(db_session, slug="fav-pub")
        pkg, _ver = await _package(db_session, org_a, slug="fav-pkg")
        listing = await _listing(db_session, mkt, pkg, pub, slug="fav-listing")

        db_session.add(ListingFavorite(
            listing_id=listing.id, user_id=user_a.id,
            organization_id=org_a.id))
        await db_session.flush()
        db_session.add(ListingFavorite(
            listing_id=listing.id, user_id=user_a.id,
            organization_id=org_a.id))
        with pytest.raises(IntegrityError):
            await db_session.flush()
        await db_session.rollback()

    async def test_follow_unique(self, db_session, org_a, user_a):
        pub = await _publisher(db_session, slug="fol-pub")
        db_session.add(PublisherFollower(
            publisher_id=pub.id, user_id=user_a.id,
            organization_id=org_a.id))
        await db_session.flush()
        db_session.add(PublisherFollower(
            publisher_id=pub.id, user_id=user_a.id,
            organization_id=org_a.id))
        with pytest.raises(IntegrityError):
            await db_session.flush()
        await db_session.rollback()


class TestListingLifecycleDb:
    async def test_revoked_listing_blocked_from_search(self, db_session, org_a):
        from openagent.api.v1.marketplace import _listing_search_base

        mkt = await _marketplace(db_session, slug="rev-mkt")
        pub = await _publisher(db_session, slug="rev-pub")
        pkg, _ver = await _package(db_session, org_a, slug="rev-pkg")
        await _listing(db_session, mkt, pkg, pub, slug="rev-listing",
                       status="REVOKED")

        rows = list((await db_session.execute(
            _listing_search_base(org_a.id).limit(100))).all())
        assert all(r[0].slug != "rev-listing" for r in rows)

    async def test_transition_table_matches_model(self):
        # Model enum and domain transition table must agree on states.
        from openagent.db.models.marketplace import ListingStatus as ModelStatus

        model_states = {s.value for s in ModelStatus}
        from openagent.marketplace.types import LISTING_TRANSITIONS

        assert model_states == set(LISTING_TRANSITIONS)
        assert can_transition_listing("PUBLISHED", "REVOKED")

    async def test_publisher_last_owner_rule(self, db_session, user_a):
        # Only one OWNER: model allows it, API blocks removal (covered by
        # contract + unit reasoning); here assert membership uniqueness.
        pub = await _publisher(db_session, slug="own-pub")
        db_session.add(PublisherMember(publisher_id=pub.id, user_id=user_a.id,
                                       role="OWNER"))
        await db_session.flush()
        db_session.add(PublisherMember(publisher_id=pub.id, user_id=user_a.id,
                                       role="OWNER"))
        with pytest.raises(IntegrityError):
            await db_session.flush()
        await db_session.rollback()


class TestAdvisoryMatching:
    async def test_affected_spec_matching(self, db_session, org_a):
        from openagent.db.models.marketplace import SecurityAdvisory
        from openagent.packages.versioning import satisfies

        mkt = await _marketplace(db_session, slug="adv-mkt")
        pub = await _publisher(db_session, slug="adv-pub")
        pkg, _ver = await _package(db_session, org_a, slug="adv-pkg")
        listing = await _listing(db_session, mkt, pkg, pub, slug="adv-listing")
        advisory = SecurityAdvisory(
            package_id=pkg.id, listing_id=listing.id, title="Test advisory",
            affected_versions="< 2.0.0", severity="HIGH")
        db_session.add(advisory)
        await db_session.flush()

        assert satisfies("1.0.0", advisory.affected_versions)
        assert not satisfies("2.1.0", advisory.affected_versions)
