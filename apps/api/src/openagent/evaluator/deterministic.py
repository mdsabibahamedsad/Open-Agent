"""Deterministic verifiers (MP20). Pure functions — no I/O, no LLM.

Verification is preferred over LLM evaluation whenever observable evidence
exists: status codes, file hashes, test summaries, node states, DOM state,
commit SHAs. Each verifier returns a CheckResult; the engine decides.
"""

from __future__ import annotations

from typing import Any, Callable

from openagent.evaluator.types import CheckResult

# -- JSON schema subset ------------------------------------------------------
# Hand-rolled (no new dependencies): object/array/string/number/integer/
# boolean/null, required, properties, items, enum, minimum/maximum,
# minLength/maxLength, additionalProperties.

_TYPE_NAMES = {"object": dict, "array": list, "string": str, "number": (int, float),
               "integer": int, "boolean": bool, "null": type(None)}


def validate_json_schema(data: Any, schema: dict[str, Any],
                         path: str = "$") -> list[str]:
    """Return a list of violation messages (empty = valid)."""
    errors: list[str] = []
    if not isinstance(schema, dict):
        return [f"{path}: schema must be an object"]
    expected = schema.get("type")
    if expected is not None:
        py = _TYPE_NAMES.get(str(expected))
        if py is None:
            return [f"{path}: unknown type '{expected}'"]
        if isinstance(py, tuple):
            ok = isinstance(data, py) and not isinstance(data, bool)
        elif py is int:
            ok = isinstance(data, int) and not isinstance(data, bool)
        elif py is type(None):
            ok = data is None
        else:
            ok = isinstance(data, py)
        if not ok:
            return [f"{path}: expected {expected}, got {type(data).__name__}"]
    if isinstance(data, dict):
        for req in schema.get("required", []) or []:
            if req not in data:
                errors.append(f"{path}: missing required field '{req}'")
        props = schema.get("properties", {}) or {}
        for key, subschema in props.items():
            if key in data:
                errors.extend(validate_json_schema(data[key], subschema, f"{path}.{key}"))
        if schema.get("additionalProperties") is False:
            for key in data:
                if key not in props:
                    errors.append(f"{path}: unexpected field '{key}'")
    if isinstance(data, list) and isinstance(schema.get("items"), dict):
        for i, item in enumerate(data):
            errors.extend(validate_json_schema(item, schema["items"], f"{path}[{i}]"))
    if "enum" in schema and data not in schema["enum"]:
        errors.append(f"{path}: value not in enum {schema['enum']}")
    if isinstance(data, (int, float)) and not isinstance(data, bool):
        if schema.get("minimum") is not None and data < schema["minimum"]:
            errors.append(f"{path}: {data} < minimum {schema['minimum']}")
        if schema.get("maximum") is not None and data > schema["maximum"]:
            errors.append(f"{path}: {data} > maximum {schema['maximum']}")
    if isinstance(data, str):
        if schema.get("minLength") is not None and len(data) < schema["minLength"]:
            errors.append(f"{path}: shorter than minLength {schema['minLength']}")
        if schema.get("maxLength") is not None and len(data) > schema["maxLength"]:
            errors.append(f"{path}: longer than maxLength {schema['maxLength']}")
    return errors


# -- individual verifiers ----------------------------------------------------

def verify_http(response: dict[str, Any], params: dict[str, Any]) -> CheckResult:
    """response: {status, body?, latency_ms?}. params: expected_status,
    required_fields, max_latency_ms, schema?"""
    status = response.get("status")
    expected = params.get("expected_status", 200)
    if isinstance(expected, list):
        ok = status in expected
    else:
        ok = status == expected
    if not ok:
        return CheckResult("http_status", False,
                           f"HTTP {status} != expected {expected}")
    reasons: list[str] = []
    body = response.get("body", {})
    for f in params.get("required_fields", []) or []:
        if isinstance(body, dict) and f not in body:
            return CheckResult("http_fields", False, f"missing field '{f}'")
    max_lat = params.get("max_latency_ms")
    if max_lat is not None and isinstance(response.get("latency_ms"), (int, float)):
        if response["latency_ms"] > max_lat:
            return CheckResult("http_latency", False,
                               f"latency {response['latency_ms']}ms > {max_lat}ms")
    schema = params.get("schema")
    if schema:
        violations = validate_json_schema(body, schema)
        if violations:
            return CheckResult("http_schema", False, "; ".join(violations[:5]))
    return CheckResult("http_response", True,
                       reasons[0] if reasons else f"HTTP {status} verified")


