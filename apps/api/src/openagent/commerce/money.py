"""MP24: exact monetary arithmetic — integer minor units only.

Never use float for money. All amounts are ``int`` minor units (cents for
USD/EUR/GBP, yen for JPY). Helpers convert from user-facing decimal strings
without ever touching binary floating point.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from openagent.commerce.types import CURRENCY_EXPONENTS


class MoneyError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def normalize_currency(currency: str) -> str:
    code = str(currency or "").strip().upper()
    if len(code) != 3 or not code.isalpha():
        raise MoneyError("BAD_CURRENCY", f"invalid ISO currency code: {currency!r}")
    return code


def exponent_for(currency: str) -> int:
    return CURRENCY_EXPONENTS.get(normalize_currency(currency), 2)


def parse_amount(decimal_amount: str, currency: str) -> int:
    """Parse ``"9.99"`` + ``USD`` -> ``999``. Raises MoneyError on bad input."""
    code = normalize_currency(currency)
    try:
        value = Decimal(str(decimal_amount).strip())
    except (InvalidOperation, ValueError, AttributeError) as exc:
        raise MoneyError("BAD_AMOUNT", f"invalid amount: {decimal_amount!r}") from exc
    if value.is_nan() or value.is_infinite():
        raise MoneyError("BAD_AMOUNT", f"invalid amount: {decimal_amount!r}")
    if value < 0:
        raise MoneyError("BAD_AMOUNT", "amount must be >= 0")
    exp = exponent_for(code)
    quantum = Decimal(1).scaleb(-exp)  # 0.01 for exponent 2
    minor = (value / quantum).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    # Enforce at most `exp` decimals were meaningful (reject 9.999 for USD).
    if (value - (minor * quantum)) != 0:
        raise MoneyError("BAD_PRECISION",
                         f"too many decimals for {code}: {decimal_amount!r}")
    result = int(minor)
    if result > 10**15:
        raise MoneyError("AMOUNT_TOO_LARGE", "amount exceeds supported range")
    return result


def format_amount(amount_minor: int, currency: str) -> str:
    code = normalize_currency(currency)
    if amount_minor < 0:
        raise MoneyError("BAD_AMOUNT", "amount must be >= 0")
    exp = exponent_for(code)
    if exp == 0:
        return str(amount_minor)
    quantum = Decimal(1).scaleb(-exp)
    return str((Decimal(amount_minor) * quantum).quantize(quantum))


def add(a: int, b: int) -> int:
    _check(a)
    _check(b)
    return a + b


def subtract(a: int, b: int) -> int:
    _check(a)
    _check(b)
    result = a - b
    if result < 0:
        raise MoneyError("NEGATIVE_RESULT", "subtraction would go negative")
    return result


def percent_of(amount_minor: int, basis_points: int) -> int:
    """Floor(amount * bps / 10000) — deterministic, no floats."""
    _check(amount_minor)
    if not 0 <= basis_points <= 10000:
        raise MoneyError("BAD_BPS", "basis points must be 0..10000")
    return (amount_minor * basis_points) // 10000


def prorate(amount_minor: int, used: int, total: int) -> int:
    if total <= 0 or used < 0:
        raise MoneyError("BAD_PRORATION", "invalid proration window")
    return (amount_minor * min(used, total)) // total


def _check(value: int) -> None:
    if not isinstance(value, bool) and isinstance(value, int):
        if value < 0:
            raise MoneyError("BAD_AMOUNT", "amount must be >= 0")
        return
    raise MoneyError("BAD_AMOUNT", f"amount must be int minor units, got {value!r}")
