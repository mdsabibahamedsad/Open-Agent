"""Data mapping + transforms (MP21).

External objects map to OpenAgent normalized resources through declarative
mapping specs. Path expressions use a safe dotted resolver (no code exec);
transforms reuse a small closed op set. Normalized records keep
provider/provider_id/raw_reference so nothing is lost.
"""

from __future__ import annotations

from typing import Any


def resolve_path(source: Any, path: str, default: Any = None) -> Any:
    """Safe dotted-path resolver over dicts/lists ('a.b.0.c')."""
    if not path:
        return source
    node = source
    for part in str(path).split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        else:
            return default
    return node


def _template(text: str, source: dict[str, Any]) -> str:
    import re

    def _replace(match: "re.Match[str]") -> str:
        return str(resolve_path(source, match.group(1).strip(), ""))

    return re.sub(r"\{\{\s*([a-zA-Z0-9_.]+)\s*\}\}", _replace, text)


def apply_transform(value: Any, transform: dict[str, Any],
                    source: dict[str, Any]) -> Any:
    """Closed transform op set: rename/map/filter/flatten/merge/format/
    parse/extract/template. Unknown ops raise (fail closed)."""
    op = str(transform.get("op", "")).lower()
    if op == "rename":
        return value
    if op == "map":
        table = transform.get("table", {}) or {}
        return table.get(str(value), transform.get("default", value))
    if op == "filter":
        keep = set(transform.get("keep", []) or [])
        if isinstance(value, dict):
            return {k: v for k, v in value.items() if k in keep}
        if isinstance(value, list):
            return [v for v in value if v in keep]
        return value
    if op == "flatten":
        flat: list[Any] = []

        def _walk(node: Any) -> None:
            if isinstance(node, list):
                for item in node:
                    _walk(item)
            else:
                flat.append(node)
        _walk(value)
        return flat
    if op == "merge":
        base = dict(transform.get("with", {}) or {})
        if isinstance(value, dict):
            base.update(value)
            return base
        return value
    if op == "format":
        return str(transform.get("format", "{value}")).replace("{value}", str(value))
    if op == "parse":
        fmt = str(transform.get("format", "json")).lower()
        if fmt == "json" and isinstance(value, str):
            import json
            try:
                return json.loads(value)
            except Exception as exc:
                raise ValueError(f"parse failed: {exc}") from exc
        raise ValueError(f"Unsupported parse format '{fmt}'")
    if op == "extract":
        return resolve_path(value, str(transform.get("path", "")),
                            transform.get("default"))
    if op == "template":
        # Placeholders use {{dotted.path}} (workflow-expression style);
        # {{value}} refers to the current value.
        scope = dict(source) if isinstance(source, dict) else {}
        scope["value"] = value
        return _template(str(transform.get("template", "")), scope)
    raise ValueError(f"Unknown transform op '{op}'")


def apply_mapping(source: dict[str, Any], mapping: dict[str, Any]) -> dict[str, Any]:
    """Map one external object to a normalized record.

    mapping: {"fields": {out: {"from": "dotted.path", "default": x,
                               "transform": {...} | [...]}},
              "constants": {...}}
    """
    fields = mapping.get("fields", {}) or {}
    if not isinstance(fields, dict):
        raise ValueError("mapping.fields must be an object")
    out: dict[str, Any] = dict(mapping.get("constants", {}) or {})
    for name, spec in fields.items():
        if isinstance(spec, str):
            out[name] = resolve_path(source, spec)
            continue
        if not isinstance(spec, dict):
            raise ValueError(f"Field '{name}' spec must be a path or object")
        value = resolve_path(source, str(spec.get("from", "")),
                             spec.get("default"))
        transforms = spec.get("transform", [])
        if isinstance(transforms, dict):
            transforms = [transforms]
        for transform in transforms or []:
            value = apply_transform(value, transform, source)
        out[name] = value
    return out