def verify_json_schema_check(output: Any, params: dict[str, Any]) -> CheckResult:
    schema = params.get("schema") or {}
    violations = validate_json_schema(output, schema)
    if violations:
        return CheckResult("json_schema", False, "; ".join(violations[:5]))
    return CheckResult("json_schema", True, "output validates against schema")


def verify_file_state(state: dict[str, Any], params: dict[str, Any]) -> CheckResult:
    """state: {exists, sha256?, size_bytes?, content?}. params: must_exist,
    expected_hash, min_size, max_size, schema?, contains?"""
    if params.get("must_exist", True) and not state.get("exists"):
        return CheckResult("file_exists", False, "file does not exist")
    if params.get("expected_hash") and state.get("sha256"):
        if state["sha256"] != params["expected_hash"]:
            return CheckResult("file_hash", False, "hash mismatch")
    size = state.get("size_bytes")
    if isinstance(size, (int, float)):
        if params.get("min_size") is not None and size < params["min_size"]:
            return CheckResult("file_size", False, f"size {size} < min {params['min_size']}")
        if params.get("max_size") is not None and size > params["max_size"]:
            return CheckResult("file_size", False, f"size {size} > max {params['max_size']}")
    for needle in params.get("contains", []) or []:
        content = state.get("content", "")
        if needle not in str(content):
            return CheckResult("file_content", False, f"missing expected text '{needle}'")
    schema = params.get("schema")
    if schema and state.get("content") is not None:
        import json as _json
        try:
            doc = state["content"] if isinstance(state["content"], dict) \
                else _json.loads(state["content"])
        except Exception:
            return CheckResult("file_schema", False, "content is not valid JSON")
        violations = validate_json_schema(doc, schema)
        if violations:
            return CheckResult("file_schema", False, "; ".join(violations[:5]))
    return CheckResult("file_state", True, "file state verified")


def verify_test_summary(summary: dict[str, Any], params: dict[str, Any]) -> CheckResult:
    """summary: {passed, failed, errors?, skipped?}. params: max_failures (default 0)."""
    failed = int(summary.get("failed", 0) or 0) + int(summary.get("errors", 0) or 0)
    allowed = int(params.get("max_failures", 0))
    if failed > allowed:
        return CheckResult("tests", False,
                           f"{failed} failing tests (allowed {allowed})")
    if int(summary.get("passed", 0) or 0) <= 0 and params.get("require_passed", True):
        return CheckResult("tests", False, "no passing tests recorded")
    return CheckResult("tests", True,
                       f"{summary.get('passed', 0)} passed, {failed} failed")


def verify_workflow_nodes(node_states: dict[str, str],
                          params: dict[str, Any]) -> CheckResult:
    """node_states: {node_id: status}. params: required_nodes[], forbid_failed=True."""
    for node in params.get("required_nodes", []) or []:
        state = str(node_states.get(node, "missing")).upper()
        if state not in ("SUCCEEDED", "SUCCESS", "COMPLETED", "PASSED"):
            return CheckResult("workflow_nodes", False,
                               f"node '{node}' not successful (is {state})")
    if params.get("forbid_failed", True):
        bad = [n for n, s in node_states.items()
               if str(s).upper() in ("FAILED", "ERROR", "TIMED_OUT")]
        if bad:
            return CheckResult("workflow_nodes", False,
                               f"failed nodes: {', '.join(bad[:5])}")
    return CheckResult("workflow_nodes", True, "required nodes succeeded")


def verify_browser_state(state: dict[str, Any], params: dict[str, Any]) -> CheckResult:
    """state: {url?, title?, dom?, has_selector?, success_text?, challenge?}.
    params: expected_url_contains?, required_selector?, success_text?,
    forbid_challenge=True."""
    if params.get("expected_url_contains"):
        url = str(state.get("url", ""))
        if params["expected_url_contains"] not in url:
            return CheckResult("browser_url", False,
                               f"URL '{url}' lacks '{params['expected_url_contains']}'")
    if params.get("required_selector") and not state.get("has_selector"):
        return CheckResult("browser_dom", False,
                           f"selector '{params['required_selector']}' not found")
    if params.get("success_text"):
        blob = f"{state.get('title', '')}\n{state.get('dom', '')}"
        if params["success_text"] not in blob:
            return CheckResult("browser_success", False, "success indicator absent")
    if params.get("forbid_challenge", True) and state.get("challenge"):
        return CheckResult("browser_challenge", False,
                           f"unresolved challenge: {state['challenge']}")
    return CheckResult("browser_state", True, "browser state verified")


