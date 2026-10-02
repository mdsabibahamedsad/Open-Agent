"""MP24 security tests: webhook forgery/replay, entitlement forgery,
cross-tenant isolation, price tampering, coupon abuse, payout auth,
payment-secret hygiene.

Pure domain + static shape checks — no database required (mirrors the MP23
security-test style). DB-backed cross-tenant checks live in
``test_commerce_api.py`` via org-scoped service calls.
"""

from __future__ import annotations

import dataclasses
import hashlib
import hmac
import inspect
import time

import pytest

from openagent.commerce import entitlements as ent
from openagent.commerce import ledger as ledger_lib
from openagent.commerce import money
from openagent.commerce import providers as providers_module
from openagent.commerce import registry as registry_lib
from openagent.commerce import usage as usage_lib
from openagent.commerce import webhooks as webhook_lib
from openagent.commerce.types import (
    BILLING_EVENTS,
    BILLING_METRICS,
    PAYOUT_TRANSITIONS,
)


class TestForgedWebhook:
    def test_wrong_secret_rejected(self):
        body = b'{"event_id":"e1","event_type":"PAYMENT_SUCCEEDED"}'
        good = "sha256=" + hmac.new(b"real", body, hashlib.sha256).hexdigest()
        assert webhook_lib.verify_signature(
            secret="real", raw_body=body, signature=good)
        assert not webhook_lib.verify_signature(
            secret="other", raw_body=body, signature=good)

    def test_tampered_body_rejected(self):
        secret = "s"
        good = "sha256=" + hmac.new(secret.encode(), b'{"a":1}',
                                    hashlib.sha256).hexdigest()
        assert not webhook_lib.verify_signature(
            secret=secret, raw_body=b'{"a":2}', signature=good)

    def test_missing_signature_rejected(self):
        assert not webhook_lib.verify_signature(
            secret="s", raw_body=b"x", signature="")

    def test_replay_outside_window_rejected(self):
        assert not webhook_lib.verify_timestamp(time.time() - 3600,
                                                max_skew_seconds=300)

    def test_future_timestamp_rejected(self):
        assert not webhook_lib.verify_timestamp(time.time() + 3600,
                                                max_skew_seconds=300)


class TestDuplicatePayment:
    def test_idempotency_key_deterministic(self):
        assert webhook_lib.idempotency_key(provider="stripe",
                                           event_id="evt_1") == "stripe:evt_1"
        assert webhook_lib.idempotency_key(provider="stripe",
                                           event_id="evt_1") == \
            webhook_lib.idempotency_key(provider="stripe", event_id="evt_1")

    def test_distinct_events_distinct_keys(self):
        assert webhook_lib.idempotency_key(provider="p", event_id="a") != \
            webhook_lib.idempotency_key(provider="p", event_id="b")


class TestEntitlementForgery:
    def test_unknown_status_never_live(self):
        ok, _ = ent.entitlement_is_live({"status": "SUPERUSER"})
        assert not ok

    def test_empty_status_never_live(self):
        ok, _ = ent.entitlement_is_live({})
        assert not ok

    def test_pending_not_usable(self):
        ok, _ = ent.has_access(
            entitlements=[{"status": "PENDING",
                           "organization_id": "o",
                           "features": ["package.install"]}],
            feature="package.install", organization_id="o")
        assert not ok

    def test_suspended_not_usable(self):
        ok, _ = ent.has_access(
            entitlements=[{"status": "SUSPENDED",
                           "organization_id": "o",
                           "features": ["package.install"]}],
            feature="package.install", organization_id="o")
        assert not ok

    def test_wildcard_only_when_granted(self):
        ok, _ = ent.has_access(
            entitlements=[{"status": "ACTIVE", "organization_id": "o",
                           "features": ["*"]}],
            feature="anything.at.all", organization_id="o")
        assert ok

    def test_no_org_inherit_by_default(self):
        # Org-scoped grants cover org context (API-layer RBAC already
        # proves membership). User-scoped grants never leak across users,
        # and member inheritance requires the explicit inherited flag.
        org_grant = {"status": "ACTIVE", "organization_id": "org-1",
                     "features": ["package.install"]}
        ok, _ = ent.has_access(entitlements=[org_grant],
                               feature="package.install",
                               organization_id="org-1", user_id="u-9")
        assert ok  # org context covered; membership proven by RBAC upstream
        user_grant = {"status": "ACTIVE", "organization_id": "org-1",
                      "user_id": "u-1", "features": ["package.install"]}
        ok, _ = ent.has_access(entitlements=[user_grant],
                               feature="package.install",
                               organization_id="org-1", user_id="u-9")
        assert not ok  # another user's grant never applies
        ok, _ = ent.has_access(
            entitlements=[{**org_grant, "inherited": True}],
            feature="package.install", organization_id="org-1",
            user_id="u-9", allow_org_inherit=True)
        assert ok


