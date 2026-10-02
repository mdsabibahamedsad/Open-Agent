"""Supervisor: monitors runs, enforces budgets, handles failures.

The supervisor never bypasses policy: every decision (retry, reassign,
pause, escalate) is returned as a recommendation the executor applies
through the same authorized paths as normal execution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

from openagent.orchestration.types import OrchTaskStatus


@dataclass
class TaskSnapshot:
    task_id: str
    status: OrchTaskStatus
    retry_count: int
    max_retries: int
    last_heartbeat_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    timeout_seconds: int = 600
    delegation_chain: List[str] = field(default_factory=list)


@dataclass
class SupervisorDecision:
    action: str  # retry | reassign | skip | fail_parent | escalate | pause | none
    task_id: Optional[str] = None
    reason: str = ""


class AgentSupervisor:
    def __init__(
        self,
        *,
        stalled_after_seconds: int = 300,
        max_identical_progress: int = 5,  # reserved for progress-signal analysis
    ):
        self.stalled_after_seconds = stalled_after_seconds
        self.max_identical_progress = max_identical_progress

    async def supervise(
        self,
        snapshots: List[TaskSnapshot],
        *,
        budget_exceeded: bool = False,
        loop_detected: bool = False,
    ) -> List[SupervisorDecision]:
        decisions: List[SupervisorDecision] = []
        now = datetime.now(timezone.utc)
        if budget_exceeded:
            decisions.append(SupervisorDecision("pause", None, "budget exceeded"))
            return decisions
        if loop_detected:
            decisions.append(SupervisorDecision("escalate", None, "delegation loop detected"))
            return decisions
        for snap in snapshots:
            stalled = self._is_stalled(snap, now)
            if snap.status in (OrchTaskStatus.FAILED, OrchTaskStatus.TIMED_OUT):
                if snap.retry_count < snap.max_retries:
                    decisions.append(
                        SupervisorDecision("retry", snap.task_id, "within retry budget")
                    )
                else:
                    decisions.append(
                        SupervisorDecision("reassign", snap.task_id, "retries exhausted; reassign")
                    )
            elif stalled and snap.status in (OrchTaskStatus.RUNNING, OrchTaskStatus.WAITING):
                decisions.append(
                    SupervisorDecision("reassign", snap.task_id, "stalled: no heartbeat/progress")
                )
        return decisions

    def _is_stalled(self, snap: TaskSnapshot, now: datetime) -> bool:
        ref = snap.last_heartbeat_at or snap.started_at
        if ref is None:
            return False
        if ref.tzinfo is None:
            ref = ref.replace(tzinfo=timezone.utc)
        elapsed = (now - ref).total_seconds()
        timeout = min(snap.timeout_seconds, self.stalled_after_seconds * 3)
        return elapsed > max(self.stalled_after_seconds, timeout)

    def detect_delegation_loop(self, chain: List[str]) -> bool:
        """A -> B -> A or repeated agent in chain indicates a loop."""
        return len(chain) != len(set(chain))
