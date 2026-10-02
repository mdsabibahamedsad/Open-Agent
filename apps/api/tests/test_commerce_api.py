"""MP24 integration tests: checkout -> webhook -> payment -> entitlement ->
package-install gate -> usage -> revenue -> ledger -> payout.

Service-layer (no HTTP auth needed); the API router tests reuse the same
paths via ``client`` where auth fixtures exist. Requires the database
(postgres in CI, ``Base.metadata.create_all`` in conftest).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from openagent.commerce import service as svc
from openagent.commerce.config import get_commerce_settings
from openagent.commerce.providers import CommerceError
from openagent.db.models.commerce import (
    CreatorLedgerEntry,
    CreditAccount,
    FeePolicy,
    Payment,
    PromoCode,
    Promotion,
    Quota,
    UsageMeter,
)
from openagent.db.models.marketplace import (
    ListingStatus,
    Marketplace,
    MarketplaceListing,
    MarketplaceType,
    RevenueRecord,
)
from openagent.db.models.package import (
    PackageVersion,
    PackageVersionStatus,
    PublisherProfile,
    ReusablePackage,
    ReusablePackageType,
)


@pytest.fixture(autouse=True)
def _mock_billing(monkeypatch):
    monkeypatch.setenv("BILLING_MODE", "mock")
    monkeypatch.setenv("BILLING_WEBHOOK_SECRET", "test-secret")
    get_commerce_settings.cache_clear()
    yield
    get_commerce_settings.cache_clear()


@pytest_asyncio.fixture
async def catalog(db_session: AsyncSession, org_a, user_a):
    marketplace = Marketplace(slug="test-mkt", name="Test",
                              type=MarketplaceType.PUBLIC_MARKETPLACE,
                              visibility="PUBLIC", configuration={})
    db_session.add(marketplace)
    package = ReusablePackage(
        organization_id=None, slug="acme.demo", name="Demo",
        package_type=ReusablePackageType.AGENT)
    db_session.add(package)
    publisher = PublisherProfile(display_name="Acme", slug="acme-test")
    db_session.add(publisher)
    await db_session.flush()
    version = PackageVersion(
        package_id=package.id, version="1.0.0",
        status=PackageVersionStatus.PUBLISHED, manifest={})
    db_session.add(version)
    await db_session.flush()
    listing = MarketplaceListing(
        marketplace_id=marketplace.id, package_id=package.id,
        publisher_id=publisher.id, slug="acme-demo", title="Demo",
        published_version_id=version.id, published_version="1.0.0",
        status=ListingStatus.PUBLISHED)
    db_session.add(listing)
    await db_session.commit()
    await db_session.refresh(listing)
    await db_session.refresh(publisher)
    return {"listing": listing, "publisher": publisher,
            "org": org_a, "user": user_a}


def _signed(secret: str, payload: dict) -> tuple[bytes, dict[str, str]]:
    raw = json.dumps(payload).encode()
    sig = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return raw, {"x-webhook-signature": f"sha256={sig}",
                 "x-webhook-timestamp": str(time.time())}


class TestCheckoutWebhookEntitlement:
    async def test_full_paid_flow(self, db_session: AsyncSession, catalog):
        listing = catalog["listing"]
        publisher = catalog["publisher"]
        org = catalog["org"]
        user = catalog["user"]

        product = await svc.create_product(
            db_session, listing_id=listing.id, publisher_id=publisher.id,
            product_type="PACKAGE", pricing_model="ONE_TIME",
            currency="USD", access="ENTITLEMENT_REQUIRED")
        price = await svc.create_price(
            db_session, product_id=product.id, amount_minor=999,
            currency="USD", pricing_model="ONE_TIME",
            billing_interval="ONE_TIME")
        await db_session.commit()

        customer = await svc.get_or_create_customer(
            db_session, provider="mock", provider_customer_id="cus_test_1",
            user_id=user.id, organization_id=org.id)
        session = await svc.create_checkout(
            db_session, customer=customer, product=product, price=price,
            organization_id=org.id, user_id=user.id,
            idempotency_key="chk-test-1")
        await db_session.commit()
        assert session.status == "CREATED"
        assert session.provider_session_id.startswith("cs_test_")

        # Duplicate idempotency key returns the same session (no double).
        again = await svc.create_checkout(
            db_session, customer=customer, product=product, price=price,
            organization_id=org.id, user_id=user.id,
            idempotency_key="chk-test-1")
        assert again.id == session.id

        # Verified webhook: payment -> checkout completion -> entitlement
        # -> revenue + ledger.
        payload = {"event_id": "evt_test_1", "event_type": "PAYMENT_SUCCEEDED",
                   "transaction_reference": "ch_test_1", "amount_minor": 999,
                   "currency": "USD", "product_id": str(product.id),
                   "organization_id": str(org.id),
                   "publisher_id": str(publisher.id),
                   "checkout_session_id": session.provider_session_id,
                   "test_mode": True}
        raw, headers = _signed("test-secret", payload)
        result = await svc.process_billing_webhook(
            db_session, provider="mock", headers=headers, raw_body=raw,
            payload=payload)
        await db_session.commit()
        assert result["processed"] is True
        assert result["entitlement_id"]
        assert result["revenue_id"]

        payment = (await db_session.execute(select(Payment).where(
            Payment.provider_reference == "ch_test_1"))).scalar_one()
        assert payment.status == "SUCCEEDED"
        assert payment.amount_minor == 999

        await db_session.refresh(session)
        assert session.status == "COMPLETED"

        # Entitlement grants commercial access...
        allowed, _ = await svc.check_access(
            db_session, feature="package.install", organization_id=org.id)
        assert allowed is True

        # ...and the MP23 install gate agrees (dual-write).
        from openagent.marketplace import entitlements as legacy_ent
        legacy_rows = (await db_session.execute(select(
            __import__("openagent.db.models.marketplace",
                       fromlist=["Entitlement"]).Entitlement))).scalars().all()
        mine = [e for e in legacy_rows
                if str(e.organization_id) == str(org.id)]
        assert mine, "legacy entitlement dual-write missing"
        allowed, code, _ = legacy_ent.can_install_listing(
            pricing_model="ONE_TIME",
            entitlements=[{"organization_id": str(org.id),
                           "status": e.status.value
                           if hasattr(e.status, "value") else str(e.status)}
                          for e in mine],
            organization_id=str(org.id), commerce_configured=True)
        assert allowed and code == "OK_ENTITLED"

        # Revenue + ledger reflect the sale (default 0 bps fee).
        revenue = (await db_session.execute(select(RevenueRecord).where(
            RevenueRecord.transaction_reference == "ch_test_1"))).scalar_one()
        assert revenue.gross_minor == 999
        assert revenue.fee_minor == 0
        assert revenue.net_minor == 999
        balances = await svc.creator_balance(db_session, publisher.id)
        assert balances.get("USD", 0) == revenue.net_minor

        # Replay of the same event is deduplicated (no double entitlement).
        result2 = await svc.process_billing_webhook(
            db_session, provider="mock", headers=headers, raw_body=raw,
            payload=payload)
        await db_session.commit()
        assert result2["deduplicated"] is True

    async def test_refund_revokes_entitlement(self, db_session: AsyncSession,
                                              catalog):
        listing = catalog["listing"]
        publisher = catalog["publisher"]
        org = catalog["org"]
        product = await svc.create_product(
            db_session, listing_id=listing.id, publisher_id=publisher.id,
            product_type="PACKAGE", pricing_model="ONE_TIME", currency="USD")
        await db_session.commit()
        payload = {"event_id": "evt_ref_1", "event_type": "PAYMENT_SUCCEEDED",
                   "transaction_reference": "ch_ref_1", "amount_minor": 500,
                   "currency": "USD", "product_id": str(product.id),
                   "organization_id": str(org.id),
                   "publisher_id": str(publisher.id), "test_mode": True}
        raw, headers = _signed("test-secret", payload)
        await svc.process_billing_webhook(
            db_session, provider="mock", headers=headers, raw_body=raw,
            payload=payload)
        await db_session.commit()
        allowed, _ = await svc.check_access(
            db_session, feature="package.install", organization_id=org.id)
        assert allowed is True

        refund_payload = {"event_id": "evt_ref_2",
                          "event_type": "PAYMENT_REFUNDED",
                          "transaction_reference": "ch_ref_1",
                          "amount_minor": 500, "test_mode": True}
        raw2, headers2 = _signed("test-secret", refund_payload)
        await svc.process_billing_webhook(
            db_session, provider="mock", headers=headers2, raw_body=raw2,
            payload=refund_payload)
        await db_session.commit()
        allowed, _ = await svc.check_access(
            db_session, feature="package.install", organization_id=org.id)
        assert allowed is False


class TestSubscriptions:
    async def test_subscription_grants_and_cancel_revokes(
            self, db_session: AsyncSession, catalog):
        listing = catalog["listing"]
        org = catalog["org"]
        user = catalog["user"]
        product = await svc.create_product(
            db_session, listing_id=listing.id, publisher_id=None,
            product_type="SUBSCRIPTION", pricing_model="SUBSCRIPTION",
            currency="USD")
        await db_session.commit()
        await svc.get_or_create_customer(
            db_session, provider="mock", provider_customer_id="cus_sub_1",
            user_id=user.id, organization_id=org.id)
        await db_session.commit()
        payload = {"event_id": "evt_sub_1",
                   "event_type": "SUBSCRIPTION_CREATED",
                   "provider_subscription_id": "sub_test_1",
                   "provider_customer_id": "cus_sub_1",
                   "organization_id": str(org.id),
                   "product_id": str(product.id),
                   "current_period_end": (
                       datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
                   "test_mode": True}
        raw, headers = _signed("test-secret", payload)
        result = await svc.process_billing_webhook(
            db_session, provider="mock", headers=headers, raw_body=raw,
            payload=payload)
        await db_session.commit()
        assert result["status"] == "ACTIVE"
        allowed, _ = await svc.check_access(
            db_session, feature="package.install", organization_id=org.id)
        assert allowed is True

        cancel = {"event_id": "evt_sub_2",
                  "event_type": "SUBSCRIPTION_CANCELLED",
                  "provider_subscription_id": "sub_test_1",
                  "test_mode": True}
        raw2, headers2 = _signed("test-secret", cancel)
        await svc.process_billing_webhook(
            db_session, provider="mock", headers=headers2, raw_body=raw2,
            payload=cancel)
        await db_session.commit()
        allowed, _ = await svc.check_access(
            db_session, feature="package.install", organization_id=org.id)
        assert allowed is False


class TestUsageQuotasCredits:
    async def test_usage_record_aggregate_quota(self, db_session: AsyncSession,
                                                org_a):
        meter = (await db_session.execute(select(UsageMeter).where(
            UsageMeter.slug == "agent_runs"))).scalar_one_or_none()
        assert meter is not None, "migration 023 must seed usage meters"
        first = await svc.record_usage(
            db_session, meter_slug="agent_runs", organization_id=org_a.id,
            quantity=3, idempotency_key="use-test-1")
        await db_session.commit()
        again = await svc.record_usage(
            db_session, meter_slug="agent_runs", organization_id=org_a.id,
            quantity=3, idempotency_key="use-test-1")
        assert again.id == first.id  # idempotent

        start = datetime.now(timezone.utc).replace(
            day=1, hour=0, minute=0, second=0, microsecond=0)
        end = datetime.now(timezone.utc) + timedelta(days=1)
        summary = await svc.aggregate_usage(
            db_session, meter_slug="agent_runs",
            organization_id=org_a.id, period_start=start, period_end=end)
        await db_session.commit()
        assert summary["total"] == 3

        quota = Quota(organization_id=org_a.id, meter_id=meter.id,
                      limit_value=5, period="MONTHLY", quota_metadata={})
        db_session.add(quota)
        await db_session.commit()
        allowed, _, _ = await svc.check_quota(
            db_session, quota_id=quota.id, quantity=2)
        assert allowed is True
        consumed = await svc.consume_quota(
            db_session, quota_id=quota.id, quantity=4)
        assert consumed["used"] == 4
        with pytest.raises(CommerceError) as exc:
            await svc.consume_quota(db_session, quota_id=quota.id,
                                    quantity=2)
        assert exc.value.code == "QUOTA_EXCEEDED"

    async def test_credits(self, db_session: AsyncSession, org_a):
        account = CreditAccount(organization_id=org_a.id, currency="CREDITS")
        db_session.add(account)
        await db_session.commit()
        await svc.credit_transaction(
            db_session, account_id=account.id, txn_type="GRANT", amount=100,
            source="promo", idempotency_key="ctx-test-1")
        await db_session.commit()
        assert await svc.credit_balance(db_session, account.id) == 100
        await svc.credit_transaction(
            db_session, account_id=account.id, txn_type="CONSUME", amount=30,
            source="api")
        await db_session.commit()
        assert await svc.credit_balance(db_session, account.id) == 70
        with pytest.raises(CommerceError):
            await svc.credit_transaction(
                db_session, account_id=account.id, txn_type="CONSUME",
                amount=1000, source="api")


class TestInvoicesRefundsDisputes:
    async def test_invoice_exact_arithmetic(self, db_session: AsyncSession,
                                            org_a, user_a):
        customer = await svc.get_or_create_customer(
            db_session, provider="mock", provider_customer_id="cus_inv_1",
            user_id=user_a.id, organization_id=org_a.id)
        await db_session.commit()
        invoice = await svc.create_invoice(
            db_session, customer_id=customer.id, organization_id=org_a.id,
            currency="USD",
            lines=[{"description": "Pro", "quantity": 2,
                    "unit_price_minor": 999},
                   {"description": "Setup", "quantity": 1,
                    "unit_price_minor": 500}],
            discount_minor=100, tax_minor=0,
            idempotency_key="inv-test-1")
        await db_session.commit()
        assert invoice.subtotal_minor == 2 * 999 + 500
        assert invoice.total_minor == 2 * 999 + 500 - 100

    async def test_creator_payout_lifecycle(self, db_session: AsyncSession,
                                            catalog):
        publisher = catalog["publisher"]
        user = catalog["user"]
        db_session.add(CreatorLedgerEntry(
            publisher_id=publisher.id, account="creator", type="CREDIT",
            amount_minor=5000, currency="USD", reference="sale-1",
            reference_type="payment", status="POSTED",
            idempotency_key="ledger-test-1"))
        await db_session.commit()
        # Unverified publishers are ineligible (verification gate).
        with pytest.raises(CommerceError) as exc:
            await svc.request_payout(
                db_session, publisher_id=publisher.id, amount_minor=2500,
                currency="USD", destination_reference="acct_test_1",
                requested_by=user.id,
                publisher_verified=False, require_verification=True)
        assert exc.value.code == "PAYOUT_INELIGIBLE"
        payout = await svc.request_payout(
            db_session, publisher_id=publisher.id, amount_minor=2500,
            currency="USD", destination_reference="acct_test_1",
            requested_by=user.id, publisher_verified=True,
            require_verification=True, idempotency_key="po-test-1")
        await db_session.commit()
        assert payout.status == "PENDING"
        # Over-balance request is rejected.
        with pytest.raises(CommerceError) as exc:
            await svc.request_payout(
                db_session, publisher_id=publisher.id, amount_minor=99999,
                currency="USD", destination_reference="acct_test_1",
                requested_by=user.id, publisher_verified=True,
                require_verification=True)
        assert exc.value.code == "INSUFFICIENT_BALANCE"

        held = await svc.transition_payout(
            db_session, payout.id, target="ELIGIBLE",
            actor_user_id=user.id)
        assert held.status == "ELIGIBLE"
        processing = await svc.transition_payout(
            db_session, payout.id, target="PROCESSING",
            actor_user_id=user.id)
        assert processing.status == "PROCESSING"
        assert processing.provider == "mock"
        paid = await svc.transition_payout(
            db_session, payout.id, target="PAID", actor_user_id=user.id)
        await db_session.commit()
        assert paid.status == "PAID"
        balances = await svc.creator_balance(db_session, publisher.id)
        assert balances["USD"] == 5000 - 2500
        # Terminal: no resurrection.
        with pytest.raises(CommerceError):
            await svc.transition_payout(db_session, payout.id,
                                        target="ELIGIBLE")

    async def test_fee_policy_applies(self, db_session: AsyncSession, catalog):
        listing = catalog["listing"]
        publisher = catalog["publisher"]
        org = catalog["org"]
        db_session.add(FeePolicy(marketplace="", product_type="PACKAGE",
                                 publisher_type="", rate_bps=1000,
                                 fixed_fee_minor=0, currency="USD",
                                 is_active=True))
        await db_session.commit()
        product = await svc.create_product(
            db_session, listing_id=listing.id, publisher_id=publisher.id,
            product_type="PACKAGE", pricing_model="ONE_TIME", currency="USD")
        await db_session.commit()
        payload = {"event_id": "evt_fee_1", "event_type": "PAYMENT_SUCCEEDED",
                   "transaction_reference": "ch_fee_1", "amount_minor": 1000,
                   "currency": "USD", "product_id": str(product.id),
                   "organization_id": str(org.id),
                   "publisher_id": str(publisher.id), "test_mode": True}
        raw, headers = _signed("test-secret", payload)
        await svc.process_billing_webhook(
            db_session, provider="mock", headers=headers, raw_body=raw,
            payload=payload)
        await db_session.commit()
        revenue = (await db_session.execute(select(RevenueRecord).where(
            RevenueRecord.transaction_reference == "ch_fee_1"))).scalar_one()
        assert revenue.fee_minor == 100
        assert revenue.net_minor == 900


class TestPromotions:
    async def test_redeem_and_limits(self, db_session: AsyncSession,
                                     org_a, user_a):
        promotion = Promotion(name="Launch 20%", kind="PERCENT",
                              percent_bps=2000, is_active=True)
        db_session.add(promotion)
        await db_session.flush()
        code = PromoCode(promotion_id=promotion.id, code="LAUNCH20",
                         max_redemptions=10, max_per_customer=1,
                         eligible_customers=[], eligible_products=[],
                         is_active=True, redemption_count=0)
        db_session.add(code)
        await db_session.commit()
        customer = await svc.get_or_create_customer(
            db_session, provider="mock", provider_customer_id="cus_promo_1",
            user_id=user_a.id, organization_id=org_a.id)
        await db_session.commit()
        redemption = await svc.redeem_promo(
            db_session, code="launch20", customer_id=customer.id,
            gross_minor=1000)
        await db_session.commit()
        assert redemption.discount_minor == 200
        # Second redemption by same customer is rejected (max_per_customer=1).
        with pytest.raises(CommerceError) as exc:
            await svc.redeem_promo(db_session, code="LAUNCH20",
                                   customer_id=customer.id, gross_minor=1000)
        assert exc.value.code == "COUPON_REJECTED"
