"""Workflow definition validation (pure functions, no DB access).

The workflow definition is the versioned JSON contract shared by the visual
builder (frontend), the CRUD API, and the future execution engine::

    {
        "schema_version": "1.0",
        "triggers": [
            {"id": "trg_1", "type": "manual", "name": "Run manually", "config": {}}
        ],
        "nodes": [
            {"id": "n_1", "type": "agent", "name": "Triage",
             "position": {"x": 120, "y": 80}, "config": {"agent_id": "..."}}
        ],
        "edges": [
            {"id": "e_1", "from": "trg_1", "to": "n_1",
             "condition": {"when": "success"}}
        ],
        "variables": [
            {"name": "ticket_id", "type": "string", "required": True}
        ],
        "settings": {"timezone": "UTC", "max_concurrency": 1}
    }

Validation produces errors (block publish/execute) and warnings (advisory).
Drafts may be saved while invalid; only publish is gated.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

SCHEMA_VERSION = "1.0"
SUPPORTED_SCHEMA_VERSIONS = {"1.0"}

TRIGGER_TYPES = {"manual", "webhook", "schedule", "event"}
NODE_TYPES = {
    "agent",
    "prompt",
    "condition",
    "switch",
    "merge",
    "loop",
    "set",
    "transform",
    "filter",
    "map",
    "variable",
    "approval",
    "webhook",
    "tool",
    "connector_action",
    "connector_trigger",
    "connector_search",
    "connector_resource",
    "delay",
    "subworkflow",
    "browser_agent",
    "browser_action",
    "browser_extract",
    "code_agent",
    "code_search",
    "code_read",
    "code_patch",
    "code_test",
    "code_lint",
    "code_review",
    "git_commit",
    "create_pr",
    "verify",
    "evaluate",
    "assert",
    "quality_gate",
    "retry",
    "correct",
}
EDGE_WHEN = {"always", "success", "failure"}
VARIABLE_TYPES = {"string", "number", "boolean", "json"}

# Node types that may terminate a branch without outgoing edges.
TERMINAL_NODE_TYPES = {"approval"}

# Nodes whose single input accepts many inbound edges (fan-in).
FAN_IN_NODE_TYPES = {"merge"}

# Config keys that must only hold references (credential_id or {{...}}),
# never literal secret material.
SECRET_LIKE_KEYS = {
    "api_key", "apikey", "secret", "token", "password", "passwd",
    "private_key", "client_secret", "access_key", "auth_token",
    "secret_key", "api_secret",
}
# ...except these reference-carrying keys, which are always allowed.
REFERENCE_KEYS = {"credential_id", "secret_ref", "credential_ref"}

_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SLUG_RE = re.compile(r"^[a-z0-9-]+$")


@dataclass
class ValidationIssue:
    code: str
    message: str
    severity: str = "error"
    node_id: Optional[str] = None
    field: Optional[str] = None
    edge_id: Optional[str] = None


@dataclass
class ValidationResult:
    valid: bool
    errors: list[ValidationIssue] = field(default_factory=list)
    warnings: list[ValidationIssue] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        def issue(i: ValidationIssue) -> dict[str, Any]:
            d: dict[str, Any] = {"code": i.code, "message": i.message, "severity": i.severity}
            if i.node_id is not None:
                d["node_id"] = i.node_id
            if i.field is not None:
                d["field"] = i.field
            if i.edge_id is not None:
                d["edge_id"] = i.edge_id
            return d

        return {
            "valid": self.valid,
            "errors": [issue(i) for i in self.errors],
            "warnings": [issue(i) for i in self.warnings],
        }


def _is_dict(v: Any) -> bool:
    return isinstance(v, dict)


def validate_definition(definition: Any) -> ValidationResult:
    """Validate a workflow definition dict. Never raises on bad input."""
    result = ValidationResult(valid=True)

    def err(code: str, message: str, node_id: Optional[str] = None,
            field: Optional[str] = None, edge_id: Optional[str] = None) -> None:
        result.errors.append(ValidationIssue(code, message, "error", node_id, field, edge_id))
        result.valid = False

    def warn(code: str, message: str, node_id: Optional[str] = None,
             field: Optional[str] = None, edge_id: Optional[str] = None) -> None:
        result.warnings.append(ValidationIssue(code, message, "warning", node_id, field, edge_id))

    if not _is_dict(definition):
        err("INVALID_DEFINITION", "Definition must be a JSON object.")
        return result

    version = definition.get("schema_version")
    if version not in SUPPORTED_SCHEMA_VERSIONS:
        err("UNSUPPORTED_SCHEMA_VERSION",
            f"Unsupported schema_version {version!r}. Supported: {sorted(SUPPORTED_SCHEMA_VERSIONS)}.",
            field="schema_version")
        # Continue with best-effort checks so authors get full feedback.

    triggers = definition.get("triggers", [])
    nodes = definition.get("nodes", [])
    edges = definition.get("edges", [])
    variables = definition.get("variables", [])
    settings = definition.get("settings", {})

    if not isinstance(triggers, list):
        err("INVALID_TRIGGERS", "'triggers' must be a list.", field="triggers")
        triggers = []
    if not isinstance(nodes, list):
        err("INVALID_NODES", "'nodes' must be a list.", field="nodes")
        nodes = []
    if not isinstance(edges, list):
        err("INVALID_EDGES", "'edges' must be a list.", field="edges")
        edges = []
    if not isinstance(variables, list):
        err("INVALID_VARIABLES", "'variables' must be a list.", field="variables")
        variables = []
    if settings is not None and not _is_dict(settings):
        err("INVALID_SETTINGS", "'settings' must be an object.", field="settings")
        settings = {}

    if not triggers:
        err("NO_TRIGGER", "Workflow must define at least one trigger.", field="triggers")

    # ---- triggers -----------------------------------------------------
    trigger_ids: set[str] = set()
    for i, t in enumerate(triggers):
        where = f"triggers[{i}]"
        if not _is_dict(t):
            err("INVALID_TRIGGER", f"{where} must be an object.", field=where)
            continue
        tid = t.get("id")
        if not isinstance(tid, str) or not tid:
            err("TRIGGER_MISSING_ID", f"{where} requires a non-empty string 'id'.", field=f"{where}.id")
            continue
        if tid in trigger_ids:
            err("DUPLICATE_ID", f"Duplicate id {tid!r}. Ids must be unique across triggers and nodes.",
                node_id=tid, field=f"{where}.id")
        trigger_ids.add(tid)
        ttype = t.get("type")
        if ttype not in TRIGGER_TYPES:
            err("UNKNOWN_TRIGGER_TYPE",
                f"Trigger {tid!r} has unknown type {ttype!r}. Expected one of {sorted(TRIGGER_TYPES)}.",
                node_id=tid, field=f"{where}.type")
        if not t.get("name"):
            err("TRIGGER_MISSING_NAME", f"Trigger {tid!r} requires a 'name'.",
                node_id=tid, field=f"{where}.name")
        config = t.get("config", {})
        if config is not None and not _is_dict(config):
            err("INVALID_TRIGGER_CONFIG", f"Trigger {tid!r} 'config' must be an object.",
                node_id=tid, field=f"{where}.config")
            config = {}
        if ttype == "webhook" and not (config or {}).get("path"):
            err("TRIGGER_CONFIG_REQUIRED",
                f"Webhook trigger {tid!r} requires 'config.path'.",
                node_id=tid, field=f"{where}.config.path")
        if ttype == "schedule" and not (config or {}).get("cron"):
            err("TRIGGER_CONFIG_REQUIRED",
                f"Schedule trigger {tid!r} requires 'config.cron'.",
                node_id=tid, field=f"{where}.config.cron")
        if ttype == "event" and not (config or {}).get("event"):
            err("TRIGGER_CONFIG_REQUIRED",
                f"Event trigger {tid!r} requires 'config.event'.",
                node_id=tid, field=f"{where}.config.event")

    # ---- nodes --------------------------------------------------------
    node_ids: set[str] = set()
    nodes_by_id: dict[str, dict] = {}
    disabled_ids: set[str] = set()
    for i, n in enumerate(nodes):
        where = f"nodes[{i}]"
        if not _is_dict(n):
            err("INVALID_NODE", f"{where} must be an object.", field=where)
            continue
        nid = n.get("id")
        if not isinstance(nid, str) or not nid:
            err("NODE_MISSING_ID", f"{where} requires a non-empty string 'id'.", field=f"{where}.id")
            continue
        if nid in trigger_ids or nid in node_ids:
            err("DUPLICATE_ID", f"Duplicate id {nid!r}. Ids must be unique across triggers and nodes.",
                node_id=nid, field=f"{where}.id")
        node_ids.add(nid)
        nodes_by_id[nid] = n
        if n.get("disabled") is True:
            # Disabled nodes are excluded from execution and from
            # config/reachability validation; ids and types must still be sane.
            disabled_ids.add(nid)
        ntype = n.get("type")
        if ntype not in NODE_TYPES:
            err("UNKNOWN_NODE_TYPE",
                f"Node {nid!r} has unknown type {ntype!r}. Expected one of {sorted(NODE_TYPES)}.",
                node_id=nid, field=f"{where}.type")
        if not n.get("name"):
            err("NODE_MISSING_NAME", f"Node {nid!r} requires a 'name'.",
                node_id=nid, field=f"{where}.name")
        tv = n.get("type_version")
        if tv is not None and (not isinstance(tv, int) or tv < 1):
            err("INVALID_NODE_FIELD",
                f"Node {nid!r} 'type_version' must be a positive integer when present.",
                node_id=nid, field=f"{where}.type_version")
        pos = n.get("position")
        if pos is not None:
            if (not _is_dict(pos) or not isinstance(pos.get("x"), (int, float))
                    or not isinstance(pos.get("y"), (int, float))):
                err("INVALID_NODE_POSITION",
                    f"Node {nid!r} 'position' must be {{'x': number, 'y': number}}.",
                    node_id=nid, field=f"{where}.position")
        config = n.get("config", {})
        if config is not None and not _is_dict(config):
            err("INVALID_NODE_CONFIG", f"Node {nid!r} 'config' must be an object.",
                node_id=nid, field=f"{where}.config")
            config = {}
        _validate_node_config(err, nid, ntype, config or {}, where,
                              disabled=nid in disabled_ids)
        timeout = n.get("timeout_seconds")
        if timeout is not None and (not isinstance(timeout, (int, float)) or timeout <= 0):
            err("INVALID_TIMEOUT", f"Node {nid!r} 'timeout_seconds' must be a positive number.",
                node_id=nid, field=f"{where}.timeout_seconds")
        retry = n.get("retry_policy")
        if retry is not None:
            if not _is_dict(retry):
                err("INVALID_RETRY_POLICY", f"Node {nid!r} 'retry_policy' must be an object.",
                    node_id=nid, field=f"{where}.retry_policy")
            else:
                attempts = retry.get("max_attempts", 0)
                if not isinstance(attempts, int) or attempts < 0 or attempts > 10:
                    err("INVALID_RETRY_POLICY",
                        f"Node {nid!r} 'retry_policy.max_attempts' must be an integer 0..10.",
                        node_id=nid, field=f"{where}.retry_policy.max_attempts")

    # ---- edges --------------------------------------------------------
    all_ids = trigger_ids | node_ids
    seen_pairs: set[tuple[str, str]] = set()
    outgoing: dict[str, list[str]] = {i: [] for i in all_ids}
    incoming: dict[str, list[str]] = {i: [] for i in all_ids}
    for i, e in enumerate(edges):
        where = f"edges[{i}]"
        if not _is_dict(e):
            err("INVALID_EDGE", f"{where} must be an object.", field=where)
            continue
        src, dst = e.get("from"), e.get("to")
        if not isinstance(src, str) or not isinstance(dst, str) or not src or not dst:
            err("EDGE_MISSING_ENDPOINTS", f"{where} requires string 'from' and 'to'.", field=where)
            continue
        if src not in all_ids:
            err("UNKNOWN_EDGE_SOURCE", f"{where} references unknown source {src!r}.", field=f"{where}.from")
            continue
        if dst not in all_ids:
            err("UNKNOWN_EDGE_TARGET", f"{where} references unknown target {dst!r}.", field=f"{where}.to")
            continue
        if src == dst:
            err("SELF_LOOP", f"Node {src!r} cannot connect to itself.", node_id=src, field=where)
            continue
        if dst in trigger_ids:
            err("EDGE_INTO_TRIGGER", f"Triggers cannot have incoming edges ({src!r} -> {dst!r}).",
                node_id=dst, field=where)
            continue
        if (src, dst) in seen_pairs:
            err("DUPLICATE_EDGE", f"Duplicate edge {src!r} -> {dst!r}.", field=where)
            continue
        seen_pairs.add((src, dst))
        outgoing[src].append(dst)
        incoming[dst].append(src)
        # Port / cardinality rules.
        src_type = None
        if src in nodes_by_id:
            src_type = nodes_by_id[src].get("type")
        label = e.get("label")
        if src_type == "condition" and label is not None and label not in {"true", "false"}:
            warn("INVALID_EDGE_PORT",
                 f"Edge {src!r} -> {dst!r}: condition outputs are 'true'/'false', got label {label!r}.",
                 edge_id=e.get("id") if isinstance(e.get("id"), str) else None, field=f"{where}.label")
        if src_type == "switch" and label is not None:
            routes = _switch_route_names(nodes_by_id[src])
            if routes and label not in routes and label != "default":
                warn("INVALID_EDGE_PORT",
                     f"Edge {src!r} -> {dst!r}: label {label!r} matches no route {sorted(routes)}.",
                     edge_id=e.get("id") if isinstance(e.get("id"), str) else None, field=f"{where}.label")
        cond = e.get("condition")
        if cond is not None:
            if not _is_dict(cond):
                err("INVALID_EDGE_CONDITION", f"{where} 'condition' must be an object.", field=f"{where}.condition")
            else:
                when = cond.get("when", "always")
                if when not in EDGE_WHEN:
                    err("INVALID_EDGE_CONDITION",
                        f"{where} 'condition.when' must be one of {sorted(EDGE_WHEN)}.",
                        field=f"{where}.condition.when")
                expr = cond.get("expression")
                if expr is not None and (not isinstance(expr, str) or not expr.strip()):
                    err("INVALID_EDGE_CONDITION",
                        f"{where} 'condition.expression' must be a non-empty string when present.",
                        field=f"{where}.condition.expression")

    # ---- graph rules --------------------------------------------------
    if trigger_ids or node_ids:
        _check_cycles(err, all_ids, outgoing)
        # Reachability from any trigger (disabled nodes are exempt: they are
        # excluded from execution by definition).
        reachable: set[str] = set()
        stack = list(trigger_ids)
        while stack:
            cur = stack.pop()
            if cur in reachable:
                continue
            reachable.add(cur)
            stack.extend(outgoing.get(cur, []))
        for nid in sorted(node_ids - reachable - disabled_ids):
            err("UNREACHABLE_NODE",
                f"Node {nid!r} is not reachable from any trigger.",
                node_id=nid)
        # Input cardinality: one inbound edge per input, except fan-in nodes.
        for nid in sorted(node_ids):
            ntype = nodes_by_id[nid].get("type")
            if ntype in FAN_IN_NODE_TYPES:
                continue
            inbound = incoming.get(nid, [])
            if len(inbound) > 1:
                err("MULTIPLE_INBOUND_EDGES",
                    f"Node {nid!r} has {len(inbound)} incoming edges; "
                    f"'{ntype}' accepts a single input. Use a merge node for fan-in.",
                    node_id=nid)

    for tid in sorted(trigger_ids):
        if not outgoing.get(tid):
            warn("TRIGGER_WITHOUT_EDGES",
                 f"Trigger {tid!r} has no outgoing edges and will never run anything.",
                 node_id=tid)
    for nid in sorted(node_ids):
        ntype = nodes_by_id[nid].get("type")
        if not outgoing.get(nid) and ntype not in TERMINAL_NODE_TYPES:
            warn("NODE_WITHOUT_OUTGOING",
                 f"Node {nid!r} has no outgoing edges; its branch ends here.",
                 node_id=nid)

    # ---- variables ----------------------------------------------------
    var_names: set[str] = set()
    for i, v in enumerate(variables):
        where = f"variables[{i}]"
        if not _is_dict(v):
            err("INVALID_VARIABLE", f"{where} must be an object.", field=where)
            continue
        name = v.get("name")
        if not isinstance(name, str) or not _NAME_RE.match(name):
            err("INVALID_VARIABLE_NAME",
                f"{where} 'name' must match [A-Za-z_][A-Za-z0-9_]*.",
                field=f"{where}.name")
            continue
        if name in var_names:
            err("DUPLICATE_VARIABLE", f"Duplicate variable {name!r}.", field=f"{where}.name")
        var_names.add(name)
        if v.get("type") not in VARIABLE_TYPES:
            err("INVALID_VARIABLE_TYPE",
                f"Variable {name!r} type must be one of {sorted(VARIABLE_TYPES)}.",
                field=f"{where}.type")

    # ---- security: no literal secrets in configs ----------------------
    for nid, n in list(nodes_by_id.items()):
        cfg = n.get("config")
        if _is_dict(cfg):
            _check_no_literal_secrets(err, nid, cfg, prefix="config")
    for tid in sorted(trigger_ids):
        t = next((x for x in triggers if isinstance(x, dict) and x.get("id") == tid), None)
        if isinstance(t, dict) and _is_dict(t.get("config")):
            _check_no_literal_secrets(err, tid, t["config"], prefix="config")

    # ---- expressions: reference checks (advisory) -------------------------
    _check_expression_refs(warn, triggers, nodes_by_id, edges, var_names)

    # ---- settings -----------------------------------------------------
    if isinstance(settings, dict) and settings:
        mc = settings.get("max_concurrency")
        if mc is not None and (not isinstance(mc, int) or mc < 1 or mc > 32):
            err("INVALID_SETTINGS",
                "'settings.max_concurrency' must be an integer 1..32.",
                field="settings.max_concurrency")

    return result


def _validate_node_config(err, nid: str, ntype: Any, config: dict, where: str,
                          disabled: bool = False) -> None:
    """Per-type required config fields. Disabled nodes are skipped."""
    if disabled:
        return

    def req(field_name: str, message: str) -> None:
        if not config.get(field_name):
            err("NODE_CONFIG_REQUIRED", f"Node {nid!r}: {message}.",
                node_id=nid, field=f"{where}.config.{field_name}")

    if ntype == "agent":
        if not config.get("agent_id") and not config.get("agent_name"):
            err("NODE_CONFIG_REQUIRED",
                f"Node {nid!r} requires 'config.agent_id' or 'config.agent_name'.",
                node_id=nid, field=f"{where}.config.agent_id")
    elif ntype == "prompt":
        req("prompt", "AI prompt nodes require 'config.prompt'")
        if not config.get("model") and not config.get("model_router_profile"):
            err("NODE_CONFIG_REQUIRED",
                f"Node {nid!r} requires 'config.model' or 'config.model_router_profile'.",
                node_id=nid, field=f"{where}.config.model")
    elif ntype == "condition":
        req("expression", "condition nodes require 'config.expression'")
    elif ntype == "switch":
        routes = config.get("routes")
        if not isinstance(routes, list) or not routes:
            err("NODE_CONFIG_REQUIRED",
                f"Node {nid!r} requires a non-empty 'config.routes' list of {{name, expression}}.",
                node_id=nid, field=f"{where}.config.routes")
        else:
            seen: set[str] = set()
            for r in routes:
                name = r.get("name") if isinstance(r, dict) else None
                if not isinstance(name, str) or not name:
                    err("NODE_CONFIG_REQUIRED",
                        f"Node {nid!r} routes require a non-empty 'name'.",
                        node_id=nid, field=f"{where}.config.routes")
                elif name in seen:
                    err("NODE_CONFIG_REQUIRED",
                        f"Node {nid!r} has a duplicate route name {name!r}.",
                        node_id=nid, field=f"{where}.config.routes")
                else:
                    seen.add(name)
                if isinstance(r, dict) and not r.get("expression"):
                    err("NODE_CONFIG_REQUIRED",
                        f"Node {nid!r} route {name!r} requires an 'expression'.",
                        node_id=nid, field=f"{where}.config.routes")
    elif ntype == "merge":
        pass  # Fan-in only; no required config.
    elif ntype == "set":
        if not isinstance(config.get("values"), dict) or not config.get("values"):
            err("NODE_CONFIG_REQUIRED",
                f"Node {nid!r} requires a non-empty 'config.values' object.",
                node_id=nid, field=f"{where}.config.values")
    elif ntype == "filter":
        req("predicate", "filter nodes require 'config.predicate'")
    elif ntype == "map":
        req("items", "map nodes require 'config.items' (collection expression)")
        req("expression", "map nodes require 'config.expression' (per-item expression)")
    elif ntype == "variable":
        if config.get("mode", "set") not in {"set", "get"}:
            err("NODE_CONFIG_REQUIRED",
                f"Node {nid!r} 'config.mode' must be 'set' or 'get'.",
                node_id=nid, field=f"{where}.config.mode")
        req("name", "variable nodes require 'config.name'")
    elif ntype == "subworkflow":
        if not config.get("workflow_id"):
            err("NODE_CONFIG_REQUIRED",
                f"Node {nid!r} requires 'config.workflow_id' (referenced workflow).",
                node_id=nid, field=f"{where}.config.workflow_id")
    elif ntype == "loop":
        req("items", "loop nodes require 'config.items' (collection expression)")
        mi = config.get("max_iterations", 100)
        if not isinstance(mi, int) or mi < 1 or mi > 10000:
            err("NODE_CONFIG_REQUIRED",
                f"Node {nid!r} 'config.max_iterations' must be an integer 1..10000.",
                node_id=nid, field=f"{where}.config.max_iterations")
    elif ntype == "transform":
        if not config.get("mapping") and not config.get("expression"):
            err("NODE_CONFIG_REQUIRED",
                f"Node {nid!r} requires 'config.mapping' or 'config.expression'.",
                node_id=nid, field=f"{where}.config.mapping")
    elif ntype == "approval":
        approvers = config.get("approvers")
        if not isinstance(approvers, list) or not approvers:
            err("NODE_CONFIG_REQUIRED",
                f"Node {nid!r} requires a non-empty 'config.approvers' list.",
                node_id=nid, field=f"{where}.config.approvers")
    elif ntype == "webhook":
        req("url", "webhook nodes require 'config.url'")
        method = str(config.get("method", "POST")).upper()
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            err("NODE_CONFIG_REQUIRED",
                f"Node {nid!r} 'config.method' must be a valid HTTP method.",
                node_id=nid, field=f"{where}.config.method")
    elif ntype == "tool":
        if not config.get("tool_id") and not config.get("tool_name"):
            err("NODE_CONFIG_REQUIRED",
                f"Node {nid!r} requires 'config.tool_id' or 'config.tool_name'.",
                node_id=nid, field=f"{where}.config.tool_id")
    elif ntype == "connector_action":
        action_id = str(config.get("action_id", "") or "")
        if not action_id or "." not in action_id:
            err("NODE_CONFIG_REQUIRED",
                f"Node {nid!r} requires 'config.action_id' (e.g. github.create_issue).",
                node_id=nid, field=f"{where}.config.action_id")
        timeout = config.get("timeout_seconds", 30)
        if not isinstance(timeout, int) or not 1 <= timeout <= 300:
            err("NODE_CONFIG_REQUIRED",
                f"Node {nid!r} 'config.timeout_seconds' must be 1..300.",
                node_id=nid, field=f"{where}.config.timeout_seconds")
    elif ntype == "connector_trigger":
        if not config.get("trigger_id"):
            err("NODE_CONFIG_REQUIRED",
                f"Node {nid!r} requires 'config.trigger_id'.",
                node_id=nid, field=f"{where}.config.trigger_id")
    elif ntype == "connector_search":
        req("query", "connector_search nodes require 'config.query'")
    elif ntype == "connector_resource":
        if str(config.get("kind", "") or "").lower() not in {
                "user", "message", "file", "folder", "repository", "issue",
                "pull_request", "task", "ticket", "customer", "invoice",
                "order", "calendar_event", "document", "database_row"}:
            err("NODE_CONFIG_REQUIRED",
                f"Node {nid!r} 'config.kind' must be a normalized resource kind.",
                node_id=nid, field=f"{where}.config.kind")
    elif ntype == "delay":
        dur = config.get("duration_seconds")
        if not isinstance(dur, (int, float)) or dur <= 0:
            err("NODE_CONFIG_REQUIRED",
                f"Node {nid!r} requires a positive 'config.duration_seconds'.",
                node_id=nid, field=f"{where}.config.duration_seconds")
    elif ntype == "browser_agent":
        req("objective", "browser_agent nodes require 'config.objective'")
        ms = config.get("max_steps", 100)
        if not isinstance(ms, int) or ms < 1 or ms > 500:
            err("NODE_CONFIG_REQUIRED",
                f"Node {nid!r} 'config.max_steps' must be an integer 1..500.",
                node_id=nid, field=f"{where}.config.max_steps")
        if config.get("allowed_domains") is not None and not isinstance(config.get("allowed_domains"), list):
            err("NODE_CONFIG_REQUIRED",
                f"Node {nid!r} 'config.allowed_domains' must be a list of domains.",
                node_id=nid, field=f"{where}.config.allowed_domains")
        rp = config.get("risk_policy") or {}
        if rp and str(rp.get("maxRiskLevel", "MEDIUM")) not in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}:
            err("NODE_CONFIG_REQUIRED",
                f"Node {nid!r} 'config.risk_policy.maxRiskLevel' is invalid.",
                node_id=nid, field=f"{where}.config.risk_policy")
    elif ntype == "browser_action":
        req("action_type", "browser_action nodes require 'config.action_type'")
        if str(config.get("action_type", "")).upper() not in {
                "NAVIGATE", "CLICK", "DOUBLE_CLICK", "TYPE", "FILL", "SELECT",
                "CHECK", "UNCHECK", "HOVER", "SCROLL", "PRESS_KEY", "DRAG",
                "DROP", "WAIT", "SCREENSHOT", "EXTRACT", "UPLOAD", "DOWNLOAD",
                "SWITCH_TAB", "GO_BACK", "GO_FORWARD", "RELOAD", "FOCUS"}:
            err("NODE_CONFIG_REQUIRED",
                f"Node {nid!r} 'config.action_type' is not a supported browser action.",
                node_id=nid, field=f"{where}.config.action_type")
    elif ntype == "browser_extract":
        req("selector", "browser_extract nodes require 'config.selector'")
    elif ntype == "code_agent":
        req("objective", "code_agent nodes require 'config.objective'")
        if not config.get("repository_id") and not config.get("repository"):
            err("NODE_CONFIG_REQUIRED",
                f"Node {nid!r} requires 'config.repository_id' or 'config.repository'.",
                node_id=nid, field=f"{where}.config.repository_id")
        ms = config.get("max_steps", 50)
        if not isinstance(ms, int) or ms < 1 or ms > 200:
            err("NODE_CONFIG_REQUIRED",
                f"Node {nid!r} 'config.max_steps' must be an integer 1..200.",
                node_id=nid, field=f"{where}.config.max_steps")
        for key in ("execution_policy", "review_policy", "approval_policy"):
            if config.get(key) is not None and not isinstance(config.get(key), dict):
                err("NODE_CONFIG_REQUIRED",
                    f"Node {nid!r} 'config.{key}' must be an object.",
                    node_id=nid, field=f"{where}.config.{key}")
    elif ntype in ("code_search",):
        req("query", f"{ntype} nodes require 'config.query'")
        if not config.get("workspace_id") and not config.get("repository_id"):
            err("NODE_CONFIG_REQUIRED",
                f"Node {nid!r} requires 'config.workspace_id' or 'config.repository_id'.",
                node_id=nid, field=f"{where}.config.workspace_id")
    elif ntype in ("code_read",):
        req("path", f"{ntype} nodes require 'config.path'")
    elif ntype in ("code_patch",):
        req("diff", f"{ntype} nodes require 'config.diff' (unified diff text)")
        if not config.get("task_id"):
            err("NODE_CONFIG_REQUIRED",
                f"Node {nid!r} requires 'config.task_id'.",
                node_id=nid, field=f"{where}.config.task_id")
    elif ntype in ("code_test", "code_lint"):
        req("command", f"{ntype} nodes require 'config.command'")
        if config.get("profile", "TEST") not in {
                "TEST", "LINT", "TYPECHECK", "BUILD", "PACKAGE", "MIGRATION"}:
            err("NODE_CONFIG_REQUIRED",
                f"Node {nid!r} 'config.profile' must be a known execution profile.",
                node_id=nid, field=f"{where}.config.profile")
    elif ntype in ("code_review",):
        if not config.get("task_id") and not config.get("diff"):
            err("NODE_CONFIG_REQUIRED",
                f"Node {nid!r} requires 'config.task_id' or 'config.diff'.",
                node_id=nid, field=f"{where}.config.task_id")
    elif ntype in ("git_commit",):
        req("message", f"{ntype} nodes require 'config.message'")
        if not config.get("task_id"):
            err("NODE_CONFIG_REQUIRED",
                f"Node {nid!r} requires 'config.task_id'.",
                node_id=nid, field=f"{where}.config.task_id")
    elif ntype in ("create_pr",):
        req("title", f"{ntype} nodes require 'config.title'")
        if not config.get("task_id"):
            err("NODE_CONFIG_REQUIRED",
                f"Node {nid!r} requires 'config.task_id'.",
                node_id=nid, field=f"{where}.config.task_id")
    elif ntype in ("verify",):
        checks = config.get("checks")
        if not isinstance(checks, list) or not checks:
            err("NODE_CONFIG_REQUIRED",
                f"Node {nid!r} requires a non-empty 'config.checks' list.",
                node_id=nid, field=f"{where}.config.checks")
        for i, check in enumerate(checks or []):
            if not isinstance(check, dict) or not check.get("kind"):
                err("NODE_CONFIG_REQUIRED",
                    f"Node {nid!r} check[{i}] requires a 'kind'.",
                    node_id=nid, field=f"{where}.config.checks")
    elif ntype in ("evaluate",):
        threshold = config.get("quality_threshold", 0.7)
        if not isinstance(threshold, (int, float)) or not 0 <= threshold <= 1:
            err("NODE_CONFIG_REQUIRED",
                f"Node {nid!r} 'config.quality_threshold' must be 0..1.",
                node_id=nid, field=f"{where}.config.quality_threshold")
    elif ntype in ("assert",):
        conditions = config.get("conditions")
        if not isinstance(conditions, list) or not conditions:
            err("NODE_CONFIG_REQUIRED",
                f"Node {nid!r} requires a non-empty 'config.conditions' list.",
                node_id=nid, field=f"{where}.config.conditions")
    elif ntype in ("quality_gate",):
        if not config.get("gate") and not config.get("definition"):
            err("NODE_CONFIG_REQUIRED",
                f"Node {nid!r} requires 'config.gate' or 'config.definition'.",
                node_id=nid, field=f"{where}.config.gate")
    elif ntype in ("retry",):
        mi = config.get("max_attempts", 3)
        if not isinstance(mi, int) or mi < 1 or mi > 10:
            err("NODE_CONFIG_REQUIRED",
                f"Node {nid!r} 'config.max_attempts' must be an integer 1..10.",
                node_id=nid, field=f"{where}.config.max_attempts")
    elif ntype in ("correct",):
        if config.get("strategy") and str(config["strategy"]).upper() not in {
                "RETRY_SAME", "RETRY_WITH_BACKOFF", "RETRY_WITH_NEW_MODEL",
                "RETRY_WITH_NEW_TOOL", "MODIFY_PARAMETERS", "REFINE_PROMPT",
                "EXPAND_CONTEXT", "REPLAN", "ROLLBACK", "ASK_ANOTHER_AGENT",
                "REQUEST_HUMAN", "STOP"}:
            err("NODE_CONFIG_REQUIRED",
                f"Node {nid!r} 'config.strategy' is not a known correction strategy.",
                node_id=nid, field=f"{where}.config.strategy")


def _switch_route_names(node: dict) -> set[str]:
    """Route names declared by a switch node (empty when misconfigured)."""
    routes = (node.get("config") or {}) if isinstance(node.get("config"), dict) else {}
    names: set[str] = set()
    for r in routes.get("routes", []) or []:
        if isinstance(r, dict) and isinstance(r.get("name"), str) and r["name"]:
            names.add(r["name"])
    return names


def _is_reference(value: Any) -> bool:
    """True when a string value is an expression/secret reference, not a literal."""
    return isinstance(value, str) and "{{" in value and "}}" in value


def _iter_string_leaves(value: Any, path: str = "") -> Any:
    """Yield (path, string) pairs for every string leaf in nested config."""
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from _iter_string_leaves(v, f"{path}.{k}" if path else str(k))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from _iter_string_leaves(v, f"{path}[{i}]")


def _check_no_literal_secrets(err, nid: str, config: dict, prefix: str) -> None:
    """Literal secret material must never live in a definition.

    Secrets travel as ``credential_id`` references or ``{{...}}`` expression
    references resolved at runtime. Anything else is rejected so exports,
    logs, and browser state stay secret-free.
    """
    for path, value in _iter_string_leaves(config):
        if not value.strip():
            continue
        leaf = path.split(".")[-1].lower()
        # Strip list indices: "headers[0].api_key" -> "api_key".
        leaf = leaf.split("[")[0]
        if leaf in REFERENCE_KEYS:
            continue
        if leaf in SECRET_LIKE_KEYS and not _is_reference(value):
            err("SECRET_VALUE",
                f"Node {nid!r}: '{path}' holds a literal secret. "
                f"Store it as a credential and reference 'credential_id' or '{{{{...}}}}' instead.",
                node_id=nid, field=f"{prefix}.{path}")


_EXPR_RE = re.compile(r"\{\{\s*(.*?)\s*\}\}")
# Namespaces the authoring layer understands; anything else is validated
# against declared variables / node ids.
_KNOWN_NAMESPACES = {"variables", "nodes", "workflow", "trigger", "run", "credentials", "env"}


def extract_expressions(value: Any) -> list[str]:
    """Collect raw ``{{...}}`` expression bodies from nested config (pure)."""
    found: list[str] = []
    for _, s in _iter_string_leaves(value):
        for m in _EXPR_RE.finditer(s):
            body = m.group(1).strip()
            if body:
                found.append(body)
    return found


def _check_expression_refs(warn, triggers: list, nodes_by_id: dict,
                           edges: list, var_names: set[str]) -> None:
    """Advisory checks for dangling expression references (never executed here)."""
    known_ids = set(nodes_by_id) | {
        t.get("id") for t in triggers if isinstance(t, dict) and t.get("id")
    }
    sources: list[tuple[Optional[str], Any]] = []
    for t in triggers:
        if isinstance(t, dict):
            sources.append((t.get("id"), t.get("config")))
    for nid, n in nodes_by_id.items():
        sources.append((nid, n.get("config")))
    for e in edges:
        if isinstance(e, dict) and isinstance(e.get("condition"), dict):
            sources.append((None, e["condition"].get("expression")))

    for nid, cfg in sources:
        for body in extract_expressions(cfg):
            head = body.split(".")[0].strip()
            if not head:
                warn("UNBALANCED_EXPRESSION",
                     f"Empty expression '{{{{...}}}}' near {body!r}.",
                     node_id=nid)
            elif head in _KNOWN_NAMESPACES:
                if head == "variables":
                    parts = body.split(".")
                    if len(parts) < 2 or parts[1].strip() not in var_names:
                        warn("UNKNOWN_VARIABLE_REFERENCE",
                             f"Expression '{{{{{body}}}}}' references an undeclared variable.",
                             node_id=nid)
                elif head == "nodes":
                    parts = body.split(".")
                    if len(parts) < 2 or parts[1].strip() not in known_ids:
                        warn("UNKNOWN_NODE_REFERENCE",
                             f"Expression '{{{{{body}}}}}' references an unknown node.",
                             node_id=nid)
            elif head not in var_names and head not in known_ids:
                warn("UNKNOWN_REFERENCE",
                     f"Expression '{{{{{body}}}}}' matches no declared variable or node. "
                     f"Use '{{{{variables.name}}}}' or '{{{{nodes.<id>....}}}}'.",
                     node_id=nid)

    # Unbalanced delimiters.
    for nid, cfg in sources:
        for path, s in _iter_string_leaves(cfg):
            if "{{" in s and s.count("{{") != s.count("}}"):
                warn("UNBALANCED_EXPRESSION",
                     f"Unbalanced '{{{{...}}}}' in '{path}'.",
                     node_id=nid)

    # Unused variables.
    used: set[str] = set()
    for _, cfg in sources:
        for body in extract_expressions(cfg):
            parts = body.split(".")
            if parts[0].strip() == "variables" and len(parts) > 1:
                used.add(parts[1].strip())
            elif len(parts) == 1 and parts[0].strip() in var_names:
                used.add(parts[0].strip())
    for name in sorted(var_names - used):
        warn("UNUSED_VARIABLE",
             f"Variable {name!r} is declared but never referenced.")


def _check_cycles(err, all_ids: set[str], outgoing: dict[str, list[str]]) -> None:
    """Detect cycles (v1 supports DAGs only). Reports one error per cycle found."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {i: WHITE for i in all_ids}

    def visit(start: str) -> None:
        stack: list[tuple[str, Any]] = [(start, iter(sorted(outgoing.get(start, []))))]
        path: list[str] = [start]
        color[start] = GRAY
        while stack:
            node, it = stack[-1]
            advanced = False
            for nxt in it:
                if color[nxt] == GRAY:
                    cycle = path[path.index(nxt):] + [nxt]
                    err("CYCLE_DETECTED",
                        f"Cycle detected: {' -> '.join(cycle)}. Only acyclic graphs are supported in v1.",
                        node_id=nxt)
                    continue
                if color[nxt] == WHITE:
                    color[nxt] = GRAY
                    stack.append((nxt, iter(sorted(outgoing.get(nxt, [])))))
                    path.append(nxt)
                    advanced = True
                    break
            if not advanced:
                color[node] = BLACK
                stack.pop()
                path.pop()

    for nid in sorted(all_ids):
        if color[nid] == WHITE:
            visit(nid)