def verify_git_state(state: dict[str, Any], params: dict[str, Any]) -> CheckResult:
    """state: {commit_sha?, branch?, diff_files?}. params: require_commit,
    branch?, must_include_files?"""
    if params.get("require_commit", True) and not state.get("commit_sha"):
        return CheckResult("git_commit", False, "no commit recorded")
    if params.get("branch") and state.get("branch") != params["branch"]:
        return CheckResult("git_branch", False,
                           f"branch '{state.get('branch')}' != '{params['branch']}'")
    for f in params.get("must_include_files", []) or []:
        if f not in (state.get("diff_files") or []):
            return CheckResult("git_files", False, f"file '{f}' not in diff")
    return CheckResult("git_state", True, "git state verified")


def verify_side_effect(report: dict[str, Any], params: dict[str, Any]) -> CheckResult:
    """report: {provider_success, provider_id?, independently_verified?}.
    A provider claim alone is never enough: independent verification required
    unless params.allow_provider_only is set (discouraged)."""
    if not report.get("provider_success"):
        return CheckResult("side_effect_provider", False, "provider reported failure")
    if report.get("independently_verified"):
        return CheckResult("side_effect", True, "side effect independently verified")
    if params.get("allow_provider_only"):
        return CheckResult("side_effect", True, "provider-only (weak verification)",
                           critical_safety=False)
    return CheckResult("side_effect", False,
                       "provider claim without independent verification")


def verify_secret_scan(scan: dict[str, Any], params: dict[str, Any]) -> CheckResult:
    """scan: {findings: [..]}. Any finding fails unless explicitly waived."""
    findings = scan.get("findings", []) or []
    if findings and not params.get("waive"):
        kinds = sorted({str(f.get("kind", "secret")) for f in findings
                        if isinstance(f, dict)})
        return CheckResult("secret_scan", False,
                           f"secret-like content: {', '.join(kinds[:5])}",
                           critical_safety=True)
    return CheckResult("secret_scan", True, "no secret-like content")


def verify_output_contains(output: Any, params: dict[str, Any]) -> CheckResult:
    blob = str(output or "")
    for needle in params.get("contains", []) or []:
        if needle not in blob:
            return CheckResult("output_contains", False, f"missing '{needle}'")
    for needle in params.get("absent", []) or []:
        if needle in blob:
            return CheckResult("output_absent", False, f"forbidden text '{needle}' present")
    return CheckResult("output_contains", True, "output markers verified")


# Registry: check-kind -> verifier(output_or_state, params).
VERIFIERS: dict[str, Callable[[Any, dict[str, Any]], CheckResult]] = {
    "http_response": lambda out, p: verify_http(out if isinstance(out, dict) else {}, p),
    "json_schema": verify_json_schema_check,
    "file_state": lambda out, p: verify_file_state(out if isinstance(out, dict) else {}, p),
    "test_summary": lambda out, p: verify_test_summary(out if isinstance(out, dict) else {}, p),
    "workflow_nodes": lambda out, p: verify_workflow_nodes(
        out if isinstance(out, dict) else {}, p),
    "browser_state": lambda out, p: verify_browser_state(out if isinstance(out, dict) else {}, p),
    "git_state": lambda out, p: verify_git_state(out if isinstance(out, dict) else {}, p),
    "side_effect": lambda out, p: verify_side_effect(out if isinstance(out, dict) else {}, p),
    "secret_scan": lambda out, p: verify_secret_scan(out if isinstance(out, dict) else {}, p),
    "output_contains": verify_output_contains,
}


def run_check(kind: str, target: Any, params: dict[str, Any],
              name: str = "", required: bool = True) -> CheckResult:
    verifier = VERIFIERS.get((kind or "").lower())
    if verifier is None:
        return CheckResult(name or kind, False, f"unknown check kind '{kind}'",
                           required=required)
    try:
        result = verifier(target, params or {})
    except Exception as exc:
        return CheckResult(name or kind, False, f"check crashed: {exc}",
                           required=required)
    result.name = name or result.name
    result.required = required
    return result
