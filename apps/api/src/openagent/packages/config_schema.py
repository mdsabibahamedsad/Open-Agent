"""MP22: declarative configuration schema.

Packages declare ``configuration.inputs`` (JSON-schema-ish) so the install
wizard UI can be generated and values validated server-side. Secret-bearing
inputs use ``secret_reference`` / ``credential_reference`` /
``connector_reference`` field types: the value stored is always a *reference*
(credential id / connection id), never the raw secret.

Secret *values* are rejected outright by :func:`validate_configuration`.
"""

from __future__ import annotations

import re
from typing import Any

SUPPORTED_FIELD_TYPES = (
    "text",
    "number",
    "boolean",
    "enum",
    "secret_reference",
    "credential_reference",
    "connector_reference",
    "tool_reference",
    "model_preset",
    "agent_reference",
    "workflow_reference",
    "file",
    "json",
    "array",
    "object",
)

_REFERENCE_TYPES = frozenset(
    {
        "secret_reference",
        "credential_reference",
        "connector_reference",
        "tool_reference",
        "agent_reference",
        "workflow_reference",
    }
)

#: Heuristic patterns that indicate a raw secret was pasted where a
#: reference belongs (or anywhere inside exported package data).
_SECRET_VALUE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"sk-(live|test)-[A-Za-z0-9]{8,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{8,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{8,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)(api[_-]?key|password|passwd|secret|access[_-]?token|refresh[_-]?token)\s*[:=]\s*['\"]?[^'\"\s]{8,}"),
)

#: Keys that must never carry inline values inside package payloads.
_SECRET_KEY_NAMES = frozenset(
    {
        "api_key",
        "apikey",
        "password",
        "secret",
        "access_token",
        "refresh_token",
        "private_key",
        "cookie",
        "session_token",
        "database_password",
        "payment_credential",
    }
)


class ConfigSchemaError(ValueError):
    """Raised for malformed configuration schemas or values."""


def validate_config_schema(schema: dict[str, Any]) -> list[str]:
    """Validate the *shape* of a configuration schema.

    Returns a list of problem strings (empty when valid).
    """
    problems: list[str] = []
    if not isinstance(schema, dict):
        return ["configuration schema must be an object"]
    inputs = schema.get("inputs", {})
    if not isinstance(inputs, dict):
        return ["configuration.inputs must be an object"]
    for name, field in inputs.items():
        if not isinstance(field, dict):
            problems.append(f"input {name!r} must be an object")
            continue
        ftype = field.get("type", "text")
        if ftype not in SUPPORTED_FIELD_TYPES:
            problems.append(f"input {name!r} has unsupported type {ftype!r}")
        if "default" in field and field.get("required") and ftype in _REFERENCE_TYPES:
            problems.append(
                f"input {name!r}: reference types must not carry inline defaults"
            )
        if ftype == "enum" and not isinstance(field.get("options"), list):
            problems.append(f"input {name!r}: enum requires an 'options' list")
    return problems


def _check_type(name: str, ftype: str, value: Any, field: dict[str, Any]) -> str | None:
    if ftype == "text":
        return None if isinstance(value, str) else f"{name!r} must be a string"
    if ftype == "number":
        return None if isinstance(value, (int, float)) and not isinstance(value, bool) else f"{name!r} must be a number"
    if ftype == "boolean":
        return None if isinstance(value, bool) else f"{name!r} must be a boolean"
    if ftype == "enum":
        options = field.get("options", [])
        return None if value in options else f"{name!r} must be one of {options!r}"
    if ftype in _REFERENCE_TYPES:
        if not isinstance(value, str) or not value.strip():
            return f"{name!r} must be a non-empty reference id"
        if _looks_like_secret_value(value):
            return f"{name!r} looks like a raw secret; provide a reference instead"
        return None
    if ftype == "json":
        return None  # any JSON value accepted
    if ftype == "array":
        return None if isinstance(value, list) else f"{name!r} must be an array"
    if ftype == "object":
        return None if isinstance(value, dict) else f"{name!r} must be an object"
    if ftype == "file":
        return None if isinstance(value, str) else f"{name!r} must be a file reference"
    if ftype == "model_preset":
        return None if isinstance(value, str) else f"{name!r} must be a model preset reference"
    return f"{name!r} has unsupported type {ftype!r}"