def empty_definition() -> dict[str, Any]:
    """Blank authoring starting point (matches frontend template)."""
    return {
        "schema_version": SCHEMA_VERSION,
        "triggers": [],
        "nodes": [],
        "edges": [],
        "variables": [],
        "settings": {},
    }


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    return slug[:100] or "workflow"


ENVELOPE_FORMAT = "openagent-workflow"


def migrate_definition(definition: Any) -> tuple[Any, bool, Optional[str]]:
    """Migrate a definition to the current schema version.

    Returns (definition, migrated, error). Only ``1.0`` exists today, so
    this is a compatibility gate with room for 1.1/2.0 migrations later.
    Never raises on bad input.
    """
    if not _is_dict(definition):
        return definition, False, "Definition must be a JSON object."
    version = definition.get("schema_version")
    if version == SCHEMA_VERSION:
        return definition, False, None
    if version in SUPPORTED_SCHEMA_VERSIONS:
        migrated = dict(definition)
        migrated["schema_version"] = SCHEMA_VERSION
        return migrated, True, None
    return (
        definition,
        False,
        f"Unsupported schema_version {version!r}. Supported: {sorted(SUPPORTED_SCHEMA_VERSIONS)}.",
    )


def build_envelope(workflow_name: str, slug: str, description: Optional[str],
                   tags: list[str], definition: dict) -> dict[str, Any]:
    """Portable export envelope. Never includes secrets: definitions store
    only credential_id / {{...}} references (enforced by validation)."""
    return {
        "format": ENVELOPE_FORMAT,
        "schemaVersion": SCHEMA_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "workflow": {
            "name": workflow_name,
            "slug": slug,
            "description": description,
            "tags": tags,
            "definition": definition,
        },
    }


def parse_envelope(payload: Any) -> tuple[Optional[dict], Optional[str]]:
    """Accept an export envelope or a raw definition (backward compatible).

    Returns (definition, error). Enforces a 1 MiB size cap before parsing
    is the caller's job; this validates structure only.
    """
    if not _is_dict(payload):
        return None, "Payload must be a JSON object."
    if payload.get("format") == ENVELOPE_FORMAT or "workflow" in payload:
        wf = payload.get("workflow")
        if not _is_dict(wf):
            return None, "Envelope 'workflow' must be an object."
        definition = wf.get("definition", wf)
        meta = {k: wf.get(k) for k in ("name", "slug", "description", "tags")}
    else:
        definition, meta = payload, {}
    migrated, _, migration_error = migrate_definition(definition)
    if migration_error:
        return None, migration_error
    return {"definition": migrated, "meta": meta}, None
