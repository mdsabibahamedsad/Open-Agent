"""Routed agent communication: authorization → policy → delivery.

No direct unrestricted agent-to-agent database writes: all sends pass
through CommunicationService, which enforces org isolation, channel policy,
rate limits, message budgets, and audit (never logging secrets).
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional
from uuid import UUID

from openagent.management.types import (
    DEFAULT_MAX_COLLABORATION_REQUESTS,
    DEFAULT_MAX_DELEGATIONS_PER_RUN,
    DEFAULT_MAX_HANDOFFS_PER_RUN,
    DEFAULT_MAX_MESSAGES_PER_AGENT_PER_RUN,
    DEFAULT_MAX_MESSAGES_PER_TASK,
    ChannelType,
)
from openagent.orchestration.security import sanitize_dict
from openagent.orchestration.types import DEFAULT_MAX_MESSAGE_BYTES


@dataclass
class RouteDecision:
    allowed: bool
    reasons: List[str]


@dataclass
class ChannelPolicy:
    allowed_channels: List[ChannelType] = field(
        default_factory=lambda: [ChannelType.DIRECT, ChannelType.TEAM, ChannelType.MANAGER]
    )
    allow_broadcast: bool = False
    allow_cross_team: bool = False


def authorize_channel(
    channel: ChannelType,
    policy: ChannelPolicy,
    *,
    same_team: bool = True,
    is_manager_of_recipient: bool = False,
    is_escalation_target: bool = False,
) -> RouteDecision:
    if channel not in policy.allowed_channels:
        if channel == ChannelType.BROADCAST and policy.allow_broadcast:
            return RouteDecision(True, ["broadcast explicitly allowed"])
        if channel == ChannelType.ESCALATION and is_escalation_target:
            # Escalation delivery to the designated target is itself the
            # authorization: the chain resolved this recipient.
            return RouteDecision(True, ["escalation target explicitly routed"])
        return RouteDecision(False, [f"channel {channel.value} not allowed"])
    if channel == ChannelType.TEAM and not same_team and not policy.allow_cross_team:
        return RouteDecision(False, ["cross-team delivery denied"])
    if channel == ChannelType.MANAGER and not is_manager_of_recipient:
        return RouteDecision(False, ["not the recipient's manager"])
    if channel == ChannelType.ESCALATION and not is_escalation_target:
        return RouteDecision(False, ["not an escalation target"])
    return RouteDecision(True, [f"channel {channel.value} authorized"])


class MessageBudget:
    """Per-run counters: messages/task, messages/agent, collaboration,
    handoffs, delegations. Enforces backpressure before storms form."""

    def __init__(
        self,
        max_per_task: int = DEFAULT_MAX_MESSAGES_PER_TASK,
        max_per_agent: int = DEFAULT_MAX_MESSAGES_PER_AGENT_PER_RUN,
        max_collaborations: int = DEFAULT_MAX_COLLABORATION_REQUESTS,
        max_handoffs: int = DEFAULT_MAX_HANDOFFS_PER_RUN,
        max_delegations: int = DEFAULT_MAX_DELEGATIONS_PER_RUN,
    ):
        self.max_per_task = max_per_task
        self.max_per_agent = max_per_agent
        self.max_collaborations = max_collaborations
        self.max_handoffs = max_handoffs
        self.max_delegations = max_delegations
        self._per_task: Dict[str, int] = defaultdict(int)
        self._per_agent: Dict[str, int] = defaultdict(int)
        self._collaborations = 0
        self._handoffs = 0
        self._delegations = 0

    def check_message(self, *, task_id: Optional[str], agent_id: Optional[str],
                      size_bytes: int) -> tuple[bool, str]:
        if size_bytes > DEFAULT_MAX_MESSAGE_BYTES:
            return False, "message exceeds size limit; use artifact references"
        if task_id and self._per_task[task_id] >= self.max_per_task:
            return False, "message budget exhausted for task"
        if agent_id and self._per_agent[agent_id] >= self.max_per_agent:
            return False, "message budget exhausted for agent"
        return True, "within budget"

    def record_message(self, *, task_id: Optional[str], agent_id: Optional[str]) -> None:
        if task_id:
            self._per_task[task_id] += 1
        if agent_id:
            self._per_agent[agent_id] += 1

    def check_kind(self, kind: str) -> tuple[bool, str]:
        counters = {
            "collaboration": (self._collaborations, self.max_collaborations),
            "handoff": (self._handoffs, self.max_handoffs),
            "delegation": (self._delegations, self.max_delegations),
        }
        used, limit = counters.get(kind, (0, 0))
        if used >= limit:
            return False, f"{kind} budget exhausted"
        return True, "within budget"

    def record_kind(self, kind: str) -> None:
        if kind == "collaboration":
            self._collaborations += 1
        elif kind == "handoff":
            self._handoffs += 1
        elif kind == "delegation":
            self._delegations += 1


class RateLimiter:
    """Token-bucket per sender for backpressure."""

    def __init__(self, per_minute: int = 60):
        self.per_minute = per_minute
        self._hits: Dict[str, List[float]] = defaultdict(list)

    def check(self, sender: str) -> tuple[bool, str]:
        now = time.monotonic()
        window = [t for t in self._hits[sender] if now - t < 60.0]
        self._hits[sender] = window
        if len(window) >= self.per_minute:
            return False, "rate limit exceeded; backpressure applied"
        window.append(now)
        return True, "within rate"


PersistMessage = Callable[..., Awaitable[Any]]
AuditEvent = Callable[..., Awaitable[Any]]


class CommunicationService:
    """Central delivery layer used by managers, workers, and collaboration."""

    def __init__(
        self,
        persist: PersistMessage,
        audit: AuditEvent,
        *,
        budget: Optional[MessageBudget] = None,
        rate_limiter: Optional[RateLimiter] = None,
    ):
        self._persist = persist
        self._audit = audit
        self.budget = budget or MessageBudget()
        self.rate_limiter = rate_limiter or RateLimiter()

    async def send(
        self,
        *,
        organization_id: UUID,
        orchestration_run_id: UUID,
        sender_agent_id: Optional[UUID],
        recipient_agent_id: Optional[UUID],
        channel: ChannelType,
        policy: ChannelPolicy,
        message_type: str,
        payload: Dict[str, Any],
        task_id: Optional[UUID] = None,
        kind: str = "message",
        same_team: bool = True,
        is_manager_of_recipient: bool = False,
        is_escalation_target: bool = False,
    ) -> Any:
        route = authorize_channel(
            channel, policy, same_team=same_team,
            is_manager_of_recipient=is_manager_of_recipient,
            is_escalation_target=is_escalation_target,
        )
        if not route.allowed:
            raise CommunicationDenied("; ".join(route.reasons))
        sender_key = str(sender_agent_id) if sender_agent_id else "system"
        ok, reason = self.rate_limiter.check(sender_key)
        if not ok:
            raise CommunicationDenied(reason)
        import json

        size = len(json.dumps(payload, default=str).encode("utf-8"))
        ok, reason = self.budget.check_message(
            task_id=str(task_id) if task_id else None, agent_id=sender_key, size_bytes=size
        )
        if not ok:
            raise CommunicationDenied(reason)
        if kind != "message":
            ok, reason = self.budget.check_kind(kind)
            if not ok:
                raise CommunicationDenied(reason)
        cleaned = sanitize_dict(dict(payload or {}))
        record = await self._persist(
            organization_id=organization_id,
            orchestration_run_id=orchestration_run_id,
            sender_agent_id=sender_agent_id,
            recipient_agent_id=recipient_agent_id,
            task_id=task_id,
            channel=channel,
            message_type=message_type,
            payload=cleaned,
        )
        self.budget.record_message(
            task_id=str(task_id) if task_id else None, agent_id=sender_key
        )
        if kind != "message":
            self.budget.record_kind(kind)
        # Audit stores metadata only — never secret values (already sanitized,
        # and payload excluded by design).
        await self._audit(
            event="message_routed",
            organization_id=organization_id,
            orchestration_run_id=orchestration_run_id,
            channel=channel.value,
            message_type=message_type,
            size_bytes=size,
        )
        return record


class CommunicationDenied(Exception):
    pass
