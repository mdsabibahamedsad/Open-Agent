"""MP24: usage metering + aggregation + quota logic (pure functions).

Raw events -> UsageAggregator -> UsageSummary -> invoice/billing.
Aggregation supports SUM/COUNT/MAX/UNIQUE/DURATION. Quota checks are
concurrency-safe at the service layer (SELECT ... FOR UPDATE); the pure
``quota_decision`` here keeps the math testable.
"""

from __future__ import annotations

from typing import Any

from openagent.commerce.types import UsageAggregation


def aggregate(records: list[dict[str, Any]], *,
              aggregation: str) -> float | int:
    """Aggregate quantity values per ``aggregation`` kind."""
    agg = str(aggregation or UsageAggregation.SUM).upper()
    quantities = [r.get("quantity", 0) for r in records]
    if agg == UsageAggregation.COUNT:
        return len(records)
    if agg == UsageAggregation.MAX:
        nums = [float(q) for q in quantities]
        return max(nums) if nums else 0
    if agg == UsageAggregation.UNIQUE:
        return len({str(r.get("dedup_key", r.get("quantity"))) for r in records})
    if agg == UsageAggregation.DURATION:
        return sum(float(q) for q in quantities)
    return sum(float(q) for q in quantities)


def quota_decision(*, limit: float | None, used: float,
                   requested: float = 1) -> tuple[bool, str, float]:
    """Return (allowed, reason, remaining_after). Unlimited when limit None."""
    if requested < 0:
        return False, "requested quantity must be >= 0", max(0.0, (limit or 0) - used)
    if limit is None:
        return True, "unlimited quota", float("inf")
    remaining = float(limit) - float(used)
    if remaining >= float(requested):
        return True, "within quota", remaining - float(requested)
    return False, "quota exceeded", remaining


def overage(*, included: float, used: float) -> float:
    """Usage beyond the included allowance (never negative)."""
    return max(0.0, float(used) - float(included))


def trial_is_live(trial: dict[str, Any], *, now_iso: str,
                  usage: float = 0) -> tuple[bool, str]:
    """Trial rules: window + optional usage cap + single-use marker."""
    start = str(trial.get("start") or "")
    end = str(trial.get("end") or "")
    if start and now_iso < start:
        return False, "trial not started"
    if end and now_iso > end:
        return False, "trial ended"
    cap = trial.get("usage_limit")
    if cap is not None and usage >= float(cap):
        return False, "trial usage limit reached"
    if trial.get("consumed"):
        return False, "trial already redeemed"
    return True, "trial live"


def validate_coupon(*, coupon: dict[str, Any], now_iso: str,
                    customer_id: str = "", product_id: str = "",
                    prior_redemptions: int = 0,
                    customer_redemptions: int = 0) -> tuple[bool, str]:
    """Server-side coupon validation. Never trust client-side checks."""
    if not coupon.get("active", True):
        return False, "coupon inactive"
    if str(coupon.get("expires_at") or "") and now_iso > str(coupon["expires_at"]):
        return False, "coupon expired"
    max_uses = coupon.get("max_redemptions")
    if max_uses is not None and prior_redemptions >= int(max_uses):
        return False, "coupon usage limit reached"
    per_customer = coupon.get("max_per_customer", 1)
    if customer_redemptions >= int(per_customer):
        return False, "coupon already redeemed by this customer"
    eligible_customers = coupon.get("eligible_customers") or []
    if eligible_customers and customer_id not in eligible_customers:
        return False, "coupon not eligible for this customer"
    eligible_products = coupon.get("eligible_products") or []
    if eligible_products and product_id not in eligible_products:
        return False, "coupon not eligible for this product"
    return True, "coupon valid"


def coupon_discount(*, coupon: dict[str, Any],
                    gross_minor: int) -> int:
    """Discount in minor units (floored, never exceeds gross)."""
    kind = str(coupon.get("kind", "PERCENT")).upper()
    if kind == "FIXED":
        return min(int(coupon.get("amount_minor", 0)), gross_minor)
    bps = int(coupon.get("percent_bps", 0))
    if not 0 <= bps <= 10000:
        raise ValueError("percent_bps out of range")
    return min((gross_minor * bps) // 10000, gross_minor)