def validate_configuration(
    schema: dict[str, Any], values: dict[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    """Validate user ``values`` against ``schema``.

    Returns ``(resolved, errors)`` where ``resolved`` merges defaults with
    provided values. ``errors`` is empty on success.
    """
    errors: list[str] = []
    resolved: dict[str, Any] = {}
    inputs = schema.get("inputs", {}) if isinstance(schema, dict) else {}
    if not isinstance(inputs, dict):
        return {}, ["configuration.inputs must be an object"]
    for name, field in inputs.items():
        if not isinstance(field, dict):
            errors.append(f"input {name!r} must be an object")
            continue
        ftype = str(field.get("type", "text"))
        required = bool(field.get("required", False))
        if name in values:
            problem = _check_type(name, ftype, values[name], field)
            if problem:
                errors.append(problem)
            else:
                resolved[name] = values[name]
        elif "default" in field:
            resolved[name] = field["default"]
        elif required:
            errors.append(f"missing required input: {name!r}")
    # Reject unexpected keys carrying secret-ish names (defense in depth).
    for name, value in values.items():
        if name not in inputs and isinstance(value, str) and _looks_like_secret_value(value):
            errors.append(f"input {name!r} looks like a raw secret and is not declared")
    return resolved, errors


def required_references(schema: dict[str, Any]) -> list[dict[str, str]]:
    """List credential/connector/secret inputs the installer must collect."""
    refs: list[dict[str, str]] = []
    inputs = schema.get("inputs", {}) if isinstance(schema, dict) else {}
    for name, field in inputs.items():
        if isinstance(field, dict) and field.get("type") in (
            "secret_reference",
            "credential_reference",
            "connector_reference",
        ):
            refs.append(
                {
                    "name": name,
                    "type": str(field.get("type")),
                    "credential_type": str(field.get("credential_type", "")),
                    "required_scope": str(field.get("required_scope", "")),
                    "required": str(bool(field.get("required", False))),
                }
            )
    return refs


def _looks_like_secret_value(value: str) -> bool:
    if not isinstance(value, str):
        return False
    return any(pattern.search(value) for pattern in _SECRET_VALUE_PATTERNS)


def find_secret_values(payload: Any, path: str = "$") -> list[dict[str, str]]:
    """Recursively scan ``payload`` for embedded raw secrets.

    Returns findings ``[{path, reason}]``. Used by the security scanner and
    the export pipeline (export must never contain raw secrets).
    """
    findings: list[dict[str, str]] = []

    def visit(node: Any, current: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                child = f"{current}.{key}"
                if (
                    isinstance(key, str)
                    and key.lower() in _SECRET_KEY_NAMES
                    and isinstance(value, str)
                    and value.strip()
                ):
                    findings.append(
                        {"path": child, "reason": f"inline secret key {key!r}"}
                    )
                visit(value, child)
        elif isinstance(node, list):
            for index, value in enumerate(node):
                visit(value, f"{current}[{index}]")
        elif isinstance(node, str) and _looks_like_secret_value(node):
            findings.append({"path": current, "reason": "value matches secret pattern"})

    visit(payload, path)
    return findings


def ui_fields(schema: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert a configuration schema into UI field descriptors."""
    inputs = schema.get("inputs", {}) if isinstance(schema, dict) else {}
    fields: list[dict[str, Any]] = []
    for name, field in inputs.items():
        if not isinstance(field, dict):
            continue
        fields.append(
            {
                "name": name,
                "type": field.get("type", "text"),
                "label": field.get("label", name.replace("_", " ").title()),
                "description": field.get("description", ""),
                "required": bool(field.get("required", False)),
                "default": field.get("default"),
                "options": field.get("options", []),
                "sensitive": field.get("type") in _REFERENCE_TYPES,
            }
        )
    return fields
