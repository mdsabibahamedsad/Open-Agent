"""MP22: provider-neutral catalog search abstraction.

Local deployments run on SQL filtering (no external service required).
The :class:`CatalogProvider` protocol lets future phases plug in pgvector,
Elasticsearch/OpenSearch or hosted semantic search without changing the
API or UI. Ranking is deliberately transparent: trust rank, then update
recency, then name — no fake popularity algorithms.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class CatalogQuery:
    text: str = ""
    categories: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    types: list[str] = field(default_factory=list)
    authors: list[str] = field(default_factory=list)
    trust: list[str] = field(default_factory=list)
    security_max_risk: str = ""
    official_only: bool = False
    installed_only: bool = False
    organization_id: str = ""
    page: int = 1
    page_size: int = 20


@dataclass
class CatalogEntry:
    package_id: str
    slug: str
    name: str
    description: str
    type: str
    version: str
    trust: str
    visibility: str
    official: bool
    categories: list[str]
    tags: list[str]
    author: str
    risk: str
    installed: bool
    updated_at: str
    score: float = 0.0


class CatalogProvider(Protocol):
    name: str

    def search(self, query: CatalogQuery) -> tuple[list[CatalogEntry], int]:
        ...


def rank_entries(entries: list[CatalogEntry], text: str) -> list[CatalogEntry]:
    """Transparent ranking: text match, then trust, then recency, then name."""
    from openagent.packages.types import TRUST_RANK

    needle = text.strip().lower()

    def score(entry: CatalogEntry) -> tuple[int, int, str, str]:
        haystack = f"{entry.name} {entry.description} {' '.join(entry.tags)}".lower()
        text_score = 0 if not needle else (2 if needle in entry.name.lower() else (1 if needle in haystack else -1))
        return (text_score, TRUST_RANK.get(entry.trust, 0), entry.updated_at, entry.name.lower())

    ranked = sorted(entries, key=score, reverse=True)
    if needle:
        ranked = [e for e in ranked if needle in f"{e.name} {e.description} {' '.join(e.tags)}".lower()]
    for position, entry in enumerate(ranked):
        entry.score = float(len(ranked) - position)
    return ranked


def apply_filters(entries: list[CatalogEntry], query: CatalogQuery) -> list[CatalogEntry]:
    """In-memory filter pass shared by SQL and future providers."""
    result = list(entries)
    if query.types:
        wanted = {t.upper() for t in query.types}
        result = [e for e in result if e.type.upper() in wanted]
    if query.categories:
        wanted = set(query.categories)
        result = [e for e in result if wanted & set(e.categories)]
    if query.tags:
        wanted = set(query.tags)
        result = [e for e in result if wanted & set(e.tags)]
    if query.authors:
        wanted = {a.lower() for a in query.authors}
        result = [e for e in result if e.author.lower() in wanted]
    if query.trust:
        wanted = {t.upper() for t in query.trust}
        result = [e for e in result if e.trust.upper() in wanted]
    if query.official_only:
        result = [e for e in result if e.official]
    if query.installed_only:
        result = [e for e in result if e.installed]
    if query.security_max_risk:
        order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
        ceiling = order.get(query.security_max_risk.upper(), 3)
        result = [e for e in result if order.get(e.risk.upper(), 3) <= ceiling]
    return rank_entries(result, query.text)


class InMemoryCatalogProvider:
    """Local-first provider used by tests and single-node deployments."""

    name = "local"

    def __init__(self, entries: list[CatalogEntry] | None = None):
        self._entries = entries or []

    def index(self, entry: CatalogEntry) -> None:
        self._entries = [e for e in self._entries if e.package_id != entry.package_id]
        self._entries.append(entry)

    def search(self, query: CatalogQuery) -> tuple[list[CatalogEntry], int]:
        matches = apply_filters(self._entries, query)
        total = len(matches)
        start = (max(query.page, 1) - 1) * max(query.page_size, 1)
        return matches[start:start + query.page_size], total


def to_entry(payload: dict[str, Any]) -> CatalogEntry:
    return CatalogEntry(
        package_id=str(payload.get("package_id", "")),
        slug=str(payload.get("slug", "")),
        name=str(payload.get("name", "")),
        description=str(payload.get("description", "")),
        type=str(payload.get("type", "")),
        version=str(payload.get("version", "")),
        trust=str(payload.get("trust", "UNTRUSTED")),
        visibility=str(payload.get("visibility", "PRIVATE")),
        official=bool(payload.get("official", False)),
        categories=list(payload.get("categories", []) or []),
        tags=list(payload.get("tags", []) or []),
        author=str(payload.get("author", "")),
        risk=str(payload.get("risk", "LOW")),
        installed=bool(payload.get("installed", False)),
        updated_at=str(payload.get("updated_at", "")),
    )
