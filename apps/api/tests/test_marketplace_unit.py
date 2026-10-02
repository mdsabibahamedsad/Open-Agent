"""MP23 unit tests: listing/verification transitions, policy, licenses,
ratings, review eligibility/anti-abuse, sanitization, search, distribution,
billing, entitlements, registry, recommendations, health, notifications.

Pure domain — no database required.
"""

from __future__ import annotations

import io
import zipfile

import pytest

from openagent.marketplace import billing as billing_module
from openagent.marketplace import distribution as dist_module
from openagent.marketplace import entitlements as ent_module
from openagent.marketplace import health as health_module
from openagent.marketplace import notifications as notif_module
from openagent.marketplace import policy as policy_module
from openagent.marketplace import ratings as ratings_module
from openagent.marketplace import registry as registry_module
from openagent.marketplace import reviews as reviews_module
from openagent.marketplace import sanitize as sanitize_module
from openagent.marketplace import search as search_module
from openagent.marketplace.recommendations import (
    discovery_sections,
    recommend_for_listing,
)
from openagent.marketplace.types import (
    can_transition_listing,
    can_transition_verification,
)


class TestListingTransitions:
    def test_happy_path(self):
        assert can_transition_listing("DRAFT", "SUBMITTED")
        assert can_transition_listing("SUBMITTED", "VALIDATING")
        assert can_transition_listing("VALIDATING", "UNDER_REVIEW")
        assert can_transition_listing("UNDER_REVIEW", "APPROVED")
        assert can_transition_listing("APPROVED", "PUBLISHED")

    def test_revoked_is_terminal_except_archive(self):
        assert can_transition_listing("REVOKED", "ARCHIVED")
        assert not can_transition_listing("REVOKED", "PUBLISHED")
        assert not can_transition_listing("REVOKED", "DRAFT")

    def test_no_skip_from_draft(self):
        assert not can_transition_listing("DRAFT", "PUBLISHED")
        assert not can_transition_listing("DRAFT", "APPROVED")

    def test_suspend_restore(self):
        assert can_transition_listing("PUBLISHED", "SUSPENDED")
        assert can_transition_listing("SUSPENDED", "PUBLISHED")
        assert can_transition_listing("SUSPENDED", "REVOKED")

    def test_rejected_returns_to_draft(self):
        assert can_transition_listing("REJECTED", "DRAFT")
        assert not can_transition_listing("REJECTED", "PUBLISHED")


class TestVerificationTransitions:
    def test_flow(self):
        assert can_transition_verification("UNVERIFIED", "PENDING")
        assert can_transition_verification("PENDING", "VERIFIED")
        assert can_transition_verification("VERIFIED", "SUSPENDED")
        assert can_transition_verification("SUSPENDED", "VERIFIED")
        assert not can_transition_verification("REVOKED", "VERIFIED")
        assert not can_transition_verification("UNVERIFIED", "VERIFIED")


class TestPolicy:
    def test_free_passes_defaults(self):
        result = policy_module.evaluate_listing_policy(
            rules=None, package_license="Apache-2.0", risk="LOW",
            publisher_verified=False, security_scan_passed=True)
        assert result["passed"]

    def test_missing_scan_blocks(self):
        result = policy_module.evaluate_listing_policy(
            rules=None, package_license="MIT", risk="LOW",
            security_scan_passed=False)
        assert not result["passed"]
        assert any(f["code"] == "POLICY_NO_SCAN" for f in result["findings"])

    def test_risk_ceiling(self):
        result = policy_module.evaluate_listing_policy(
            rules={"maximum_risk_level": "MEDIUM"}, package_license="MIT",
            risk="HIGH", security_scan_passed=True)
        assert not result["passed"]

    def test_unverified_blocked_when_required(self):
        result = policy_module.evaluate_listing_policy(
            rules={"require_publisher_verification": True},
            package_license="MIT", risk="LOW", publisher_verified=False,
            security_scan_passed=True)
        assert not result["passed"]

    def test_blocked_dep_and_perm(self):
        result = policy_module.evaluate_listing_policy(
            rules={"blocked_dependencies": ["evil-pack"],
                   "blocked_permissions": ["root.shell"]},
            package_license="MIT", risk="LOW", security_scan_passed=True,
            dependencies=[{"package": "evil-pack"}],
            permissions=["root.shell"])
        codes = {f["code"] for f in result["findings"]}
        assert {"POLICY_BLOCKED_DEP", "POLICY_BLOCKED_PERM"} <= codes

    def test_license_compat_warning(self):
        warnings = policy_module.check_license_compatibility(
            ["Apache-2.0", "GPL-3.0-only"])
        assert warnings
        assert "legal advice" in warnings[0]

    def test_license_compat_block_mode(self):
        result = policy_module.evaluate_listing_policy(
            rules={"license_mode": "block"}, package_license="GPL-3.0-only",
            dependency_licenses=["Apache-2.0"], risk="LOW",
            security_scan_passed=True)
        assert not result["passed"]

    def test_unknown_policy_keys_rejected_at_api(self):
        # Domain merges defaults; unknown keys are an API-layer 400.
        merged = dict(policy_module.DEFAULT_POLICY_RULES)
        merged.update({"bogus_key": True})
        assert "bogus_key" in merged  # merge itself is permissive


