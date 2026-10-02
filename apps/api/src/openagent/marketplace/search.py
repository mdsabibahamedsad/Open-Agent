"""MP23: marketplace discovery query model + SQL search builder.

Provider-neutral: the normalized ``MarketplaceSearchQuery`` can be executed
by the built-in SQL builder today and by pgvector/OpenSearch/ES providers
later without changing the API. Only PUBLISHED listings are publicly
searchable; featured/organic separation is explicit (badges returned, never
hidden boosts).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from openagent.marketplace.types import SORT_COLUMNS, SearchSort


@dataclass
class MarketplaceSearchQuery:
    text: str = ""
    marketplace_id: str = ""
    category: str = ""
    tags: list[str] = field(default_factory=list)
    package_types: list[str] = field(default_factory=list)
    publishers: list[str] = field(default_factory=list)
    pricing: list[str] = field(default_factory=list)
    license: str = ""
    trust: list[str] = field(default_factory=list)
    security_max: str = ""
    compatibility: str = ""
    min_rating: float = 0.0
    badges: list[str] = field(default_factory=list)
    sort: str = SearchSort.RELEVANCE.value
    page: int = 1
    page_size: int = 20

    def normalized(self) -> "MarketplaceSearchQuery":
        self.text = (self.text or "").strip()[:200]
        self.page = max(1, int(self.page or 1))
        self.page_size = min(100, max(1, int(self.page_size or 20)))
        if self.sort not in {s.value for s in SearchSort}:
            self.sort = SearchSort.RELEVANCE.value
        return self


def build_listing_filters(query: MarketplaceSearchQuery) -> dict[str, Any]:
    """Return a JSON-serializable filter spec for SQL or future providers."""
    return {
        "text": query.text,
        "marketplace_id": query.marketplace_id,
        "category": query.category,
        "tags": list(query.tags),
        "package_types": [t.upper() for t in query.package_types],
        "publishers": list(query.publishers),
        "pricing": [p.upper() for p in query.pricing],
        "license": query.license,
        "trust": [t.upper() for t in query.trust],
        "security_max": query.security_max.upper(),
        "min_rating": float(query.min_rating or 0.0),
        "badges": [b.upper() for b in query.badges],
        "sort": query.sort,
        "page": query.page,
        "page_size": query.page_size,
    }


def relevance_score(*, title: str, description: str, tags: list[str],
                    text: str) -> float:
    """Transparent text relevance (no hidden boosts, no personalization)."""
    needle = (text or "").strip().lower()
    if not needle:
        return 0.0
    score = 0.0
    if needle in (title or "").lower():
        score += 3.0
    if needle in (description or "").lower():
        score += 1.0
    joined_tags = " ".join(tags or []).lower()
    if needle in joined_tags:
        score += 1.5
    for token in needle.split():
        if token and token in (title or "").lower():
            score += 0.5
    return score


def sort_key(sort: str) -> tuple[str, bool] | None:
    """Map a sort option to (column, descending); None = relevance."""
    if sort == SearchSort.PRICE_LOW_TO_HIGH.value:
        return ("min_price", False)
    if sort == SearchSort.PRICE_HIGH_TO_LOW.value:
        return ("min_price", True)
    return SORT_COLUMNS.get(sort)


def related_reasons(source: dict[str, Any], candidate: dict[str, Any]) -> list[str]:
    """Explainable related-package signals (labels only, no scores hidden)."""
    reasons: list[str] = []
    if source.get("publisher_id") and source.get("publisher_id") == candidate.get("publisher_id"):
        reasons.append("same publisher")
    shared_tags = set(source.get("tags", []) or []) & set(candidate.get("tags", []) or [])
    if shared_tags:
        reasons.append(f"shared tags: {', '.join(sorted(shared_tags)[:3])}")
    if source.get("category") and source.get("category") == candidate.get("category"):
        reasons.append("same category")
    if source.get("package_type") and source.get("package_type") == candidate.get("package_type"):
        reasons.append("same package type")
    return reasons
