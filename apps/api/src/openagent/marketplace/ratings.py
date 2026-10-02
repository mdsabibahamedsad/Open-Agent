"""MP23: rating aggregation (factual, publisher-immutable).

Aggregates are recomputed only from valid reviews
(status PUBLISHED, not REMOVED/HIDDEN) by writers, never by publishers.
"""

from __future__ import annotations

from typing import Any


def aggregate(ratings: list[int], verified_flags: list[bool] | None = None) -> dict[str, Any]:
    """Compute average/count/distribution from a list of 1-5 ratings."""
    clean = [int(r) for r in ratings if isinstance(r, int) and 1 <= int(r) <= 5]
    distribution = {str(star): 0 for star in range(1, 6)}
    for value in clean:
        distribution[str(value)] += 1
    count = len(clean)
    average = round(sum(clean) / count, 2) if count else 0.0
    verified = 0
    if verified_flags is not None:
        verified = sum(1 for flag, value in zip(verified_flags, ratings)
                       if flag and isinstance(value, int) and 1 <= int(value) <= 5)
    return {
        "rating_average": average,
        "rating_count": count,
        "rating_distribution": distribution,
        "verified_review_count": verified,
    }
