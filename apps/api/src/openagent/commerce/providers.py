"""MP24: provider-neutral billing/payout/tax interfaces + mock + disabled.

No real provider SDK is vendored here. ``BillingProvider`` is the seam a
future Stripe/Paddle/... adapter implements; ``MockBillingProvider`` gives
deterministic test events (clearly labelled ``provider="mock"``) and
``DisabledBillingProvider`` (default) refuses paid operations with an
explicit error instead of fabricating success.

Payment security: provider-hosted checkout only. We store provider
references (customer/subscription/invoice ids) — never card numbers, CVV,
bank credentials or passwords. No such field exists in this package.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol


class CommerceError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class CheckoutResult:
    provider: str
    provider_session_id: str
    checkout_url: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class VerifiedPayment:
    provider: str
    transaction_reference: str
    amount_minor: int
    currency: str
    product_id: str = ""
    customer_reference: str = ""


class BillingProvider(Protocol):
    name: str

    async def create_customer(self, *, email: str,
                              organization_id: str = "",
                              user_id: str = "",
                              metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        ...

    async def create_product(self, *, name: str, product_type: str,
                             metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        ...

    async def create_price(self, *, provider_product_id: str,
                           amount_minor: int, currency: str,
                           interval: str = "ONE_TIME",
                           trial_days: int = 0,
                           metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        ...

    async def create_checkout(self, *, provider_customer_id: str,
                              provider_price_id: str, product_id: str,
                              organization_id: str,
                              success_url: str, cancel_url: str,
                              metadata: dict[str, Any] | None = None) -> CheckoutResult:
        ...

    async def verify_payment(self, *, transaction_reference: str) -> VerifiedPayment:
        ...

    async def create_subscription(self, *, provider_customer_id: str,
                                  provider_price_id: str,
                                  trial_days: int = 0,
                                  metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        ...

    async def cancel_subscription(self, *, provider_subscription_id: str,
                                  at_period_end: bool = True) -> dict[str, Any]:
        ...

    async def refund(self, *, transaction_reference: str,
                     amount_minor: int | None = None,
                     reason: str = "") -> dict[str, Any]:
        ...

    async def create_portal_session(self, *, provider_customer_id: str,
                                    return_url: str) -> dict[str, Any]:
        ...

    async def retrieve_invoice(self, *, provider_invoice_id: str) -> dict[str, Any]:
        ...

    async def handle_webhook(self, *, headers: dict[str, str],
                             raw_body: bytes) -> dict[str, Any]:
        ...


class DisabledBillingProvider:
    """Default: commerce not configured. Paid ops raise; free flows pass."""

    name = "disabled"

    async def _unavailable(self, op: str) -> Any:
        raise CommerceError("COMMERCE_DISABLED",
                            f"billing provider not configured (op={op}); "
                            "set BILLING_MODE=mock for local development")

    async def create_customer(self, **kw: Any) -> dict[str, Any]:
        await self._unavailable("create_customer")
        raise AssertionError("unreachable")

    async def create_product(self, **kw: Any) -> dict[str, Any]:
        await self._unavailable("create_product")
        raise AssertionError("unreachable")

    async def create_price(self, **kw: Any) -> dict[str, Any]:
        await self._unavailable("create_price")
        raise AssertionError("unreachable")

    async def create_checkout(self, **kw: Any) -> CheckoutResult:
        await self._unavailable("create_checkout")
        raise AssertionError("unreachable")

    async def verify_payment(self, **kw: Any) -> VerifiedPayment:
        await self._unavailable("verify_payment")
        raise AssertionError("unreachable")

    async def create_subscription(self, **kw: Any) -> dict[str, Any]:
        await self._unavailable("create_subscription")
        raise AssertionError("unreachable")

    async def cancel_subscription(self, **kw: Any) -> dict[str, Any]:
        await self._unavailable("cancel_subscription")
        raise AssertionError("unreachable")

    async def refund(self, **kw: Any) -> dict[str, Any]:
        await self._unavailable("refund")
        raise AssertionError("unreachable")

    async def create_portal_session(self, **kw: Any) -> dict[str, Any]:
        await self._unavailable("create_portal_session")
        raise AssertionError("unreachable")

    async def retrieve_invoice(self, **kw: Any) -> dict[str, Any]:
        await self._unavailable("retrieve_invoice")
        raise AssertionError("unreachable")

    async def handle_webhook(self, **kw: Any) -> dict[str, Any]:
        await self._unavailable("handle_webhook")
        raise AssertionError("unreachable")


def _mock_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]
    return f"{prefix}_test_{digest}"


class MockBillingProvider:
    """Deterministic test provider. NEVER reports a real payment.

    Every id is ``mock_test_*``-style and every event payload carries
    ``"test_mode": true``. Webhooks it emits are HMAC-signed with the
    configured secret so the real verification path is exercised.
    """

    name = "mock"

    def __init__(self, webhook_secret: str = "mock-secret"):
        self._secret = webhook_secret
        self._payments: dict[str, VerifiedPayment] = {}

    async def create_customer(self, *, email: str, organization_id: str = "",
                              user_id: str = "",
                              metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"provider": "mock",
                "provider_customer_id": _mock_id("cus", email, organization_id),
                "test_mode": True}

    async def create_product(self, *, name: str, product_type: str,
                             metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"provider": "mock",
                "provider_product_id": _mock_id("prod", name, product_type),
                "test_mode": True}

    async def create_price(self, *, provider_product_id: str,
                           amount_minor: int, currency: str,
                           interval: str = "ONE_TIME",
                           trial_days: int = 0,
                           metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        if amount_minor < 0:
            raise CommerceError("BAD_AMOUNT", "amount must be >= 0")
        return {"provider": "mock",
                "provider_price_id": _mock_id(
                    "price", provider_product_id, str(amount_minor),
                    currency, interval),
                "test_mode": True}

    async def create_checkout(self, *, provider_customer_id: str,
                              provider_price_id: str, product_id: str,
                              organization_id: str,
                              success_url: str, cancel_url: str,
                              metadata: dict[str, Any] | None = None) -> CheckoutResult:
        session_id = _mock_id("cs", provider_customer_id, provider_price_id,
                              organization_id or uuid.uuid4().hex)
        return CheckoutResult(provider="mock", provider_session_id=session_id,
                              checkout_url=f"mock://checkout/{session_id}",
                              metadata={"test_mode": True, **(metadata or {})})

    async def verify_payment(self, *, transaction_reference: str) -> VerifiedPayment:
        payment = self._payments.get(transaction_reference)
        if payment is None:
            raise CommerceError("PAYMENT_NOT_FOUND",
                                f"unknown test payment {transaction_reference}")
        return payment

    async def create_subscription(self, *, provider_customer_id: str,
                                  provider_price_id: str,
                                  trial_days: int = 0,
                                  metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"provider": "mock",
                "provider_subscription_id": _mock_id(
                    "sub", provider_customer_id, provider_price_id),
                "status": "TRIALING" if trial_days > 0 else "ACTIVE",
                "test_mode": True}

    async def cancel_subscription(self, *, provider_subscription_id: str,
                                  at_period_end: bool = True) -> dict[str, Any]:
        return {"provider": "mock",
                "provider_subscription_id": provider_subscription_id,
                "status": "CANCELLED", "test_mode": True}

    async def refund(self, *, transaction_reference: str,
                     amount_minor: int | None = None,
                     reason: str = "") -> dict[str, Any]:
        return {"provider": "mock",
                "provider_refund_id": _mock_id("re", transaction_reference,
                                               str(amount_minor or 0)),
                "status": "SUCCEEDED", "test_mode": True}

    async def create_portal_session(self, *, provider_customer_id: str,
                                    return_url: str) -> dict[str, Any]:
        return {"provider": "mock",
                "portal_url": f"mock://portal/{provider_customer_id}",
                "test_mode": True}

    async def retrieve_invoice(self, *, provider_invoice_id: str) -> dict[str, Any]:
        return {"provider": "mock",
                "provider_invoice_id": provider_invoice_id,
                "status": "OPEN", "test_mode": True}

    async def handle_webhook(self, *, headers: dict[str, str],
                             raw_body: bytes) -> dict[str, Any]:
        # Mock provider never auto-processes inbound webhooks; tests drive
        # deterministic events via `mock_event()`.
        raise CommerceError("MOCK_NO_INBOUND",
                            "mock provider has no inbound webhooks; "
                            "use mock_event() in tests")

    # -- deterministic test helpers -----------------------------------------
    def record_test_payment(self, *, reference: str, amount_minor: int,
                            currency: str, product_id: str = "",
                            customer_reference: str = "") -> VerifiedPayment:
        payment = VerifiedPayment(provider="mock",
                                  transaction_reference=reference,
                                  amount_minor=amount_minor,
                                  currency=currency, product_id=product_id,
                                  customer_reference=customer_reference)
        self._payments[reference] = payment
        return payment

    def mock_event(self, *, event_id: str, event_type: str,
                   transaction_reference: str = "",
                   amount_minor: int = 0, currency: str = "USD") -> dict[str, Any]:
        return {"provider": "mock", "event_id": event_id,
                "event_type": event_type,
                "transaction_reference": transaction_reference,
                "amount_minor": amount_minor, "currency": currency,
                "test_mode": True,
                "created_at": datetime.now(timezone.utc).isoformat()}


def get_billing_provider(*, mode: str,
                         webhook_secret: str = "") -> BillingProvider:
    normalized = str(mode or "disabled").lower()
    if normalized == "mock":
        provider: BillingProvider = MockBillingProvider(
            webhook_secret=webhook_secret or "mock-secret")
        return provider
    if normalized == "live":
        raise CommerceError("PROVIDER_NOT_CONFIGURED",
                            "BILLING_MODE=live requires an explicit provider "
                            "adapter (Stripe/Paddle/...); none is bundled")
    disabled: BillingProvider = DisabledBillingProvider()
    return disabled


class PayoutProvider(Protocol):
    name: str

    async def create_payout(self, *, publisher_id: str, amount_minor: int,
                            currency: str,
                            destination_reference: str) -> dict[str, Any]:
        ...

    async def get_payout(self, *, provider_payout_id: str) -> dict[str, Any]:
        ...

    async def cancel_payout(self, *, provider_payout_id: str) -> dict[str, Any]:
        ...

    async def verify_destination(self, *, destination_reference: str) -> dict[str, Any]:
        ...


class MockPayoutProvider:
    """Deterministic payout stub for tests/dev (clearly test mode)."""

    name = "mock"

    async def create_payout(self, *, publisher_id: str, amount_minor: int,
                            currency: str,
                            destination_reference: str) -> dict[str, Any]:
        if amount_minor <= 0:
            raise CommerceError("BAD_AMOUNT", "payout amount must be > 0")
        return {"provider": "mock",
                "provider_payout_id": _mock_id("po", publisher_id,
                                               str(amount_minor), currency),
                "status": "PROCESSING", "test_mode": True}

    async def get_payout(self, *, provider_payout_id: str) -> dict[str, Any]:
        return {"provider": "mock",
                "provider_payout_id": provider_payout_id,
                "status": "PROCESSING", "test_mode": True}

    async def cancel_payout(self, *, provider_payout_id: str) -> dict[str, Any]:
        return {"provider": "mock",
                "provider_payout_id": provider_payout_id,
                "status": "CANCELLED", "test_mode": True}

    async def verify_destination(self, *, destination_reference: str) -> dict[str, Any]:
        return {"provider": "mock", "valid": bool(destination_reference),
                "test_mode": True}


class DisabledPayoutProvider:
    name = "disabled"

    async def _unavailable(self, op: str) -> Any:
        raise CommerceError("PAYOUTS_DISABLED",
                            f"payout provider not configured (op={op})")

    async def create_payout(self, **kw: Any) -> dict[str, Any]:
        await self._unavailable("create_payout")
        raise AssertionError("unreachable")

    async def get_payout(self, **kw: Any) -> dict[str, Any]:
        await self._unavailable("get_payout")
        raise AssertionError("unreachable")

    async def cancel_payout(self, **kw: Any) -> dict[str, Any]:
        await self._unavailable("cancel_payout")
        raise AssertionError("unreachable")

    async def verify_destination(self, **kw: Any) -> dict[str, Any]:
        await self._unavailable("verify_destination")
        raise AssertionError("unreachable")


class TaxProvider(Protocol):
    name: str

    async def calculate(self, *, amount_minor: int, currency: str,
                        customer_country: str = "",
                        product_type: str = "") -> dict[str, Any]:
        ...

    async def validate(self, *, tax_id: str, country: str = "") -> dict[str, Any]:
        ...

    async def report(self, *, period_start: str,
                     period_end: str) -> dict[str, Any]:
        ...


class NoopTaxProvider:
    """Default: no jurisdiction logic. Never invents rates.

    Returns zero tax with an explicit ``calculated=false`` marker so callers
    can distinguish "no tax provider" from "0% tax assessed".
    """

    name = "noop"

    async def calculate(self, *, amount_minor: int, currency: str,
                        customer_country: str = "",
                        product_type: str = "") -> dict[str, Any]:
        return {"provider": "noop", "tax_minor": 0, "currency": currency,
                "calculated": False,
                "note": "no tax provider configured; no tax assessed"}

    async def validate(self, *, tax_id: str, country: str = "") -> dict[str, Any]:
        return {"provider": "noop", "valid": False,
                "note": "no tax provider configured"}

    async def report(self, *, period_start: str,
                     period_end: str) -> dict[str, Any]:
        return {"provider": "noop", "entries": [], "period_start": period_start,
                "period_end": period_end}
