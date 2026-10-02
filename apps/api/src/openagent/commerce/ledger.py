"""MP24: revenue math + ledger balances + fee-policy resolution.

- ``split_revenue``: Gross - discounts/refunds - platform fee = creator net.
  Accounting treatment stays provider/config dependent; this is the
  deterministic core.
- ``ledger_balance``: balances derive from ledger entries, never from a
  mutable ``publisher.balance`` column.
- ``resolve_fee``: most-specific FeePolicy wins (product > publisher_type >
  marketplace default). Rates are configuration, never hard-coded.
"""

from __future__ import annotations

from typing import Any

from openagent.commerce.money import percent_of, subtract


class LedgerError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def split_revenue(*, gross_minor: int, discount_minor: int = 0,
                  refund_minor: int = 0, tax_minor: int = 0,
                  platform_bps: int = 0,
                  fixed_fee_minor: int = 0) -> dict[str, int]:
    if gross_minor < 0:
        raise LedgerError("BAD_AMOUNT", "gross must be >= 0")
    for label, value in (("discount", discount_minor), ("refund", refund_minor),
                         ("tax", tax_minor), ("fixed_fee", fixed_fee_minor)):
        if value < 0:
            raise LedgerError("BAD_AMOUNT", f"{label} must be >= 0")
    if not 0 <= platform_bps <= 10000:
        raise LedgerError("BAD_BPS", "platform_bps out of range")
    net_base = gross_minor - discount_minor - refund_minor - tax_minor
    if net_base < 0:
        raise LedgerError("NEGATIVE_BASE",
                          "discounts/refunds/tax exceed gross")
    platform_fee = percent_of(net_base, platform_bps) + fixed_fee_minor
    platform_fee = min(platform_fee, net_base)
    creator_amount = subtract(net_base, platform_fee)
    return {"gross": gross_minor, "discount": discount_minor,
            "refund": refund_minor, "tax": tax_minor,
            "platform_fee": platform_fee,
            "creator_amount": creator_amount}


def ledger_balance(entries: list[dict[str, Any]], *,
                   currency: str = "") -> int:
    """Net balance from ledger entries. Signed per entry type.

    CREDIT/REFUND/ADJUSTMENT(+) increase the creator balance; DEBIT/FEE/
    PAYOUT decrease it. ADJUSTMENT carries its own signed ``amount_minor``.
    """
    total = 0
    for entry in entries:
        if currency and str(entry.get("currency", "")) != currency:
            continue
        kind = str(entry.get("type", "")).upper()
        amount = int(entry.get("amount_minor", 0))
        if kind in ("CREDIT", "REFUND"):
            total += abs(amount)
        elif kind in ("DEBIT", "FEE", "PAYOUT"):
            total -= abs(amount)
        elif kind == "ADJUSTMENT":
            total += amount  # signed
        else:
            raise LedgerError("UNKNOWN_ENTRY", f"unknown ledger type {kind!r}")
    return total


def resolve_fee(*, policies: list[dict[str, Any]], marketplace: str = "",
                product_type: str = "", publisher_type: str = "") -> dict[str, Any]:
    """Most-specific matching FeePolicy wins; fallback is 0 bps + 0 fixed."""

    def specificity(p: dict[str, Any]) -> int:
        score = 0
        if p.get("product_type"):
            score += 4
        if p.get("publisher_type"):
            score += 2
        if p.get("marketplace"):
            score += 1
        return score

    candidates = []
    for policy in policies:
        if policy.get("product_type") and policy["product_type"] != product_type:
            continue
        if policy.get("publisher_type") and policy["publisher_type"] != publisher_type:
            continue
        if policy.get("marketplace") and policy["marketplace"] != marketplace:
            continue
        candidates.append(policy)
    if not candidates:
        return {"platform_bps": 0, "fixed_fee_minor": 0, "source": "default"}
    best = max(candidates, key=specificity)
    return {"platform_bps": int(best.get("rate_bps", best.get("platform_bps", 0))),
            "fixed_fee_minor": int(best.get("fixed_fee_minor", 0)),
            "source": best.get("id", "policy")}


def payout_eligibility(*, balance_minor: int, minimum_minor: int,
                       held_minor: int = 0,
                       publisher_verified: bool = False,
                       require_verification: bool = True,
                       open_disputes: int = 0,
                       pending_refunds_minor: int = 0) -> tuple[bool, str]:
    """Configurable payout gate. No jurisdiction-specific claims."""
    available = balance_minor - held_minor - pending_refunds_minor
    if require_verification and not publisher_verified:
        return False, "publisher verification required"
    if open_disputes > 0:
        return False, "open disputes hold payout"
    if available < minimum_minor:
        return False, "balance below payout minimum"
    if available <= 0:
        return False, "no available balance"
    return True, "eligible"