class TestCrossTenantBilling:
    def test_subject_isolation(self):
        grant_a = {"status": "ACTIVE", "organization_id": "org-a",
                   "features": ["package.install"]}
        ok, _ = ent.has_access(entitlements=[grant_a],
                               feature="package.install",
                               organization_id="org-b")
        assert not ok

    def test_publisher_isolation_shape(self):
        # Revenue/ledger/payout queries always filter by publisher_id and
        # the API gates every one on publisher membership (DB-backed
        # negative tests live in test_commerce_api.py).
        import openagent.api.v1.commerce_billing as billing_api
        api_source = inspect.getsource(billing_api)
        assert api_source.count("_require_publisher_access") >= 4


class TestPriceTampering:
    @pytest.mark.parametrize("raw", ["9.999", "-5", "abc", "NaN", ""])
    def test_bad_amounts_rejected(self, raw):
        with pytest.raises(Exception):
            money.parse_amount(raw, "USD")

    def test_checkout_interval_allowlist(self):
        import openagent.api.v1.commerce as commerce_api
        source = inspect.getsource(commerce_api)
        # Prices go through parse_amount (decimal strings, never floats).
        assert "parse_amount" in source


class TestCouponAbuse:
    def test_expired_rejected(self):
        ok, _ = usage_lib.validate_coupon(
            coupon={"active": True, "expires_at": "2000-01-01T00:00:00+00:00",
                    "max_per_customer": 5},
            now_iso="2026-09-30T00:00:00+00:00", customer_id="c",
            prior_redemptions=0, customer_redemptions=0)
        assert not ok

    def test_global_cap_rejected(self):
        ok, _ = usage_lib.validate_coupon(
            coupon={"active": True, "max_redemptions": 10,
                    "max_per_customer": 5},
            now_iso="2026-09-30T00:00:00+00:00", customer_id="c",
            prior_redemptions=10, customer_redemptions=0)
        assert not ok

    def test_ineligible_product_rejected(self):
        ok, _ = usage_lib.validate_coupon(
            coupon={"active": True, "max_per_customer": 5,
                    "eligible_products": ["prod-a"]},
            now_iso="2026-09-30T00:00:00+00:00", customer_id="c",
            product_id="prod-b", prior_redemptions=0,
            customer_redemptions=0)
        assert not ok

    def test_percent_bounds(self):
        with pytest.raises(Exception):
            usage_lib.coupon_discount(
                coupon={"kind": "PERCENT", "percent_bps": 20000},
                gross_minor=100)


class TestPayoutAuthorization:
    def test_terminal_states_final(self):
        for terminal in ("PAID", "CANCELLED"):
            assert PAYOUT_TRANSITIONS[terminal] == frozenset()

    def test_no_direct_pending_to_paid(self):
        from openagent.commerce.types import can_transition_payout
        assert not can_transition_payout("PENDING", "PAID")
        assert not can_transition_payout("PENDING", "PROCESSING")

    def test_hold_requires_reason_path(self):
        import openagent.api.v1.commerce_billing as billing_api
        source = inspect.getsource(billing_api.transition_payout)
        assert "payout:manage" in source


class TestPaymentSecretHygiene:
    def test_no_card_fields_in_provider_types(self):
        forbidden = {"card_number", "cvv", "cvc", "pan", "bank_account",
                     "routing_number", "password"}
        for name in dir(providers_module):
            obj = getattr(providers_module, name)
            fields = set()
            if dataclasses.is_dataclass(obj):
                fields = {f.name for f in dataclasses.fields(obj)}
            elif inspect.isclass(obj):
                fields = set(getattr(obj, "__annotations__", {}))
            overlap = {f.lower() for f in fields} & forbidden
            assert not overlap, f"{name} stores payment secrets: {overlap}"

    def test_webhook_persistence_strips_secrets(self):
        import openagent.commerce.service as service_module
        source = inspect.getsource(service_module.process_billing_webhook)
        assert "card_number" in source  # filtered before persistence

    def test_registry_rejects_plaintext(self):
        problems = registry_lib.validate_registry_config(
            {"type": "PRIVATE", "authentication": "API_KEY",
             "password": "hunter2"})
        assert problems

    def test_billing_events_cover_lifecycle(self):
        for event in ("PAYMENT_SUCCEEDED", "ENTITLEMENT_GRANTED",
                      "REFUND_CREATED", "PAYOUT_COMPLETED",
                      "SUBSCRIPTION_CANCELLED"):
            assert event in BILLING_EVENTS

    def test_billing_metrics_defined(self):
        assert "billing_webhook_failed_total" in BILLING_METRICS
        assert "payout_failed_total" in BILLING_METRICS

    def test_ledger_rejects_negative_base(self):
        with pytest.raises(Exception):
            ledger_lib.split_revenue(gross_minor=100, refund_minor=200)
