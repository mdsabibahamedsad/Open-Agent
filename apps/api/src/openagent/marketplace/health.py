"""MP23: package health — explainable signals, no opaque scores.

Status is derived from observable facts: revocation, open advisories,
failed validation, dependency/install failures, review health. Every
status ships with ``reasons[]``; UNKNOWN means insufficient data.
"""

from __future__ import annotations

from typing import Any


def compute_health(
    *,
    revoked: bool = False,
    open_advisories: list[dict[str, Any]] | None = None,
    last_validation_passed: bool | None = None,
    install_success_rate: float | None = None,
    install_samples: int = 0,
    rating_average: float = 0.0,
    rating_count: int = 0,
    flagged_review_ratio: float = 0.0,
    deprecated: bool = False,
) -> dict[str, Any]:
    advisories = open_advisories or []
    if revoked:
        return {"status": "REVOKED",
                "reasons": ["package version has been revoked"]}
    critical = [a for a in advisories
                if str(a.get("severity", "")).upper() in ("HIGH", "CRITICAL")]
    if critical:
        return {"status": "AT_RISK",
                "reasons": [f"{len(critical)} open high/critical advisories"]}
    reasons: list[str] = []
    if last_validation_passed is False:
        reasons.append("latest validation failed")
    if install_samples >= 5 and (install_success_rate or 0.0) < 0.7:
        reasons.append(
            f"install success rate {install_success_rate:.0%} "
            f"over {install_samples} attempts")
    if rating_count >= 5 and rating_average < 2.5:
        reasons.append(f"low rating {rating_average:.1f} over {rating_count} reviews")
    if flagged_review_ratio > 0.3:
        reasons.append("elevated share of flagged reviews")
    if advisories:
        reasons.append(f"{len(advisories)} open advisories")
    if deprecated:
        reasons.append("package deprecated by publisher")
    if not reasons:
        if last_validation_passed is None and install_samples == 0:
            return {"status": "UNKNOWN", "reasons": ["insufficient data"]}
        return {"status": "HEALTHY", "reasons": ["no negative signals"]}
    if last_validation_passed is False or critical:
        return {"status": "AT_RISK", "reasons": reasons}
    return {"status": "WARNING", "reasons": reasons}
