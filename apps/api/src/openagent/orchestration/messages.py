"""Internal agent-to-agent communication abstraction.

Protocol-neutral adapter: internal bus today, external A2A-compatible
transports later. No external protocol is implemented in this phase.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from openagent.orchestration.types import AgentMessageType


@dataclass
class AgentCommunicationEnvelope:
    id: str = field(default_factory=lambda: f"msg_{uuid4().hex[:16]}")
    orchestration_run_id: str = ""
    sender_agent_id: Optional[str] = None
    recipient_agent_id: Optional[str] = None
    message_type: AgentMessageType = AgentMessageType.STATUS_UPDATE
    task_id: Optional[str] = None
    payload: Dict[str, Any] = field(default_factory=dict)
    correlation_id: Optional[str] = None
    reply_to: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class AgentCommunicationAdapter(ABC):
    """Transport for agent messages. Implementations must preserve ordering
    per (orchestration_run_id, task_id) and never leak cross-org messages."""

    @abstractmethod
    async def send(self, envelope: AgentCommunicationEnvelope) -> AgentCommunicationEnvelope:
        ...

    @abstractmethod
    async def history(
        self,
        orchestration_run_id: str,
        *,
        task_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[AgentCommunicationEnvelope]:
        ...


class InMemoryCommunicationAdapter(AgentCommunicationAdapter):
    """Process-local adapter used in tests and single-worker dev."""

    def __init__(self) -> None:
        self._store: Dict[str, List[AgentCommunicationEnvelope]] = {}

    async def send(self, envelope: AgentCommunicationEnvelope) -> AgentCommunicationEnvelope:
        self._store.setdefault(envelope.orchestration_run_id, []).append(envelope)
        return envelope

    async def history(
        self,
        orchestration_run_id: str,
        *,
        task_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[AgentCommunicationEnvelope]:
        items = self._store.get(orchestration_run_id, [])
        if task_id:
            items = [m for m in items if m.task_id == task_id]
        return items[-limit:]
