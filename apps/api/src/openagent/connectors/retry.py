"""Provider-aware retry decisions (MP21).

Retry only appropriate errors and respect idempotency: non-idempotent
mutations are never auto-retried. Pure decision logic — execution lives in
the shared HTTP client.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from openagent.connectors.errors import ProviderError, ProviderErrorKind

RETRYABLE_KINDS = frozenset({
    ProviderErrorKind.RATE_LIMITED,
    ProviderErrorKind.PROVIDER_UNAVAILABLE,
    ProviderErrorKind.TIMEOUT,
    ProviderErrorKind.NETWORK_ERROR,
})

# 401 refreshes credentials once (handled by the caller); the retry itself
# is only safe for idempotent operations.
REFRESHABLE_KINDS = frozenset({ProviderErrorKind.AUTHENTICATION_ERROR})


@dataclass
class RetryDecision:
    retry: bool
    delay_seconds: float = 0.0
    reason: str = ""
    refresh_credential: bool = False


def decide_retry(error: ProviderError, *, attempt: int,
                 idempotent: bool,
                 retry_after: Optional[float] = None,
                 base_delay: float = 1.0,
                 max_delay: float = 60.0) -> RetryDecision:
    """Decide whether to retry. attempt is 0-based (already-failed tries)."""
    if error.retryable_hint is not None and not error.retryable_hint:
        return RetryDecision(False, reason="provider marked non-retryable")
    if error.kind in REFRESHABLE_KINDS:
        if attempt == 0:
            return RetryDecision(False, reason="refresh credential, then retry once",
                                 refresh_credential=True)
        return RetryDecision(False, reason="credential refresh already attempted")
    if error.kind not in RETRYABLE_KINDS:
        return RetryDecision(False, reason=f"{error.kind} is not retryable")
    if not idempotent and error.kind != ProviderErrorKind.RATE_LIMITED:
        # Rate-limit waits are safe (no resend yet); other retries resend.
        return RetryDecision(False, reason="non-idempotent mutation: no auto-retry")
    if retry_after is not None:
        delay = min(max(0.0, retry_after), max_delay)
        return RetryDecision(True, delay_seconds=delay, reason="provider retry-after")
    delay = min(base_delay * (2 ** attempt), max_delay)
    # Deterministic jitter substitute: attempt-parity offset (no RNG needed).
    delay = min(max_delay, delay + (0.25 if attempt % 2 else 0.0))
    return RetryDecision(True, delay_seconds=delay, reason=f"backoff attempt {attempt + 1}")
