"""Boundary interfaces for MP15 (Memory), MP19 (Approval), MP20 (Evaluator).

Management code depends on these abstractions — never on concrete future
implementations, and never builds a duplicate memory/approval/evaluator.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

# Re-export MP19/MP20 boundaries from their home modules so consumers have
# a single import surface.
from openagent.management.escalation import ApprovalPolicy, ApprovalRequestHook  # noqa: F401
from openagent.management.review import EvaluationHook, QualityGate, ReviewProvider  # noqa: F401
from openagent.management.embedding_providers import EmbeddingProvider, EmbeddingResult  # noqa: F401


class ContextProvider(ABC):
    """Summaries / references for prompt construction (MP15 extends)."""

    @abstractmethod
    def summarize(self, state: Dict[str, Any]) -> str:
        ...


class MemoryProvider(ABC):
    """Persistent memory boundary (implemented in MP15)."""

    @abstractmethod
    async def recall(self, *, agent_id: str, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        ...

    @abstractmethod
    async def remember(self, *, agent_id: str, content: Dict[str, Any],
                       importance: float = 0.5) -> str:
        ...


class ArtifactProvider(ABC):
    """Artifact storage boundary (references preferred over copies)."""

    @abstractmethod
    async def store_reference(self, *, name: str, kind: str, location: str,
                              size_bytes: int = 0) -> str:
        ...

    @abstractmethod
    async def resolve_reference(self, *, reference: str) -> Optional[Dict[str, Any]]:
        ...


class NullContextProvider(ContextProvider):
    def summarize(self, state: Dict[str, Any]) -> str:
        return ""


__all__ = [
    "ContextProvider",
    "MemoryProvider",
    "ArtifactProvider",
    "NullContextProvider",
    "EmbeddingProvider",
    "EmbeddingResult",
]
