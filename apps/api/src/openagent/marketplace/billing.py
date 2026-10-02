"""MP23: commerce interfaces — provider-neutral, no real payments.

``BillingProvider`` defines the seam future providers (Stripe, etc.) plug
into: products, prices, checkout, payment verification, entitlements,
refunds, payouts and webhooks. ``DisabledBillingProvider`` is the default:
paid operations raise instead of fabricating success. Webhook intake calls
:func:`verify_webhook` (HMAC signature + timestamp freshness + replay via
the persisted event table + idempotency key) and never trusts unsigned
events. Revenue splits are computed from explicit platform policy, never a
hard-coded permanent percentage.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass, field
from typing import Any, Protocol


class CommerceError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class CheckoutSession:
    provider: str
    session_id: str
    checkout_url: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class VerifiedPayment:
    provider: str
    transaction_reference: str
    amount_minor: int
    currency: str
    product_id: str = ""
    payer_org_id: str = ""


class BillingProvider(Protocol):
    name: str

    async def create_product(self, *, listing_id: str,
                             product_type: str, pricing_model: str,
                             currency: str) -> dict[str, Any]:
        ...

    async def create_price(self, *, product_id: str, amount_minor: int,
                           currency: str, interval: str = "ONE_TIME",
                           tiers: list[dict[str, Any]] | None = None
                           ) -> dict[str, Any]:
        ...

    async def create_checkout(self, *, product_id: str, price_id: str,
                              organization_id: str,
                              success_url: str, cancel_url: str
                              ) -> CheckoutSession:
        ...

    async def verify_payment(self, *, transaction_reference: str) -> VerifiedPayment:
        ...

    async def create_entitlement(self, *, product_id: str, listing_id: str,
                                 organization_id: str) -> dict[str, Any]:
        ...

    async def refund(self, *, transaction_reference: str,
                     amount_minor: int | None = None) -> dict[str, Any]:
        ...

    async def payout(self, *, publisher_id: str, amount_minor: int,
                     currency: str) -> dict[str, Any]:
        ...

    async def handle_webhook(self, *, headers: dict[str, str],
                             raw_body: bytes) -> dict[str, Any]:
        ...


class DisabledBillingProvider:
    """Default provider: commerce is not configured.

    Free flows work; anything requiring money raises a clear error instead
    of inventing a successful payment.
    """

    name = "disabled"

    async def _unavailable(self, op: str) -> Any:
        raise CommerceError("COMMERCE_DISABLED",
                            f"billing provider not configured (op={op})")

    async def create_product(self, **kwargs: Any) -> dict[str, Any]:
        await self._unavailable("create_product")
        raise AssertionError("unreachable")

    async def create_price(self, **kwargs: Any) -> dict[str, Any]:
        await self._unavailable("create_price")
        raise AssertionError("unreachable")

    async def create_checkout(self, **kwargs: Any) -> CheckoutSession:
        await self._unavailable("create_checkout")
        raise AssertionError("unreachable")

    async def verify_payment(self, **kwargs: Any) -> VerifiedPayment:
        await self._unavailable("verify_payment")
        raise AssertionError("unreachable")

    async def create_entitlement(self, **kwargs: Any) -> dict[str, Any]:
        await self._unavailable("create_entitlement")
        raise AssertionError("unreachable")

    async def refund(self, **kwargs: Any) -> dict[str, Any]:
        await self._unavailable("refund")
        raise AssertionError("unreachable")

    async def payout(self, **kwargs: Any) -> dict[str, Any]:
        await self._unavailable("payout")
        raise AssertionError("unreachable")

    async def handle_webhook(self, **kwargs: Any) -> dict[str, Any]:
        await self._unavailable("handle_webhook")
        raise AssertionError("unreachable")


WEBHOOK_MAX_SKEW_SECONDS = 300


def verify_webhook_signature(*, secret: str, raw_body: bytes,
                             signature: str) -> bool:
    """HMAC-SHA256 check (``sha256=<hex>`` or raw hex accepted)."""
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    candidate = signature.split("=", 1)[-1].strip()
    return hmac.compare_digest(expected, candidate)


def verify_webhook_timestamp(timestamp: str | int,
                             *, now: float | None = None,
                             max_skew: int = WEBHOOK_MAX_SKEW_SECONDS) -> bool:
    try:
        moment = float(timestamp)
    except (TypeError, ValueError):
        return False
    return abs((now if now is not None else time.time()) - moment) <= max_skew


def split_revenue(*, gross_minor: int, platform_bps: int,
                  affiliate_bps: int = 0) -> dict[str, int]:
    """Split revenue per explicit platform policy (basis points).

    No permanent percentage is hard-coded: callers pass the configured
    policy. Returns {gross, platform_fee, affiliate_fee, publisher_amount}.
    """
    if gross_minor < 0:
        raise CommerceError("BAD_AMOUNT", "gross amount must be >= 0")
    if not (0 <= platform_bps <= 10000) or not (0 <= affiliate_bps <= 10000):
        raise CommerceError("BAD_SPLIT", "fee basis points out of range")
    if platform_bps + affiliate_bps > 10000:
        raise CommerceError("BAD_SPLIT", "fees exceed 100%")
    platform_fee = (gross_minor * platform_bps) // 10000
    affiliate_fee = (gross_minor * affiliate_bps) // 10000
    return {
        "gross": gross_minor,
        "platform_fee": platform_fee,
        "affiliate_fee": affiliate_fee,
        "publisher_amount": gross_minor - platform_fee - affiliate_fee,
    }


def default_revenue_policy() -> dict[str, int]:
    """Placeholder policy used only when nothing is configured.

    A real deployment sets this in marketplace configuration; the default
    keeps 100% with the publisher and charges no platform fee.
    """
    return {"platform_bps": 0, "affiliate_bps": 0}
