"""MP23: review eligibility + anti-abuse signals.

Preferred reviews are verified-use (linked installation). Anti-abuse is
signal-based (duplicates, self-review, velocity, content patterns) with
rate limits at the API layer — no invasive profiling.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

# Velocity thresholds (tunable): more than this many reviews in the window
# from one account is flagged for moderation instead of published.
REVIEW_VELOCITY_LIMIT = 5
REVIEW_VELOCITY_WINDOW_HOURS = 24

_SPAM_PATTERNS = (
    "http://", "https://", "www.", "buy now", "click here", "free money",
    "crypto", "discount code",
)


def check_eligibility(
    *,
    has_installation: bool,
    documented_usage: bool = False,
    allow_unverified: bool = True,
) -> tuple[bool, bool, str]:
    """Return (eligible, verified_use, reason)."""
    if has_installation:
        return True, True, "verified installation"
    if documented_usage:
        return True, False, "documented usage"
    if allow_unverified:
        return True, False, "unverified"
    return False, False, "review requires installation or documented usage"


def check_self_review(*, reviewer_user_id: str, publisher_member_ids: list[str]) -> bool:
    """True when the reviewer is on the publisher team (self-review)."""
    return str(reviewer_user_id) in {str(m) for m in publisher_member_ids}


def check_velocity(*, recent_count: int,
                   limit: int = REVIEW_VELOCITY_LIMIT) -> tuple[bool, str]:
    """True when the account exceeded the review velocity threshold."""
    if recent_count >= limit:
        return True, (
            f"more than {limit} reviews in {REVIEW_VELOCITY_WINDOW_HOURS}h; "
            "held for moderation")
    return False, ""


def check_spam_signals(*, title: str, body: str) -> list[str]:
    """Heuristic spam signals (advisory; moderation decides)."""
    haystack = f"{title or ''}\n{body or ''}".lower()
    signals = [f"contains {pattern!r}" for pattern in _SPAM_PATTERNS
               if pattern in haystack]
    if len(body or "") > 5000:
        signals.append("excessively long body")
    if body and len(set(body.split())) < 5 and len(body.split()) > 20:
        signals.append("highly repetitive content")
    return signals


def velocity_window_start(now: datetime | None = None) -> datetime:
    base = now or datetime.now(timezone.utc)
    return base - timedelta(hours=REVIEW_VELOCITY_WINDOW_HOURS)


def decide_initial_status(
    *,
    eligible: bool,
    self_review: bool,
    velocity_exceeded: bool,
    spam_signals: list[str],
) -> tuple[str, str]:
    """Map abuse signals to an initial review status + reason."""
    if not eligible:
        return "PENDING", "eligibility not established"
    if self_review:
        return "FLAGGED", "possible publisher self-review"
    if velocity_exceeded:
        return "FLAGGED", "review velocity exceeded"
    if spam_signals:
        return "PENDING", f"spam signals: {', '.join(spam_signals[:3])}"
    return "PUBLISHED", ""
