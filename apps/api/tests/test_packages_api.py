"""MP22 integration tests: package versioning, install, update, rollback,
idempotency, revocation and tenant scoping at the service level.

Requires a database (CI postgres). Uses the shared conftest fixtures.
"""

from __future__ import annotations

import copy

import pytest
from sqlalchemy import select

from openagent.db.models.organization import Organization
from openagent.db.models.package import (
    InstallationResource,
    PackageInstallation,
    PackageResource,
    PackageVersion,
    PackageVersionStatus,
    ReusablePackage,
)
from openagent.db.models.user import User
from openagent.packages import installer
from openagent.packages.samples import research_workforce
from openagent.packages.types import InstallationStatus


async def _make_published_version(db, org: Organization, user: User,
                                  manifest: dict | None = None,
                                  version: str = "1.0.0"):
    from openagent.packages.manifest import parse_manifest
    from openagent.packages.signing import content_hash

    raw = copy.deepcopy(manifest or research_workforce())
    raw["package"]["version"] = version
    canonical = parse_manifest(raw).model_dump()
    package_slug = raw["package"]["id"]
    pkg = (await db.execute(select(ReusablePackage).where(
        ReusablePackage.organization_id == org.id,
        ReusablePackage.slug == package_slug))).scalar_one_or_none()
    if pkg is None:
        pkg = ReusablePackage(
            organization_id=org.id, slug=package_slug,
            name=raw["package"]["name"], description=raw.get("description", ""),
            package_type=raw["package"]["type"], latest_version=version)
        db.add(pkg)
        await db.flush()
    row = PackageVersion(
        package_id=pkg.id, version=version,
        status=PackageVersionStatus.PUBLISHED, manifest=canonical,
        content_hash=content_hash(canonical), risk="LOW",
        created_by=user.id)
    db.add(row)
    await db.flush()
    for resource in canonical.get("resources", []):
        db.add(PackageResource(
            version_id=row.id, kind=resource["kind"], slug=resource["slug"],
            name=resource["name"], payload=resource["payload"]))
    pkg.latest_version = version
    await db.commit()
    await db.refresh(row)
    return pkg, row


class TestInstallerFlow:
    async def test_preview_then_install(self, db_session, org_a, user_a):
        _, version = await _make_published_version(db_session, org_a, user_a)
        preview = await installer.preview_install(
            db_session, organization_id=org_a.id, version_id=version.id,
            values={"topic": "AI safety", "depth": "quick"})
        assert preview["can_install"] is True
        assert preview["estimated_changes"]["resources"] > 0
        assert preview["graph"]["nodes"]

        installation = await installer.install(
            db_session, organization_id=org_a.id, version_id=version.id,
            installed_by=user_a.id,
            values={"topic": "AI safety", "depth": "quick"},
            idempotency_key="test-install-1")
        assert installation.status == InstallationStatus.INSTALLED
        resources = (await db_session.execute(select(InstallationResource).where(
            InstallationResource.installation_id == installation.id))).scalars().all()
        assert len(resources) > 0
        kinds = {r.local_ref_type for r in resources}
        assert "agent" in kinds  # real agent rows materialized

    async def test_install_requires_configuration(self, db_session, org_a, user_a):
        _, version = await _make_published_version(db_session, org_a, user_a)
        installation = await installer.install(
            db_session, organization_id=org_a.id, version_id=version.id,
            installed_by=user_a.id, values={},
            idempotency_key="test-install-needs-config")
        assert installation.status == InstallationStatus.AWAITING_CONFIGURATION
        assert installation.error

    async def test_install_idempotent(self, db_session, org_a, user_a):
        _, version = await _make_published_version(db_session, org_a, user_a)
        first = await installer.install(
            db_session, organization_id=org_a.id, version_id=version.id,
            installed_by=user_a.id,
            values={"topic": "x", "depth": "quick"},
            idempotency_key="test-idem-1")
        second = await installer.install(
            db_session, organization_id=org_a.id, version_id=version.id,
            installed_by=user_a.id,
            values={"topic": "x", "depth": "quick"},
            idempotency_key="test-idem-1")
        assert first.id == second.id

    async def test_revoked_cannot_install(self, db_session, org_a, user_a):
        _, version = await _make_published_version(db_session, org_a, user_a)
        version.status = PackageVersionStatus.REVOKED
        await db_session.commit()
        with pytest.raises(installer.InstallationError) as excinfo:
            await installer.install(
                db_session, organization_id=org_a.id, version_id=version.id,
                installed_by=user_a.id, values={"topic": "x", "depth": "quick"},
                idempotency_key="test-revoked-1")
        assert excinfo.value.code == "REVOKED"

    async def test_update_and_rollback(self, db_session, org_a, user_a):
        pkg, v1 = await _make_published_version(db_session, org_a, user_a,
                                                version="1.0.0")
        installation = await installer.install(
            db_session, organization_id=org_a.id, version_id=v1.id,
            installed_by=user_a.id,
            values={"topic": "x", "depth": "quick"},
            idempotency_key="test-update-1")
        assert installation.status == InstallationStatus.INSTALLED

        raw = research_workforce()
        raw["package"]["id"] = pkg.slug
        _, v2 = await _make_published_version(db_session, org_a, user_a,
                                              manifest=raw, version="1.1.0")
        plan = await installer.plan_update(
            db_session, installation_id=installation.id,
            to_version_id=v2.id, organization_id=org_a.id)
        assert plan.impact["affected_count"] > 0

        updated = await installer.apply_update(
            db_session, installation_id=installation.id,
            organization_id=org_a.id, approved_by=user_a.id)
        assert updated.status == InstallationStatus.INSTALLED
        assert updated.version_id == v2.id
        assert updated.previous_version_id == v1.id

        rolled = await installer.rollback(
            db_session, installation_id=installation.id,
            organization_id=org_a.id, actor=user_a.id)
        assert rolled.version_id == v1.id

        # Published v1 manifest untouched by update/rollback churn.
        check = await db_session.get(PackageVersion, v1.id)
        assert check is not None
        assert check.manifest["package"]["version"] == "1.0.0"

    async def test_cross_tenant_installation_isolated(self, db_session, org_a,
                                                     org_b, user_a):
        _, version = await _make_published_version(db_session, org_a, user_a)
        installation = await installer.install(
            db_session, organization_id=org_a.id, version_id=version.id,
            installed_by=user_a.id,
            values={"topic": "x", "depth": "quick"},
            idempotency_key="test-tenant-1")
        visible = (await db_session.execute(select(PackageInstallation).where(
            PackageInstallation.organization_id == org_b.id,
            PackageInstallation.id == installation.id))).scalar_one_or_none()
        assert visible is None
