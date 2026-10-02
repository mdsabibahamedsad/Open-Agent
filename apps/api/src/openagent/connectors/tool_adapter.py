"""Tool Runtime adapter for connector actions (MP21).

Registers connector actions as runtime ToolDefinitions (compact discovery)
and executes them through ConnectorEngine — the same single gate as the API
path. Context must carry db + organization_id (+ user/approval when present);
missing context fails closed.
"""

from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

import structlog

from openagent.runtime.tools import ToolDefinition, ToolExecutor

logger = structlog.get_logger("openagent.connectors.tool_adapter")


def tool_definition_for(connector_id: str, action: Any,
                        manifest_version: str) -> ToolDefinition:
    risk = action.risk_level.value if hasattr(action.risk_level, "value") \
        else str(action.risk_level)
    return ToolDefinition(
        id=f"connector:{action.id}",
        name=action.id,  # e.g. github.create_issue — compact for model context
        description=(action.description or action.name)[:300],
        input_schema=dict(action.input_schema or {"type": "object"}),
        output_schema=dict(action.output_schema or {}),
        capabilities=list(action.required_capabilities or []),
        risk_level=str(risk).lower(),
        executor_id="connector",
        version=manifest_version,
        metadata={"connector": connector_id, "action": action.id,
                  "connector_action": True,
                  "required_capabilities": list(
                      action.required_capabilities or [])})


