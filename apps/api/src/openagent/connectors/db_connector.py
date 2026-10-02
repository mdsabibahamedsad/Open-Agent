"""Secure database connector architecture (MP21).

PostgreSQL + SQLite now; MySQL/MongoDB/Redis/BigQuery/Snowflake later via the
same guard. Rules: parameterized queries only, read-only default, table and
schema allowlists, row limits, timeouts. Destructive statements require
approval upstream (engine gate) AND explicit write mode here.
"""

from __future__ import annotations

import re
import time
from contextlib import suppress
from typing import Any, Optional

import structlog

logger = structlog.get_logger("openagent.connectors.database")


class DatabaseError(Exception):
    def __init__(self, message: str, code: str = "DATABASE_ERROR"):
        super().__init__(message)
        self.code = code


# Statements that mutate or escape. Matched on the normalized statement head.
DESTRUCTIVE_RE = re.compile(
    r"^\s*(insert|update|delete|merge|upsert|replace|truncate|drop|alter|create|"
    r"grant|revoke|vacuum|analyze|reindex|cluster|comment|copy|call|do|execute|"
    r"listen|notify|load|import|attach|detach|pragma|checkpoint)\b",
    re.IGNORECASE)

# Dangerous even in reads: multi-statement, comments that smuggle, pg escapes.
UNSAFE_RE = re.compile(r";\s*\S|\bcopy\b|\\\\copy|pg_sleep|pg_terminate|dblink",
                       re.IGNORECASE)

_PARAM_RE = re.compile(r"\$(\d+)|\?")

_LITERAL_RE = re.compile(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"|\$\$.*?\$\$", re.DOTALL)


def _strip_literals(sql: str) -> str:
    """Remove string/quoted/dollar-quoted literals so keyword scans cannot be
    fooled by (or fire on) literal contents."""
    return _LITERAL_RE.sub(" ", sql or "")


def _extract_tables(sql: str) -> list[str]:
    """Extract candidate table refs from FROM/JOIN clauses (incl. comma joins,
    subselects, CTE bodies, quoted schema.table). Operates on literal-stripped
    SQL; CTE names are NOT allowlisted automatically."""
    cleaned = _strip_literals(sql).lower()
    tables: list[str] = []
    # FROM a, b JOIN c ... — capture comma-separated lists after FROM/JOIN.
    for match in re.finditer(
            r"(?:from|join)\s+([a-z0-9_\"'.]+(?:\s*,\s*[a-z0-9_\"'.]+)*)",
            cleaned):
        for part in match.group(1).split(","):
            candidate = part.strip().split()[0] if part.strip() else ""
            candidate = candidate.strip("\"'")
            if candidate and candidate not in ("select", "lateral"):
                tables.append(candidate)
    return tables


def _extract_schemas(sql: str) -> list[str]:
    cleaned = _strip_literals(sql).lower()
    return re.findall(r"(?:from|join)\s+([a-z0-9_]+)\.", cleaned)


def classify_statement(sql: str) -> str:
    """Return read|write|deny. Deny wins over everything."""
    head = (sql or "").strip()
    if not head:
        return "deny"
    if UNSAFE_RE.search(head):
        return "deny"
    if DESTRUCTIVE_RE.match(head):
        return "write"
    if re.match(r"^\s*(select|with|values|table|show|describe|desc|explain)\b",
                head, re.IGNORECASE):
        return "read"
    return "deny"


def validate_query(sql: str, *, mode: str = "read",
                   allowed_tables: Optional[list[str]] = None,
                   allowed_schemas: Optional[list[str]] = None,
                   max_rows: int = 500) -> dict[str, Any]:
    """Fail-closed SQL validation. Raises DatabaseError on any violation."""
    if not isinstance(sql, str) or not sql.strip() or len(sql) > 20000:
        raise DatabaseError("Invalid or oversized SQL", code="VALIDATION_ERROR")
    kind = classify_statement(sql)
    if kind == "deny":
        raise DatabaseError("Statement type not permitted", code="STATEMENT_DENIED")
    if mode == "read" and kind != "read":
        raise DatabaseError("Write statements require write mode + approval",
                            code="WRITE_DENIED")
    lowered = _strip_literals(sql).lower()
    if allowed_tables:
        allowed = {t.lower() for t in allowed_tables}
        candidates = set(_extract_tables(sql))
        for candidate in candidates:
            name = candidate.strip("\"'").split(".")[-1]
            if name and name not in allowed and name not in ("select",):
                raise DatabaseError(f"Table '{candidate}' not allowlisted",
                                    code="TABLE_DENIED")
    if allowed_schemas:
        allowed = {s.lower() for s in allowed_schemas}
        for match in _extract_schemas(sql):
            if match not in allowed:
                raise DatabaseError(f"Schema '{match}' not allowlisted",
                                    code="SCHEMA_DENIED")
    # Hidden writes: a statement classified "read" must not smuggle
    # INSERT/UPDATE/DELETE/MERGE/etc. outside literals (e.g. WITH ... INSERT,
    # SELECT ... INTO, UNION with function calls handled above).
    if kind == "read" and re.search(
            r"\b(insert|update|delete|merge|upsert|replace|truncate|drop|alter|"
            r"create|grant|revoke|vacuum|copy|call|do|execute)\b", lowered):
        raise DatabaseError("Statement type not permitted", code="STATEMENT_DENIED")
    params = sorted({int(n) for n in _PARAM_RE.findall(sql) if n.isdigit()},
                    reverse=True)
    positional = sql.count("?")
    return {"kind": kind, "max_rows": max(1, min(max_rows, 10000)),
            "numbered_params": params, "positional_params": positional}