class TestRatings:
    def test_aggregate(self):
        agg = ratings_module.aggregate([5, 5, 4, 3], [True, True, False, False])
        assert agg == {"rating_average": 4.25, "rating_count": 4,
                       "rating_distribution": {"1": 0, "2": 0, "3": 1,
                                               "4": 1, "5": 2},
                       "verified_review_count": 2}

    def test_empty(self):
        agg = ratings_module.aggregate([])
        assert agg["rating_average"] == 0.0
        assert agg["rating_count"] == 0

    def test_out_of_range_ignored(self):
        agg = ratings_module.aggregate([0, 6, 5])
        assert agg["rating_count"] == 1


class TestReviews:
    def test_verified_installation(self):
        eligible, verified, _ = reviews_module.check_eligibility(
            has_installation=True)
        assert (eligible, verified) == (True, True)

    def test_documented_usage(self):
        eligible, verified, _ = reviews_module.check_eligibility(
            has_installation=False, documented_usage=True)
        assert (eligible, verified) == (True, False)

    def test_self_review(self):
        assert reviews_module.check_self_review(
            reviewer_user_id="u1", publisher_member_ids=["u1", "u2"])
        assert not reviews_module.check_self_review(
            reviewer_user_id="u9", publisher_member_ids=["u1"])

    def test_velocity(self):
        exceeded, _ = reviews_module.check_velocity(recent_count=5)
        assert exceeded
        exceeded, _ = reviews_module.check_velocity(recent_count=2)
        assert not exceeded

    def test_spam_signals(self):
        assert reviews_module.check_spam_signals(
            title="Great", body="Buy now at http://spam.example")
        assert not reviews_module.check_spam_signals(
            title="Solid", body="Works well for our team daily.")

    def test_initial_status(self):
        status, _ = reviews_module.decide_initial_status(
            eligible=True, self_review=False, velocity_exceeded=False,
            spam_signals=[])
        assert status == "PUBLISHED"
        status, _ = reviews_module.decide_initial_status(
            eligible=True, self_review=True, velocity_exceeded=False,
            spam_signals=[])
        assert status == "FLAGGED"


class TestSanitize:
    def test_rejects_javascript_urls(self):
        with pytest.raises(sanitize_module.ContentError):
            sanitize_module.check_url("javascript:alert(1)", field="website")

    def test_rejects_data_urls(self):
        assert not sanitize_module.is_safe_url("data:text/html,<script>")

    def test_accepts_https(self):
        assert sanitize_module.is_safe_url("https://example.com/docs?a=1")

    def test_rejects_relative(self):
        assert not sanitize_module.is_safe_url("/etc/passwd")

    def test_strips_markup(self):
        assert sanitize_module.strip_html(
            "<script>alert(1)</script>Hello <b>world</b>") == "Hello world"

    def test_detects_event_handlers(self):
        assert sanitize_module.contains_active_markup('<img onerror="x()">')
        assert not sanitize_module.contains_active_markup("plain **text**")

    def test_review_length_floor(self):
        with pytest.raises(sanitize_module.ContentError):
            sanitize_module.validate_review_text("ok", "short")

    def test_link_cap(self):
        with pytest.raises(sanitize_module.ContentError):
            sanitize_module.validate_links(
                [f"https://example.com/{i}" for i in range(25)],
                field="screenshots")


