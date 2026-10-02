"""MP23: transparent recommendation foundation.

Rule-based suggestions with human-readable reasons. Signals are limited to
non-sensitive marketplace facts (publisher, categories, tags, type,
org-installed siblings). No personal attribute inference, no hidden
ranking: callers decide ordering and must label recommendation slots.
"""

from __future__ import annotations

from typing import Any


def recommend_for_listing(
    *,
    source: dict[str, Any],
    candidates: list[dict[str, Any]],
    installed_package_ids: list[str] | None = None,
    limit: int = 8,
) -> list[dict[str, Any]]:
    """Return [{listing, reasons[]}] for a detail page slot."""
    from openagent.marketplace.search import related_reasons

    installed = set(installed_package_ids or [])
    scored: list[tuple[int, dict[str, Any], list[str]]] = []
    for candidate in candidates:
        if str(candidate.get("id", "")) == str(source.get("id", "")):
            continue
        reasons = related_reasons(source, candidate)
        if str(candidate.get("package_id", "")) in installed:
            reasons.append("already installed by your organization")
        if not reasons:
            continue
        scored.append((len(reasons), candidate, reasons))
    scored.sort(key=lambda item: (-item[0], str(item[1].get("title", ""))))
    return [{"listing": item[1], "reasons": item[2]} for item in scored[:limit]]


def discovery_sections(
    *,
    featured: list[dict[str, Any]],
    official: list[dict[str, Any]],
    new: list[dict[str, Any]],
    popular: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Labeled homepage sections (labels travel with data, never implicit)."""
    return [
        {"key": "featured", "label": "Featured",
         "editorial": True, "items": featured},
        {"key": "official", "label": "Official packages",
         "editorial": False, "items": official},
        {"key": "new", "label": "New arrivals",
         "editorial": False, "items": new},
        {"key": "popular", "label": "Most installed",
         "editorial": False, "items": popular},
    ]
