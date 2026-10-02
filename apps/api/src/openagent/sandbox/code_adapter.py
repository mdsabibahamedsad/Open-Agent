"""Code Agent -> Sandbox adapter (MP18 migration, §59/§93).

Routes the ``CodeExecutionProvider`` interface through the Sandbox Manager
so repository test/lint/build/typecheck execution is container-isolated.
No direct host execution remains on this path in production.

The legacy ``LocalConfinedExecutionProvider`` in :mod:`openagent.code.service`
is retained ONLY as an explicit dev-only fallback (``SANDBOX_PROVIDER=local``
+ non-production + ``SANDBOX_ALLOW_LOCAL_FALLBACK=true``); production fails
closed instead of silently falling back.
"""

from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

import structlog

logger = structlog.get_logger("sandbox.code_adapter")

__all__ = ["SandboxCodeExecutionProvider"]


class SandboxCodeExecutionProvider:
    """``CodeExecutionProvider``-compatible transport over SandboxManager.

    Holds a prepared sandbox per workspace root. The Code Agent's
    ``run_command``/``run_tests`` flow is unchanged; only the transport is
    container-isolated.
    """

    def __init__(self, sandbox_manager_factory,
                 organization_id: UUID,
                 task_id: Optional[UUID] = None,
                 actor: Optional[UUID] = None,
                 owner: Optional[str] = None):
        self._factory = sandbox_manager_factory
        self._org = organization_id
        self._task_id = task_id
        self._actor = actor
        self._owner = owner or (f"task:{task_id}" if task_id else "code-agent")
        self._sandboxes: dict[str, str] = {}  # workspace host path -> sandbox id

    def _manager(self):
        return self._factory()

    @staticmethod
    def _profile_for(code_profile: str) -> str:
        mapping = {"TEST": "TEST", "LINT": "LINT", "TYPECHECK": "TYPECHECK",
                   "BUILD": "BUILD", "PACKAGE": "PACKAGE",
                   "MIGRATION": "CUSTOM", "CUSTOM": "CUSTOM",
                   "DEV_SERVER": "DEVELOPMENT"}
        return mapping.get((code_profile or "TEST").upper(), "TEST")

    @staticmethod
    def _ready_status(status: Any) -> bool:
        # SQLAlchemy may hand back enum members or raw strings depending on
        # backend/driver; normalize through .value before comparing.
        value = getattr(status, "value", status)
        return value in ("READY", "RUNNING")

    async def _sandbox_for(self, workspace_host_path: str,
                           code_profile: str) -> Any:
        key = workspace_host_path
        manager = self._manager()
        if key in self._sandboxes:
            try:
                sb = await manager.get_sandbox(UUID(self._sandboxes[key]), self._org)
                if self._ready_status(sb.status):
                    return sb
            except Exception:
                self._sandboxes.pop(key, None)
        sb = await manager.create_sandbox(
            organization_id=self._org,
            profile=self._profile_for(code_profile),
            owner_id=self._actor, task_id=self._task_id,
            workspace_host_path=workspace_host_path,
            workspace_mode="WORKSPACE_RW", ttl_seconds=3600,
            labels={"origin": "code-agent"})
        if not self._ready_status(sb.status):
            sb = await manager.start_sandbox(sb.id, self._org, self._actor)
        self._sandboxes[key] = str(sb.id)
        return sb

    async def execute(self, *, command: str, cwd: str, profile: str,
                      timeout_seconds: Optional[int] = None) -> Any:
        """Same shape as ``CodeService.ExecutionOutcome`` (duck-typed)."""
        from openagent.code.service import CodeSecurityError, ExecutionOutcome
        from openagent.sandbox.providers import SandboxError
        from openagent.sandbox.service import SandboxPolicyDenied as SbxDenied
        manager = self._manager()
        try:
            sb = await self._sandbox_for(cwd, profile)
            result = await manager.execute(
                sandbox_id=sb.id, organization_id=self._org, command=command,
                workdir="/workspace", task_id=self._task_id, actor=self._actor,
                owner=self._owner, timeout_seconds=timeout_seconds)
        except SandboxError as e:
            raise CodeSecurityError(f"Sandbox execution failed: {e}") from e
        except SbxDenied as e:
            from openagent.code.service import CodePolicyDenied
            raise CodePolicyDenied(str(e)) from e
        status = result.get("status")
        if status == "POLICY_DENIED":
            from openagent.code.service import CodePolicyDenied
            raise CodePolicyDenied(result.get("reason", "sandbox policy denied"))
        if status == "WAITING_FOR_APPROVAL":
            from openagent.code.service import CodePolicyDenied
            raise CodePolicyDenied(
                "Sandbox execution parked for approval: "
                + "; ".join(result.get("risk_reasons", [])))
        # Full (profile-capped) output flows back so CodeService keeps its
        # tail + storage-ref behavior; sandbox storage holds the same bytes.
        return ExecutionOutcome(
            exit_code=int(result.get("exit_code", 1)),
            stdout=result.get("stdout") or "",
            stderr=result.get("stderr") or "",
            duration_ms=int(result.get("duration_ms", 0)),
            timed_out=bool(result.get("timed_out", False)))
