"""Rate-limit tracking per connection (MP21).

Parses provider headers (requests/remaining/reset/retry-after), enforces
per-action configured limits, and exposes wait/backoff/queue/fail strategies.
State is caller-owned (DB row or memory) — this module is pure logic.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RateLimitState:
    limit: Optional[int] = None
    remaining: Optional[int] = None
    reset_at_epoch: Optional[float] = None
    retry_after_seconds: Optional[float] = None
    window_requests: int = 0
    window_started_epoch: float = field(default_factory=time.time)
    configured_per_minute: int = 60


@dataclass
class RateLimitDecision:
    allowed: bool
    wait_seconds: float = 0.0
    strategy: str = "fail"  # wait|backoff|queue|fail
    reason: str = ""


def parse_headers(headers: dict[str, str]) -> RateLimitState:
    """Parse common provider rate-limit headers (GitHub, Stripe, Slack...)."""
    from contextlib import suppress
    lowered = {str(k).lower(): str(v) for k, v in (headers or {}).items()}
    state = RateLimitState()
    for key in ("x-ratelimit-limit", "ratelimit-limit", "x-rate-limit-limit"):
        if key in lowered:
            with suppress(ValueError):
                state.limit = int(float(lowered[key]))
    for key in ("x-ratelimit-remaining", "ratelimit-remaining",
                "x-rate-limit-remaining"):
        if key in lowered:
            with suppress(ValueError):
                state.remaining = int(float(lowered[key]))
    for key in ("x-ratelimit-reset", "ratelimit-reset", "x-rate-limit-reset"):
        if key in lowered:
            with suppress(ValueError):
                value = float(lowered[key])
                # Providers send epoch seconds or epoch millis.
                state.reset_at_epoch = value / 1000.0 if value > 1e12 else value
    retry_after = lowered.get("retry-after")
    if retry_after is not None:
        with suppress(ValueError):
            state.retry_after_seconds = max(0.0, float(retry_after))
    return state


def check(state: RateLimitState, *, now: Optional[float] = None,
          strategy: str = "wait") -> RateLimitDecision:
    """Decide whether a call may proceed now."""
    now = now if now is not None else time.time()
    if state.retry_after_seconds:
        return RateLimitDecision(False, state.retry_after_seconds, "wait",
                                 "provider retry-after")
    if state.remaining is not None and state.remaining <= 0:
        wait = 0.0
        if state.reset_at_epoch:
            wait = max(0.0, state.reset_at_epoch - now)
        if strategy == "fail":
            return RateLimitDecision(False, wait, "fail", "rate limit exhausted")
        return RateLimitDecision(False, wait, "wait", "rate limit exhausted")
    # Configured per-minute cap (sliding 60s window).
    elapsed = now - state.window_started_epoch
    if elapsed >= 60:
        state.window_started_epoch = now
        state.window_requests = 0
    if state.window_requests >= max(1, state.configured_per_minute):
        wait = max(0.0, 60 - elapsed)
        if strategy == "fail":
            return RateLimitDecision(False, wait, "fail", "connector quota exhausted")
        return RateLimitDecision(False, wait, "wait", "connector quota exhausted")
    return RateLimitDecision(True, 0.0, "wait", "allowed")


def record_call(state: RateLimitState, *, now: Optional[float] = None) -> None:
    now = now if now is not None else time.time()
    if now - state.window_started_epoch >= 60:
        state.window_started_epoch = now
        state.window_requests = 0
    state.window_requests += 1
    if state.remaining is not None:
        state.remaining = max(0, state.remaining - 1)