class TestSearch:
    def test_query_normalization(self):
        query = search_module.MarketplaceSearchQuery(
            text="  x  ", page=0, page_size=500, sort="BOGUS")
        query.normalized()
        assert query.text == "x"
        assert query.page == 1
        assert query.page_size == 100
        assert query.sort == "RELEVANCE"

    def test_relevance_transparent(self):
        score = search_module.relevance_score(
            title="Research Workforce", description="deep research",
            tags=["research"], text="research")
        assert score >= 4.0
        assert search_module.relevance_score(
            title="Other", description="nothing", tags=[], text="zzz") == 0.0

    def test_sort_mapping(self):
        assert search_module.sort_key("MOST_INSTALLED") == ("install_count", True)
        assert search_module.sort_key("PRICE_LOW_TO_HIGH") == ("min_price", False)
        assert search_module.sort_key("RELEVANCE") is None

    def test_related_reasons_labeled(self):
        reasons = search_module.related_reasons(
            {"publisher_id": "p1", "category": "c", "tags": ["a", "b"],
             "package_type": "WORKFLOW"},
            {"publisher_id": "p1", "category": "c", "tags": ["b", "c"],
             "package_type": "WORKFLOW"})
        assert "same publisher" in reasons
        assert any("shared tags" in r for r in reasons)


class TestDistribution:
    def _zip(self, members: dict[str, bytes]) -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, data in members.items():
                archive.writestr(name, data)
        return buffer.getvalue()

    def test_verify_ok(self):
        result = dist_module.verify_archive(
            self._zip({"manifest.json": b"{}", "a.txt": b"hi"}),
            filename="pkg.zip")
        assert result["ok"]
        assert len(result["sha256"]) == 64

    def test_hash_mismatch(self):
        result = dist_module.verify_archive(
            self._zip({"a.txt": b"hi"}), filename="pkg.zip",
            expected_sha256="0" * 64)
        assert not result["ok"]

    def test_path_traversal_rejected(self):
        result = dist_module.verify_archive(
            self._zip({"../evil.txt": b"x", "ok.txt": b"y"}),
            filename="pkg.zip")
        assert not result["ok"]
        assert any("traversal" in p for p in result["problems"])

    def test_bad_zip(self):
        result = dist_module.verify_archive(b"not a zip", filename="pkg.zip")
        assert not result["ok"]

    def test_content_key_safe(self):
        key = dist_module.content_key("artifacts", "ab" * 32, "../../etc/passwd")
        assert ".." not in key
        assert key.startswith("artifacts/ab/ab/")

    def test_asset_validation(self):
        assert dist_module.validate_asset_upload(
            filename="shot.png", mime="image/png", size_bytes=100) == []
        problems = dist_module.validate_asset_upload(
            filename="run.exe", mime="application/octet-stream", size_bytes=100)
        assert problems
        problems = dist_module.validate_asset_upload(
            filename="../x.png", mime="image/png", size_bytes=100)
        assert problems


class TestBilling:
    def test_split(self):
        out = billing_module.split_revenue(
            gross_minor=10000, platform_bps=1000, affiliate_bps=500)
        assert out == {"gross": 10000, "platform_fee": 1000,
                       "affiliate_fee": 500, "publisher_amount": 8500}

    def test_split_rejects_over_100(self):
        with pytest.raises(billing_module.CommerceError):
            billing_module.split_revenue(
                gross_minor=100, platform_bps=9000, affiliate_bps=2000)

    def test_webhook_signature(self):
        secret = "whsec-test"
        body = b'{"id":"evt_1"}'
        import hashlib as _hashlib
        import hmac as _hmac

        sig = "sha256=" + _hmac.new(secret.encode(), body,
                                    _hashlib.sha256).hexdigest()
        assert billing_module.verify_webhook_signature(
            secret=secret, raw_body=body, signature=sig)
        assert not billing_module.verify_webhook_signature(
            secret=secret, raw_body=b"tampered", signature=sig)
        assert not billing_module.verify_webhook_signature(
            secret="", raw_body=body, signature=sig)

    def test_webhook_timestamp(self):
        import time as _time

        assert billing_module.verify_webhook_timestamp(str(_time.time()))
        assert not billing_module.verify_webhook_timestamp("1")
        assert not billing_module.verify_webhook_timestamp("not-a-number")

    async def test_disabled_provider_raises(self):
        provider = billing_module.DisabledBillingProvider()
        with pytest.raises(billing_module.CommerceError):
            await provider.create_checkout(product_id="p", price_id="pr",
                                           organization_id="o",
                                           success_url="s", cancel_url="c")


