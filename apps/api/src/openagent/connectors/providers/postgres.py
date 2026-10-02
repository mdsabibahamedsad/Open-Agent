"""PostgreSQL database connector manifest (MP21).

Execution flows through the guarded db_connector (parameterized queries,
read-only default, allowlists, row caps). No raw credentials reach models.
"""

from __future__ import annotations

from typing import Any

from openagent.connectors import db_connector
from openagent.connectors.providers._base import schema

MANIFEST = {
    "id": "postgres",
    "name": "PostgreSQL",
    "version": "1.0.0",
    "category": "database",
    "type": "DATABASE",
    "trust": "ORGANIZATION",
    "description": "Parameterized PostgreSQL queries with guardrails.",
    "publisher": "OpenAgent",
    "license": "Apache-2.0",
    "documentation_url": "https://www.postgresql.org/docs/",
    "auth": {"type": "service_account", "driver": "postgres"},
    "capabilities": [
        {"id": "postgres.query.read", "description": "Run read queries",
         "risk_level": "MEDIUM"},
        {"id": "postgres.query.write", "description": "Run write queries (approval)",
         "risk_level": "HIGH"},
        {"id": "postgres.schema.read", "description": "Inspect schema",
         "risk_level": "LOW"},
    ],
    "actions": [
        {"id": "postgres.query", "name": "Run query",
         "description": "Parameterized query ($1 params). Writes need approval.",
         "input_schema": schema("object", {
             "sql": {"type": "string"}, "params": {"type": "array"},
             "mode": {"type": "string", "enum": ["read", "write"]},
             "max_rows": {"type": "integer"}}, ["sql"]),
         "required_capabilities": ["postgres.query.read"],
         "risk_level": "HIGH", "timeout_seconds": 30,
         "rate_limit_per_minute": 30,
         "verification": {"kind": "side_effect"}},
        {"id": "postgres.read", "name": "Read query",
         "description": "Read-only parameterized query.",
         "input_schema": schema("object", {
             "sql": {"type": "string"}, "params": {"type": "array"},
             "max_rows": {"type": "integer"}}, ["sql"]),
         "required_capabilities": ["postgres.query.read"],
         "risk_level": "MEDIUM", "mutation": False, "timeout_seconds": 30,
         "rate_limit_per_minute": 30},
        {"id": "postgres.inspect", "name": "Inspect schema",
         "description": "List tables in non-system schemas.",
         "input_schema": schema("object", {}),
         "required_capabilities": ["postgres.schema.read"],
         "risk_level": "LOW", "mutation": False, "rate_limit_per_minute": 10},
    ],
    "triggers": [],
    "resources": [{"kind": "database_row", "provider_kind": "row"}],
    "scopes": [],
    "rate_limits": {"per_minute": 30},
}


async def execute(action_id: str, params: dict[str, Any],
                  auth: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    # Read actions force read mode even if the caller asks otherwise.
    if action_id == "postgres.read":
        params = dict(params or {})
        params["mode"] = "read"
    outcome = await db_connector.execute(
        manifest={"auth": {"driver": "postgres"}}, action=action_id,
        arguments=params, auth=auth, ctx=ctx)
    return {"status": outcome.get("status", "ok"), "action": action_id,
            "result": {"rows": outcome.get("rows", []),
                       "row_count": outcome.get("row_count", 0),
                       "truncated": outcome.get("truncated", False)},
            "provider_request_id": "",
            "verified": outcome.get("status") == "ok"}


async def test(auth: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    secrets = (auth.get("secrets", {}) or {})
    dsn = secrets.get("dsn") or secrets.get("database_url") or ""
    if not dsn:
        raise ValueError("Missing DSN")
    outcome = await db_connector.inspect_schema_postgres(dsn=dsn,
                                                         timeout_seconds=10)
    tables = outcome.get("tables", []) or []
    return {"provider": "postgres", "tables": len(tables)}


def normalize_event(event: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"event_type": event, "resource_id": "",
            "attributes": {}}