def _bind_params(sql: str, params: list[Any],
                 *, expected_numbered: Optional[list[int]] = None,
                 expected_positional: int = 0) -> tuple[str, list[Any]]:
    """Rewrite $N placeholders for the driver. asyncpg uses $N natively;
    sqlite uses ?. Fail-closed on arity mismatch. Returns (sql, ordered_values)."""
    values = list(params or [])
    if expected_numbered:
        if max(expected_numbered) != len(values):
            raise DatabaseError(
                f"Expected {max(expected_numbered)} params, got {len(values)}",
                code="VALIDATION_ERROR")
        if sorted(expected_numbered) != list(range(1, max(expected_numbered) + 1)):
            raise DatabaseError("Non-contiguous $N placeholders",
                                code="VALIDATION_ERROR")
    elif expected_positional:
        if len(values) != expected_positional:
            raise DatabaseError(
                f"Expected {expected_positional} params, got {len(values)}",
                code="VALIDATION_ERROR")
    elif values:
        raise DatabaseError("Query takes no parameters", code="VALIDATION_ERROR")
    return sql, values


async def execute_postgres(*, dsn: str, sql: str, params: Optional[list[Any]] = None,
                           timeout_seconds: int = 15,
                           max_rows: int = 500) -> dict[str, Any]:
    import asyncpg
    validated = validate_query(sql, max_rows=max_rows)
    statement, values = _bind_params(
        sql, params, expected_numbered=validated["numbered_params"],
        expected_positional=validated["positional_params"])
    started = time.time()
    try:
        conn = await asyncpg.connect(dsn, timeout=timeout_seconds,
                                     statement_cache_size=0)
    except Exception as exc:
        raise DatabaseError(f"Connect failed: {exc}", code="CONNECT_FAILED") from exc
    try:
        rows = await asyncio_wait(conn.fetch, statement, *values,
                                  timeout=timeout_seconds)
    except Exception as exc:
        raise DatabaseError(f"Query failed: {exc}", code="QUERY_FAILED") from exc
    finally:
        with suppress(Exception):
            await conn.close()
    clipped = [dict(r) for r in rows[: validated["max_rows"]]]
    return {"status": "ok", "kind": validated["kind"], "rows": clipped,
            "row_count": len(rows), "truncated": len(rows) > len(clipped),
            "latency_ms": int((time.time() - started) * 1000)}


async def asyncio_wait(coro_fn, *args, timeout: int = 15):
    import asyncio
    return await asyncio.wait_for(coro_fn(*args), timeout=timeout)


async def execute_sqlite(*, path: str, sql: str,
                         params: Optional[list[Any]] = None,
                         timeout_seconds: int = 15,
                         max_rows: int = 500) -> dict[str, Any]:
    import aiosqlite
    validated = validate_query(sql, max_rows=max_rows)
    _, values = _bind_params(
        sql, params, expected_numbered=validated["numbered_params"],
        expected_positional=validated["positional_params"])
    statement = re.sub(r"\$(\d+)", "?", sql)
    started = time.time()
    try:
        async with aiosqlite.connect(path, timeout=timeout_seconds) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(statement, list(params or []))
            rows = await cursor.fetchall()
            columns = [d[0] for d in (cursor.description or [])]
    except Exception as exc:
        raise DatabaseError(f"Query failed: {exc}", code="QUERY_FAILED") from exc
    clipped = [dict(zip(columns, r)) for r in rows[: validated["max_rows"]]]
    return {"status": "ok", "kind": validated["kind"], "rows": clipped,
            "row_count": len(rows), "truncated": len(rows) > len(clipped),
            "latency_ms": int((time.time() - started) * 1000)}


async def inspect_schema_postgres(*, dsn: str,
                                  timeout_seconds: int = 15) -> dict[str, Any]:
    import asyncpg
    try:
        conn = await asyncpg.connect(dsn, timeout=timeout_seconds,
                                     statement_cache_size=0)
    except Exception as exc:
        raise DatabaseError(f"Connect failed: {exc}", code="CONNECT_FAILED") from exc
    try:
        rows = await asyncio_wait(
            conn.fetch,
            "SELECT table_schema, table_name FROM information_schema.tables "
            "WHERE table_schema NOT IN ('pg_catalog','information_schema') "
            "ORDER BY 1,2 LIMIT 500", timeout=timeout_seconds)
        return {"status": "ok",
                "tables": [f"{r['table_schema']}.{r['table_name']}" for r in rows]}
    except Exception as exc:
        raise DatabaseError(f"Inspect failed: {exc}", code="QUERY_FAILED") from exc
    finally:
        with suppress(Exception):
            await conn.close()