class ConnectorToolExecutor(ToolExecutor):
    """Dynamic executor: supported tools + schemas follow the registry."""

    def __init__(self):
        self._tools: dict[str, str] = {}  # action_id -> connector_id
        self._versions: dict[str, str] = {}

    @property
    def executor_id(self) -> str:
        return "connector"

    @property
    def supported_tools(self) -> list[str]:
        return sorted(self._tools)

    def sync_from_registry(self) -> int:
        """Load all registry actions. Returns count (lazy, cheap)."""
        from openagent.connectors.providers import provider_ids, register_official
        if not provider_ids():
            register_official()
        from openagent.connectors.registry import registry
        count = 0
        for manifest in registry.list(include_disabled=True):
            for action in manifest.actions:
                self._tools[action.id] = manifest.id
                self._versions[action.id] = manifest.version
                count += 1
        return count

    def get_tool_schema(self, tool_name: str) -> Optional[dict[str, Any]]:
        from openagent.connectors.registry import registry
        entry = registry.action_definition(tool_name)
        if entry is None:
            return None
        return dict(entry["action"].get("input_schema", {}) or {})

    def list_tools(self) -> list[dict[str, Any]]:
        return [{"name": name, "schema": self.get_tool_schema(name) or {}}
                for name in self.supported_tools]

    async def validate_arguments(self, tool_name: str,
                                 arguments: dict[str, Any]) -> bool:
        from openagent.evaluator.deterministic import validate_json_schema
        schema = self.get_tool_schema(tool_name)
        if schema is None:
            return False
        return not validate_json_schema(arguments or {}, schema)

    async def execute(self, tool_name: str, arguments: dict[str, Any],
                      context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        from openagent.connectors.engine import ConnectorEngine
        from openagent.connectors.types import ConnectorExecutionContext
        ctx = context or {}
        db = ctx.get("db")
        organization_id = ctx.get("organization_id")
        if db is None or organization_id is None:
            return {"status": "error", "error": "Connector execution requires "
                                               "db + organization context",
                    "error_code": "NO_CONTEXT"}
        connector_id = self._tools.get(tool_name)
        if connector_id is None:
            # Lazy sync once before giving up (registry may have loaded late).
            self.sync_from_registry()
            connector_id = self._tools.get(tool_name)
        if connector_id is None:
            return {"status": "error",
                    "error": f"Unknown connector action '{tool_name}'",
                    "error_code": "UNKNOWN_ACTION"}
        try:
            org_uuid = organization_id if isinstance(organization_id, UUID) \
                else UUID(str(organization_id))
        except ValueError:
            return {"status": "error", "error": "Invalid organization context",
                    "error_code": "NO_CONTEXT"}
        connection_id = (arguments or {}).get("connection_id", "")
        if not connection_id:
            # Resolve default connection like the API path: newest CONNECTED
            # connection the caller may actually use (deterministic order).
            from sqlalchemy import select

            from openagent.db.models.connector import ConnectionStatus, ConnectorConnection
            try:
                result = await db.execute(
                    select(ConnectorConnection).where(
                        ConnectorConnection.organization_id == org_uuid,
                        ConnectorConnection.connector_id == connector_id,
                        ConnectorConnection.status == ConnectionStatus.CONNECTED
                    ).order_by(ConnectorConnection.created_at.desc()).limit(10))
                connection = None
                team_ids = await self._resolve_team_ids(
                    db, org_uuid, ctx.get("user_id"))
                for candidate in result.scalars().all():
                    try:
                        ConnectorEngine(db).check_sharing(
                            candidate, user_id=self._as_uuid(ctx.get("user_id")),
                            team_ids=team_ids,
                            workflow_id=self._as_uuid(ctx.get("workflow_id")))
                        connection = candidate
                        break
                    except Exception:
                        continue
                if connection is None:
                    return {"status": "error",
                            "error": f"No accessible '{connector_id}' connection",
                            "error_code": "NO_CONNECTION"}
                connection_id = str(connection.id)
            except Exception as exc:
                return {"status": "error",
                        "error": "Connection resolution failed",
                        "error_code": "NO_CONNECTION"}
        args = {k: v for k, v in (arguments or {}).items()
                if k != "connection_id"}
        try:
            approval_raw = ctx.get("approval_id")
            approval_id = UUID(str(approval_raw)) if approval_raw else None
        except ValueError:
            approval_id = None
        try:
            team_ids = await self._resolve_team_ids(
                db, org_uuid, ctx.get("user_id"))
            outcome = await ConnectorEngine(db).execute_action(
                connector_id=connector_id, action_id=tool_name,
                connection_id=UUID(str(connection_id)),
                organization_id=org_uuid, arguments=args,
                context=ConnectorExecutionContext(
                    organization_id=str(org_uuid),
                    user_id=str(ctx.get("user_id") or ""),
                    agent_id=str(ctx.get("agent_id") or ""),
                    workflow_id=str(ctx.get("workflow_id") or ""),
                    tool_id=tool_name, connector_id=connector_id,
                    connection_id=str(connection_id),
                    policy_context={"team_ids": team_ids}),
                approval_id=approval_id,
                idempotency_key=str(ctx.get("idempotency_key", "")))
            await db.commit()
            return outcome
        except Exception as exc:
            from openagent.connectors.engine import ConnectorError
            await db.rollback()
            if isinstance(exc, ConnectorError):
                return {"status": "error", "error": str(exc),
                        "error_code": exc.code}
            logger.warning("connector tool failed", tool=tool_name,
                           error=str(exc))
            return {"status": "error", "error": "Connector execution failed",
                    "error_code": "EXECUTION_FAILED"}


connector_tool_executor = ConnectorToolExecutor()


def _noop() -> None:
    return None


# Attach helpers to the executor class (kept outside the hot path).
async def _resolve_team_ids(self: ConnectorToolExecutor, db: Any,
                            org_uuid: UUID, user_raw: Any) -> list[str]:
    """Server-side team resolution. Caller-supplied team lists are never
    trusted; membership is read from the DB."""
    user_id = self._as_uuid(user_raw)
    if user_id is None:
        return []
    try:
        from sqlalchemy import select

        from openagent.db.models.membership import Membership
        rows = (await db.execute(select(Membership).where(
            Membership.organization_id == org_uuid,
            Membership.user_id == user_id))).scalars().all()
        return sorted({str(getattr(r, "team_id", "")) for r in rows if getattr(r, "team_id", None)})
    except Exception:
        try:
            from sqlalchemy import select as _select

            from openagent.db.models.team import TeamMember
            rows = (await db.execute(_select(TeamMember).where(
                TeamMember.user_id == user_id))).scalars().all()
            return sorted({str(getattr(r, "team_id", "")) for r in rows if getattr(r, "team_id", None)})
        except Exception:
            return []


def _as_uuid(self: ConnectorToolExecutor, raw: Any) -> Any:
    if raw is None or raw == "":
        return None
    try:
        return raw if isinstance(raw, UUID) else UUID(str(raw))
    except (ValueError, AttributeError, TypeError):
        return None


ConnectorToolExecutor._resolve_team_ids = _resolve_team_ids  # type: ignore[attr-defined]
ConnectorToolExecutor._as_uuid = _as_uuid  # type: ignore[attr-defined]
