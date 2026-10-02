"""MP24 unit tests: money, states, entitlements, quotas, ledger, registry.

Pure-domain (no DB, no network). Runs in CI with postgres and locally
with ``pytest --noconftest`` + stdlib/pydantic only.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
from datetime import datetime, timedelta, timezone

import pytest

from openagent.commerce import entitlements as ent
from openagent.commerce import ledger as ledger_lib
from openagent.commerce import money
from openagent.commerce import registry as registry_lib
from openagent.commerce import usage as usage_lib
from openagent.commerce import webhooks as webhook_lib
from openagent.commerce.providers import (
    DisabledBillingProvider,
    MockBillingProvider,
    get_billing_provider,
)
from openagent.commerce.types import (
    can_transition_checkout,
    can_transition_payout,
    can_transition_subscription,
)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) \
        if False else asyncio.run(coro)


# --------------------------------------------------------------------------
# Money
# --------------------------------------------------------------------------

class TestMoney:
    def test_parse_usd(self):
        assert money.parse_amount("9.99", "USD") == 999
        assert money.parse_amount("0.00", "USD") == 0

    def test_parse_jpy_zero_decimal(self):
        assert money.parse_amount("500", "JPY") == 500
        with pytest.raises(Exception):
            money.parse_amount("500.5", "JPY")

    def test_rejects_float_precision(self):
        with pytest.raises(Exception):
            money.parse_amount("9.999", "USD")

    def test_rejects_negative(self):
        with pytest.raises(Exception):
            money.parse_amount("-1.00", "USD")

    def test_rejects_bad_currency(self):
        with pytest.raises(Exception):
            money.parse_amount("1.00", "US")

    def test_format_roundtrip(self):
        assert money.format_amount(999, "USD") == "9.99"
        assert money.format_amount(500, "JPY") == "500"

    def test_never_float(self):
        with pytest.raises(Exception):
            money.add(999, 9.99)  # type: ignore[arg-type]

    def test_percent_floor(self):
        assert money.percent_of(999, 1000) == 99  # 10% floored


# --------------------------------------------------------------------------
# State machines
# --------------------------------------------------------------------------

class TestTransitions:
    def test_checkout_happy(self):
        assert can_transition_checkout("CREATED", "PENDING")
        assert can_transition_checkout("PENDING", "COMPLETED")
        assert not can_transition_checkout("COMPLETED", "PENDING")
        assert not can_transition_checkout("CREATED", "COMPLETED")

    def test_subscription_flows(self):
        assert can_transition_subscription("ACTIVE", "PAST_DUE")
        assert can_transition_subscription("PAST_DUE", "ACTIVE")
        assert can_transition_subscription("ACTIVE", "CANCELLED")
        assert not can_transition_subscription("CANCELLED", "ACTIVE")

    def test_payout_holds(self):
        assert can_transition_payout("PENDING", "ELIGIBLE")
        assert can_transition_payout("ELIGIBLE", "HELD")
        assert can_transition_payout("HELD", "ELIGIBLE")
        assert can_transition_payout("PROCESSING", "PAID")
        assert not can_transition_payout("PAID", "ELIGIBLE")


# --------------------------------------------------------------------------
# Entitlements (commercial only)
# --------------------------------------------------------------------------

def _ent(**kw):
    base = {"status": "ACTIVE", "organization_id": "org-1",
            "features": ["package.install"]}
    base.update(kw)
    return base


class TestEntitlements:
    def test_live(self):
        ok, _ = ent.entitlement_is_live(_ent())
        assert ok

    def test_revoked_not_live(self):
        ok, _ = ent.entitlement_is_live(_ent(status="REVOKED"))
        assert not ok

    def test_expired_window(self):
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        ok, _ = ent.entitlement_is_live(_ent(valid_until=past))
        assert not ok

    def test_has_access_feature_match(self):
        ok, _ = ent.has_access(entitlements=[_ent()], feature="package.install",
                               organization_id="org-1")
        assert ok

    def test_has_access_wrong_feature(self):
        ok, _ = ent.has_access(entitlements=[_ent()], feature="product.updates",
                               organization_id="org-1")
        assert not ok

    def test_has_access_wrong_org(self):
        ok, _ = ent.has_access(entitlements=[_ent()], feature="package.install",
                               organization_id="org-2")
        assert not ok

    def test_quantity_exhausted(self):
        ok, _ = ent.has_access(
            entitlements=[_ent(quantity=2, used=2)], feature="package.install",
            organization_id="org-1")
        assert not ok

    def test_can_install_free(self):
        allowed, code, _ = ent.can_install(
            pricing_model="FREE", entitlements=[], commerce_configured=False)
        assert allowed and code == "OK_FREE"

    def test_can_install_paid_needs_provider(self):
        allowed, code, _ = ent.can_install(
            pricing_model="ONE_TIME", entitlements=[], commerce_configured=False)
        assert not allowed and code == "COMMERCE_DISABLED"

    def test_can_install_paid_with_entitlement(self):
        allowed, code, _ = ent.can_install(
            pricing_model="SUBSCRIPTION", entitlements=[_ent()],
            organization_id="org-1", commerce_configured=True)
        assert allowed and code == "OK_ENTITLED"


# --------------------------------------------------------------------------
# Usage / quotas / coupons
# --------------------------------------------------------------------------

class TestUsage:
    def test_aggregations(self):
        records = [{"quantity": 2, "dedup_key": "a"},
                   {"quantity": 3, "dedup_key": "b"}]
        assert usage_lib.aggregate(records, aggregation="SUM") == 5
        assert usage_lib.aggregate(records, aggregation="COUNT") == 2
        assert usage_lib.aggregate(records, aggregation="MAX") == 3
        assert usage_lib.aggregate(
            [{"quantity": 1, "dedup_key": "a"},
             {"quantity": 9, "dedup_key": "a"}], aggregation="UNIQUE") == 1

    def test_quota(self):
        allowed, _, remaining = usage_lib.quota_decision(
            limit=10, used=9, requested=1)
        assert allowed and remaining == 0
        allowed, _, _ = usage_lib.quota_decision(
            limit=10, used=9, requested=2)
        assert not allowed

    def test_quota_unlimited(self):
        allowed, _, _ = usage_lib.quota_decision(
            limit=None, used=10**9, requested=1)
        assert allowed

    def test_overage(self):
        assert usage_lib.overage(included=100, used=130) == 30
        assert usage_lib.overage(included=100, used=80) == 0

    def test_coupon_percent(self):
        assert usage_lib.coupon_discount(
            coupon={"kind": "PERCENT", "percent_bps": 2000},
            gross_minor=1000) == 200

    def test_coupon_capped_at_gross(self):
        assert usage_lib.coupon_discount(
            coupon={"kind": "FIXED", "amount_minor": 5000},
            gross_minor=1000) == 1000

    def test_coupon_validation(self):
        now = datetime.now(timezone.utc).isoformat()
        ok, _ = usage_lib.validate_coupon(
            coupon={"active": True, "max_per_customer": 1},
            now_iso=now, customer_id="c1", prior_redemptions=0,
            customer_redemptions=0)
        assert ok
        ok, reason = usage_lib.validate_coupon(
            coupon={"active": True, "max_per_customer": 1},
            now_iso=now, customer_id="c1", prior_redemptions=0,
            customer_redemptions=1)
        assert not ok and "redeemed" in reason


# --------------------------------------------------------------------------
# Ledger / fees / payouts
# --------------------------------------------------------------------------

class TestLedger:
    def test_split(self):
        out = ledger_lib.split_revenue(gross_minor=1000, platform_bps=1000)
        assert out == {"gross": 1000, "discount": 0, "refund": 0, "tax": 0,
                       "platform_fee": 100, "creator_amount": 900}

    def test_split_with_discount_refund(self):
        out = ledger_lib.split_revenue(gross_minor=1000, discount_minor=100,
                                       refund_minor=100, platform_bps=0)
        assert out["creator_amount"] == 800

    def test_split_rejects_overdraw(self):
        with pytest.raises(Exception):
            ledger_lib.split_revenue(gross_minor=100, discount_minor=200)

    def test_ledger_balance(self):
        entries = [{"type": "CREDIT", "amount_minor": 900, "currency": "USD"},
                   {"type": "FEE", "amount_minor": 100, "currency": "USD"},
                   {"type": "PAYOUT", "amount_minor": 400, "currency": "USD"}]
        assert ledger_lib.ledger_balance(entries, currency="USD") == 400

    def test_ledger_rejects_unknown(self):
        with pytest.raises(Exception):
            ledger_lib.ledger_balance([{"type": "???", "amount_minor": 1}])

    def test_fee_resolution_specificity(self):
        policies = [
            {"id": "default", "rate_bps": 0},
            {"id": "sub", "product_type": "SUBSCRIPTION", "rate_bps": 500},
        ]
        resolved = ledger_lib.resolve_fee(
            policies=policies, product_type="SUBSCRIPTION")
        assert resolved["platform_bps"] == 500
        resolved = ledger_lib.resolve_fee(policies=policies,
                                          product_type="PACKAGE")
        assert resolved["platform_bps"] == 0

    def test_payout_eligibility(self):
        ok, _ = ledger_lib.payout_eligibility(
            balance_minor=5000, minimum_minor=1000,
            publisher_verified=True, require_verification=True,
            open_disputes=0)
        assert ok
        ok, reason = ledger_lib.payout_eligibility(
            balance_minor=500, minimum_minor=1000,
            publisher_verified=True, require_verification=True,
            open_disputes=0)
        assert not ok and "minimum" in reason
        ok, _ = ledger_lib.payout_eligibility(
            balance_minor=5000, minimum_minor=1000,
            publisher_verified=True, require_verification=True,
            open_disputes=1)
        assert not ok


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------

class TestRegistry:
    def test_rejects_plaintext_secret(self):
        problems = registry_lib.validate_registry_config(
            {"type": "PRIVATE", "authentication": "API_KEY",
             "api_key": "sekret"})
        assert any("plaintext" in p for p in problems)

    def test_requires_credential_ref(self):
        problems = registry_lib.validate_registry_config(
            {"type": "PRIVATE", "authentication": "API_KEY"})
        assert any("credential_ref" in p for p in problems)

    def test_public_ok(self):
        assert registry_lib.validate_registry_config(
            {"type": "PUBLIC", "authentication": "PUBLIC"}) == []

    def test_trust_order(self):
        assert registry_lib.trust_meets("VERIFIED", "COMMUNITY")
        assert not registry_lib.trust_meets("COMMUNITY", "VERIFIED")

    def test_signature_policy(self):
        ok, _ = registry_lib.signature_policy_ok(
            policy={"require_signed": True}, signature_status="VALID")
        assert ok
        ok, _ = registry_lib.signature_policy_ok(
            policy={"require_signed": True}, signature_status="MISSING")
        assert not ok

    def test_integrity(self):
        artifact = b"hello-package"
        digest = hashlib.sha256(artifact).hexdigest()
        assert registry_lib.verify_artifact_sha256(artifact, digest)
        assert not registry_lib.verify_artifact_sha256(artifact, "0" * 64)

    def test_mirror_cycle_safe(self):
        by_slug = {"a": {"slug": "a", "mirror_of": "b"},
                   "b": {"slug": "b", "mirror_of": "a"}}
        chain = registry_lib.mirror_chain({"slug": "a", "mirror_of": "b"},
                                          by_slug)
        assert any("cycle" in c for c in chain)

    def test_local_provider_offline(self):
        provider = registry_lib.LocalRegistryProvider(
            {"demo/pkg": {"versions": {"1.0.0": {"name": "demo/pkg"}},
                          "artifacts": {"1.0.0": b"bytes"}}})
        assert _run(provider.get_package(name="demo/pkg"))["name"] == "demo/pkg"
        assert _run(provider.download_artifact(
            name="demo/pkg", version="1.0.0")) == b"bytes"


# --------------------------------------------------------------------------
# Webhooks
# --------------------------------------------------------------------------

class TestWebhooks:
    def test_signature_roundtrip(self):
        secret = "s3cret"
        body = b'{"event_id":"e1"}'
        sig = "sha256=" + hmac.new(secret.encode(), body,
                                   hashlib.sha256).hexdigest()
        assert webhook_lib.verify_signature(secret=secret, raw_body=body,
                                            signature=sig)
        assert not webhook_lib.verify_signature(
            secret=secret, raw_body=body, signature="sha256=" + "0" * 64)

    def test_empty_secret_never_verifies(self):
        assert not webhook_lib.verify_signature(secret="", raw_body=b"x",
                                                signature="abc")

    def test_timestamp_window(self):
        import time
        assert webhook_lib.verify_timestamp(time.time(), max_skew_seconds=300)
        assert not webhook_lib.verify_timestamp(time.time() - 3600,
                                                max_skew_seconds=300)

    def test_idempotency_key(self):
        assert webhook_lib.idempotency_key(
            provider="mock", event_id="e1") == "mock:e1"


# --------------------------------------------------------------------------
# Providers
# --------------------------------------------------------------------------

class TestProviders:
    def test_disabled_raises(self):
        provider = DisabledBillingProvider()
        with pytest.raises(Exception) as exc:
            _run(provider.create_checkout(product_id="p", price_id="pr",
                                          organization_id="o",
                                          success_url="s", cancel_url="c"))
        assert "not configured" in str(exc.value)

    def test_mock_deterministic(self):
        provider = MockBillingProvider()
        first = _run(provider.create_customer(email="a@x.com",
                                              organization_id="o1"))
        second = _run(provider.create_customer(email="a@x.com",
                                               organization_id="o1"))
        assert first["provider_customer_id"] == second["provider_customer_id"]
        assert first["test_mode"] is True

    def test_mock_payment_roundtrip(self):
        provider = MockBillingProvider()
        provider.record_test_payment(reference="ch_test_1", amount_minor=999,
                                     currency="USD", product_id="prod-1")
        verified = _run(provider.verify_payment(
            transaction_reference="ch_test_1"))
        assert verified.amount_minor == 999
        with pytest.raises(Exception):
            _run(provider.verify_payment(transaction_reference="nope"))

    def test_get_provider_modes(self):
        assert get_billing_provider(mode="disabled").name == "disabled"
        assert get_billing_provider(mode="mock").name == "mock"
        with pytest.raises(Exception):
            get_billing_provider(mode="live")
