#!/usr/bin/env python3
"""Seed development marketplace content. DEV ONLY — never run in production.

Creates, idempotently: the official OpenAgent publisher, MP22 sample
packages (published versions), and PUBLISHED listings for each in the
default public marketplace. All rows are real (validation passes, no fake
metrics); aggregates start at zero.

Usage:
    python scripts/seed_marketplace.py
"""

from __future__ import annotations

import asyncio
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "apps", "api", "src"))

if os.environ.get("OPENAGENT_ENV", "development") == "production":
    print("seed_marketplace.py refuses to run in production", file=sys.stderr)
    raise SystemExit(1)


async def main() -> None:
    from sqlalchemy import select

    from openagent.core.config import get_settings
    from openagent.db.models.marketplace import (
        ListingStatus,
        Marketplace,
        MarketplaceListing,
        MarketplaceListingVersion,
    )
    from openagent.db.models.package import (
        PackageDependency,
        PackageResource,
        PackageVersion,
        PackageVersionStatus,
        PublisherProfile,
        ReusablePackage,
    )
    from openagent.packages import validation as validation_module
    from openagent.packages.manifest import parse_manifest
    from openagent.packages.samples import all_samples
    from openagent.packages.signing import content_hash

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(get_settings().DATABASE_URL)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        marketplace = (await db.execute(select(Marketplace).where(
            Marketplace.slug == "openagent-public"))).scalar_one_or_none()
        if marketplace is None:
            print("default marketplace missing: run migrations first",
                  file=sys.stderr)
            raise SystemExit(1)
        publisher = (await db.execute(select(PublisherProfile).where(
            PublisherProfile.slug == "openagent-official"))).scalar_one_or_none()
        if publisher is None:
            publisher = PublisherProfile(
                display_name="OpenAgent", slug="openagent-official",
                publisher_type="OPENAGENT_OFFICIAL",
                description="Official OpenAgent packages.",
                website="https://openagent.dev",
                verification_status="OFFICIAL", verified=True)
            db.add(publisher)
            await db.flush()
            print("created publisher openagent-official")

        for package_id, raw in all_samples().items():
            report = validation_module.validate_package(raw)
            if not report["passed"]:
                print(f"SKIP {package_id}: sample failed validation")
                continue
            manifest = parse_manifest(raw).model_dump()
            pkg = (await db.execute(select(ReusablePackage).where(
                ReusablePackage.slug == package_id,
                ReusablePackage.organization_id.is_(None)))).scalar_one_or_none()
            if pkg is None:
                pkg = ReusablePackage(
                    organization_id=None, slug=package_id,
                    name=manifest["package"]["name"],
                    description=manifest.get("description", ""),
                    package_type=manifest["package"]["type"],
                    visibility="PUBLIC", trust="CORE", official=True,
                    license=manifest.get("license", "Apache-2.0"),
                    author_name="OpenAgent",
                    categories=manifest.get("categories", []),
                    tags=manifest.get("tags", []),
                    latest_version=manifest["package"]["version"])
                db.add(pkg)
                await db.flush()
            version = (await db.execute(select(PackageVersion).where(
                PackageVersion.package_id == pkg.id,
                PackageVersion.version == manifest["package"]["version"])
            )).scalar_one_or_none()
            if version is None:
                version = PackageVersion(
                    package_id=pkg.id, version=manifest["package"]["version"],
                    status=PackageVersionStatus.PUBLISHED, manifest=manifest,
                    content_hash=content_hash(manifest), risk=report["risk"],
                    changelog=manifest.get("changelog", ""))
                db.add(version)
                await db.flush()
                for resource in manifest.get("resources", []):
                    db.add(PackageResource(
                        version_id=version.id, kind=resource["kind"],
                        slug=resource["slug"], name=resource["name"],
                        payload=resource.get("payload", {})))
                for dep in manifest.get("dependencies", []):
                    db.add(PackageDependency(
                        version_id=version.id, dep_type=dep["type"],
                        package=dep["package"], constraint=dep.get("version", "*"),
                        optional=dep.get("optional", False),
                        peer=dep.get("peer", False)))
                pkg.latest_version = version.version
                await db.flush()
            slug = package_id.replace(".", "-").replace("_", "-")
            listing = (await db.execute(select(MarketplaceListing).where(
                MarketplaceListing.marketplace_id == marketplace.id,
                MarketplaceListing.slug == slug))).scalar_one_or_none()
            if listing is None:
                listing = MarketplaceListing(
                    marketplace_id=marketplace.id, package_id=pkg.id,
                    publisher_id=publisher.id, slug=slug,
                    title=manifest["package"]["name"],
                    short_description=manifest.get("description", "")[:500],
                    full_description=manifest.get("description", ""),
                    category=(manifest.get("categories") or ["AI & Agents"])[0],
                    license=manifest.get("license", "Apache-2.0"),
                    pricing_model="FREE", trust_level="CORE",
                    security_status=report["risk"],
                    published_version_id=version.id,
                    published_version=version.version,
                    status=ListingStatus.PUBLISHED,
                    badges={"official": True, "official_reason": "seeded official sample"})
                db.add(listing)
                await db.flush()
                db.add(MarketplaceListingVersion(
                    listing_id=listing.id, version_id=version.id,
                    version=version.version,
                    changelog={"notes": "Official sample release."},
                    is_current=True))
                await db.flush()
                print(f"listed {slug} v{version.version}")
            else:
                print(f"exists {slug}")
        await db.commit()
    await engine.dispose()
    print("marketplace seed complete (dev data only)")


if __name__ == "__main__":
    asyncio.run(main())
