"""Connector workflow node executors (MP21).

Pure descriptor nodes running inside the EXISTING workflow engine. They
validate statically against the connector registry (fail closed on unknown
actions/schemas) and emit normalized invocation descriptors — credential
selector, input, output schema, retry/timeout/approval metadata — for the
API/worker execution path (ConnectorEngine). No secrets, no egress here.
"""

from __future__ import annotations

from typing import Any, Dict

from openagent.runtime.engine import resolve_expressions
from openagent.runtime.executors.base import (
    NodeExecutionContext,
    NodeExecutionResult,
    NodeExecutor,
    NodeRunStatus,
)


def _fail(message: str, code: str = "INVALID_CONFIG") -> NodeExecutionResult:
    return NodeExecutionResult(status=NodeRunStatus.FAILED, error=message,
                               error_code=code)


def _registry():
    from openagent.connectors.providers import provider_ids, register_official
    from openagent.connectors.registry import registry
    if not provider_ids():
        register_official()
    return registry


class ConnectorActionNodeExecutor(NodeExecutor):
    """Connector action invocation descriptor."""

    node_type = "connector_action"
    default_timeout = 120
    required_capabilities = ["tool_execution", "external_api"]

    async def execute(self, node_config: Dict[str, Any],
                      context: NodeExecutionContext) -> NodeExecutionResult:
        try:
            cfg = resolve_expressions(node_config, context)
        except Exception as e:
            return _fail(f"Failed to resolve expressions: {e}", "EXPRESSION_ERROR")
        action_id = str(cfg.get("action_id", "") or "").strip().lower()
        connection_id = str(cfg.get("connection_id", "") or "")
        if not action_id or "." not in action_id:
            return _fail("connector_action node requires 'config.action_id' "
                         "(e.g. github.create_issue)")
        entry = _registry().action_definition(action_id)
        if entry is None:
            return _fail(f"Unknown connector action '{action_id}'",
                         "UNKNOWN_ACTION")
        definition = entry["action"]
        timeout = cfg.get("timeout_seconds", definition.get("timeout_seconds", 30))
        try:
            timeout = int(timeout)
        except (TypeError, ValueError):
            return _fail("'timeout_seconds' must be an integer")
        if not 1 <= timeout <= 300:
            return _fail("'timeout_seconds' must be 1..300")
        retry = cfg.get("retry", {}) or {}
        if not isinstance(retry, dict):
            return _fail("'retry' must be an object")
        max_attempts = int(retry.get("max_attempts", 1) or 1)
        if not 1 <= max_attempts <= 5:
            return _fail("'retry.max_attempts' must be 1..5")
        return NodeExecutionResult(
            status=NodeRunStatus.SUCCEEDED,
            outputs={
                "connector": entry["connector"],
                "connector_version": entry["version"],
                "action": action_id,
                "connection_id": connection_id,
                "credential_selector": cfg.get("credential_id", ""),
                "input": cfg.get("input", {}),
                "output_schema": definition.get("output_schema", {}),
                "risk_level": definition.get("risk_level", "MEDIUM"),
                "required_capabilities": definition.get(
                    "required_capabilities", []),
                "advanced": {
                    "timeout_seconds": timeout,
                    "retry": {"max_attempts": max_attempts},
                    "idempotency_key": cfg.get("idempotency_key", ""),
                    "approval_id": cfg.get("approval_id", ""),
                },
            },
            metadata={"node_type": self.node_type, "action": action_id})


class ConnectorTriggerNodeExecutor(NodeExecutor):
    """Connector trigger descriptor (webhook/polling/schedule/event/manual)."""

    node_type = "connector_trigger"
    default_timeout = 30
    required_capabilities = ["event_subscription"]

    async def execute(self, node_config: Dict[str, Any],
                      context: NodeExecutionContext) -> NodeExecutionResult:
        try:
            cfg = resolve_expressions(node_config, context)
        except Exception as e:
            return _fail(f"Failed to resolve expressions: {e}", "EXPRESSION_ERROR")
        trigger_id = str(cfg.get("trigger_id", "") or "").strip().lower()
        if not trigger_id or "." not in trigger_id:
            return _fail("connector_trigger node requires 'config.trigger_id'")
        connector_id = trigger_id.split(".", 1)[0]
        manifest = _registry().get(connector_id)
        if manifest is None:
            return _fail(f"Unknown connector '{connector_id}'", "UNKNOWN_ACTION")
        trigger = next((t for t in manifest.triggers if t.id == trigger_id), None)
        if trigger is None:
            return _fail(f"Unknown trigger '{trigger_id}'", "UNKNOWN_ACTION")
        return NodeExecutionResult(
            status=NodeRunStatus.SUCCEEDED,
            outputs={
                "connector": connector_id,
                "trigger": trigger_id,
                "kind": trigger.kind.value,
                "event_types": trigger.event_types,
                "connection_id": str(cfg.get("connection_id", "") or ""),
                "filter": cfg.get("filter", {}),
            },
            metadata={"node_type": self.node_type, "trigger": trigger_id})


class ConnectorSearchNodeExecutor(NodeExecutor):
    """Capability/action search descriptor (compact discovery for agents)."""

    node_type = "connector_search"
    default_timeout = 30
    required_capabilities = ["tool_discovery"]

    async def execute(self, node_config: Dict[str, Any],
                      context: NodeExecutionContext) -> NodeExecutionResult:
        try:
            cfg = resolve_expressions(node_config, context)
        except Exception as e:
            return _fail(f"Failed to resolve expressions: {e}", "EXPRESSION_ERROR")
        query = str(cfg.get("query", "") or "").strip()
        if not query:
            return _fail("connector_search node requires 'config.query'")
        try:
            limit = int(cfg.get("limit", 10) or 10)
        except (TypeError, ValueError):
            return _fail("'limit' must be an integer")
        results = _registry().search_actions(query, limit=max(1, min(limit, 50)))
        return NodeExecutionResult(
            status=NodeRunStatus.SUCCEEDED,
            outputs={"query": query, "actions": results},
            metadata={"node_type": self.node_type})


class ConnectorResourceNodeExecutor(NodeExecutor):
    """Normalized resource lookup descriptor."""

    node_type = "connector_resource"
    default_timeout = 60
    required_capabilities = ["tool_execution", "external_api"]

    async def execute(self, node_config: Dict[str, Any],
                      context: NodeExecutionContext) -> NodeExecutionResult:
        try:
            cfg = resolve_expressions(node_config, context)
        except Exception as e:
            return _fail(f"Failed to resolve expressions: {e}", "EXPRESSION_ERROR")
        kind = str(cfg.get("kind", "") or "").strip().lower()
        connector_id = str(cfg.get("connector", "") or "").strip().lower()
        from openagent.connectors.resources import NORMALIZERS
        if kind not in NORMALIZERS:
            return _fail(f"Unknown resource kind '{kind}'")
        if connector_id and _registry().get(connector_id) is None:
            return _fail(f"Unknown connector '{connector_id}'", "UNKNOWN_ACTION")
        return NodeExecutionResult(
            status=NodeRunStatus.SUCCEEDED,
            outputs={
                "kind": kind, "connector": connector_id,
                "connection_id": str(cfg.get("connection_id", "") or ""),
                "lookup": cfg.get("lookup", {}),
            },
            metadata={"node_type": self.node_type, "kind": kind})