async def execute(*, manifest: Any, action: Any, arguments: dict[str, Any],
                  auth: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Database action dispatcher (query/read/inspect).

    manifest/action may be ActionDef dataclasses or plain identifiers —
    only driver config, action id, and arguments matter here.
    """
    secrets = auth.get("secrets", {}) or {}
    manifest_auth = getattr(manifest, "auth", None)
    if manifest_auth is None and isinstance(manifest, dict):
        manifest_auth = manifest.get("auth", {})
    driver = str(((manifest_auth or {}).get("driver")) or secrets.get("driver")
                 or "postgres").lower()
    action_id = getattr(action, "id", action) if not isinstance(action, str) \
        else action
    connection_cfg = (ctx.get("connection", {}) or {}).get("config", {}) or {}
    # Connection config is the ceiling; caller arguments may only narrow.
    # A caller with execute permission must not escalate mode, widen table/
    # schema allowlists, or raise row/timeout budgets.
    cfg_mode = str(connection_cfg.get("mode", "read")).lower()
    req_mode = str(arguments.get("mode", cfg_mode)).lower()
    mode = req_mode if cfg_mode == "write" else "read"
    if req_mode == "write" and cfg_mode != "write":
        raise DatabaseError("Write statements require write mode + approval",
                            code="WRITE_DENIED")
    cfg_tables = connection_cfg.get("allowed_tables")
    req_tables = arguments.get("allowed_tables", None)
    if cfg_tables is not None:
        allowed_tables = list(cfg_tables)
        if req_tables is not None:
            narrowed = {str(t).lower() for t in (req_tables or [])}
            if not narrowed.issubset({str(t).lower() for t in cfg_tables}):
                raise DatabaseError("Table allowlist widening denied",
                                    code="TABLE_DENIED")
            allowed_tables = list(req_tables)
    else:
        allowed_tables = req_tables
    cfg_schemas = connection_cfg.get("allowed_schemas")
    req_schemas = arguments.get("allowed_schemas", None)
    if cfg_schemas is not None:
        allowed_schemas = list(cfg_schemas)
        if req_schemas is not None:
            narrowed = {str(s).lower() for s in (req_schemas or [])}
            if not narrowed.issubset({str(s).lower() for s in cfg_schemas}):
                raise DatabaseError("Schema allowlist widening denied",
                                    code="SCHEMA_DENIED")
            allowed_schemas = list(req_schemas)
    else:
        allowed_schemas = req_schemas
    cfg_rows = int(connection_cfg.get("max_rows", 500) or 500)
    req_rows = int(arguments.get("max_rows", cfg_rows) or cfg_rows)
    max_rows = max(1, min(req_rows, cfg_rows, 10000))
    cfg_timeout = int(connection_cfg.get("timeout_seconds", 15) or 15)
    req_timeout = int(arguments.get("timeout_seconds", cfg_timeout) or cfg_timeout)
    timeout = max(1, min(req_timeout, cfg_timeout, 120))
    if action_id.endswith(".query") or action_id.endswith(".read"):
        sql = str(arguments.get("sql", ""))
        validate_query(sql, mode=mode, allowed_tables=allowed_tables,
                       allowed_schemas=allowed_schemas, max_rows=max_rows)
        params = arguments.get("params", []) or []
        if driver in ("postgres", "postgresql"):
            dsn = secrets.get("dsn") or secrets.get("database_url") or ""
            if not dsn:
                raise DatabaseError("Missing DSN", code="NO_DSN")
            return await execute_postgres(dsn=dsn, sql=sql, params=params,
                                          timeout_seconds=timeout,
                                          max_rows=max_rows)
        if driver == "sqlite":
            path = secrets.get("path") or ":memory:"
            return await execute_sqlite(path=path, sql=sql, params=params,
                                        timeout_seconds=timeout,
                                        max_rows=max_rows)
        raise DatabaseError(f"Driver '{driver}' not yet supported "
                            "(postgres/sqlite now; mysql/mongo/redis/bigquery/snowflake later)",
                            code="DRIVER_UNSUPPORTED")
    if action_id.endswith(".inspect"):
        dsn = secrets.get("dsn") or secrets.get("database_url") or ""
        if driver in ("postgres", "postgresql") and dsn:
            return await inspect_schema_postgres(dsn=dsn, timeout_seconds=timeout)
        raise DatabaseError("Schema inspect needs a postgres DSN",
                            code="NO_DSN")
    raise DatabaseError(f"Unknown database action '{action_id}'",
                        code="UNKNOWN_ACTION")