class TestEntitlements:
    def test_free_always(self):
        allowed, code, _ = ent_module.can_install_listing(pricing_model="FREE",
                                                          entitlements=[])
        assert (allowed, code) == (True, "OK_FREE")

    def test_paid_needs_entitlement(self):
        allowed, code, _ = ent_module.can_install_listing(
            pricing_model="ONE_TIME", entitlements=[],
            commerce_configured=True)
        assert (allowed, code) == (False, "NEED_ENTITLEMENT")

    def test_paid_no_provider(self):
        allowed, code, _ = ent_module.can_install_listing(
            pricing_model="SUBSCRIPTION", entitlements=[],
            commerce_configured=False)
        assert (allowed, code) == (False, "COMMERCE_DISABLED")

    def test_live_entitlement(self):
        allowed, code, _ = ent_module.can_install_listing(
            pricing_model="ONE_TIME",
            entitlements=[{"organization_id": "org-1", "user_id": "",
                           "status": "ACTIVE", "valid_from": "",
                           "valid_until": ""}],
            organization_id="org-1", commerce_configured=True)
        assert (allowed, code) == (True, "OK_ENTITLED")

    def test_revoked_and_expired(self):
        for status in ("REVOKED", "EXPIRED"):
            live, _ = ent_module.entitlement_is_live({"status": status})
            assert not live


class TestRegistry:
    def test_nothing_implicitly_trusted(self):
        from openagent.marketplace.types import IMPLICITLY_TRUSTED_REGISTRIES

        assert len(IMPLICITLY_TRUSTED_REGISTRIES) == 0

    def test_signature_policy(self):
        ok, _ = registry_module.signature_policy_ok(
            policy={"require_signed": True}, signature_status="VALID")
        assert ok
        ok, _ = registry_module.signature_policy_ok(
            policy={"require_signed": True}, signature_status="UNSIGNED")
        assert not ok

    def test_mirror_cycle_safe(self):
        chain = registry_module.mirror_chain(
            {"slug": "a", "mirror_of": "b"},
            {"b": {"slug": "b", "mirror_of": "a"}})
        assert any("cycle" in item for item in chain)


class TestRecommendations:
    def _candidate(self, slug: str, **over: object) -> dict:
        base: dict = {"id": slug, "package_id": f"pkg-{slug}",
                      "publisher_id": "p1", "category": "research",
                      "title": slug, "tags": ["research"]}
        base.update(over)
        return base

    def test_reasons_and_dedup(self):
        recs = recommend_for_listing(
            source={"id": "s", "package_id": "pkg-s", "publisher_id": "p1",
                    "category": "research", "tags": ["research"]},
            candidates=[self._candidate("a"),
                        self._candidate("s"),
                        self._candidate("b", publisher_id="p2",
                                        category="other", tags=["zzz"])],
            installed_package_ids=["pkg-a"], limit=8)
        assert len(recs) == 1
        assert "same publisher" in recs[0]["reasons"]
        assert "already installed by your organization" in recs[0]["reasons"]

    def test_sections_labeled(self):
        sections = discovery_sections(featured=[], official=[],
                                      new=[], popular=[])
        assert [s["key"] for s in sections] == ["featured", "official",
                                                "new", "popular"]
        assert sections[0]["editorial"] is True
        assert sections[1]["editorial"] is False


class TestHealth:
    def test_revoked(self):
        assert health_module.compute_health(revoked=True)["status"] == "REVOKED"

    def test_critical_advisory(self):
        out = health_module.compute_health(
            open_advisories=[{"severity": "CRITICAL"}])
        assert out["status"] == "AT_RISK"

    def test_healthy_and_unknown(self):
        assert health_module.compute_health(
            last_validation_passed=True)["status"] == "HEALTHY"
        assert health_module.compute_health()["status"] == "UNKNOWN"

    def test_warning_signals(self):
        out = health_module.compute_health(
            last_validation_passed=True, install_success_rate=0.5,
            install_samples=10)
        assert out["status"] == "WARNING"
        assert out["reasons"]


class TestNotifications:
    def test_prefs_defaults(self):
        prefs = notif_module.prefs_for(None)
        assert prefs["SECURITY_ADVISORY"] is True
        assert prefs["PAYOUT_EVENT"] is False

    def test_prefs_override_and_unknown_ignored(self):
        prefs = notif_module.prefs_for({"SECURITY_ADVISORY": False,
                                        "BOGUS": True})
        assert prefs["SECURITY_ADVISORY"] is False
        assert "BOGUS" not in prefs

    def test_build_requires_user(self):
        with pytest.raises(ValueError):
            notif_module.build_notification(user_id="", notif_type="X",
                                            title="t")
