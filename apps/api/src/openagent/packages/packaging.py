"""MP22: portable package export / import.

Bundle layout (``openagent-package/``)::

    manifest.json
    resources/<kind>/<slug>.json
    skills/<slug>.json
    presets/<kind>/<slug>.json
    schemas/configuration.json
    assets/<file>
    integrity.json

``integrity.json`` maps every relative path to its sha256 hex digest plus a
top-level ``manifest_hash``. Export strips raw secrets (hard failure if any
are found — the caller must convert them to references first). Import
parses, verifies integrity, checks signatures when present, re-runs the
security scan and returns a preview of pending changes without writing.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from openagent.packages import config_schema, validation
from openagent.packages.manifest import parse_manifest
from openagent.packages.signing import SignatureRecord, content_hash

_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

_EXPORT_SECRET_BLOCKLIST = (
    "SECRET_LEAK",
)


class PackagingError(ValueError):
    """Raised when export/import cannot proceed safely."""


def _check_safe_name(name: str) -> None:
    if not _SAFE_NAME.match(name) or ".." in name or name.startswith((".", "/")):
        raise PackagingError(f"unsafe asset/filename: {name!r}")


def build_export_files(manifest_dict: dict[str, Any]) -> dict[str, str]:
    """Build the portable file map ``{relative_path: text_content}``.

    Raises PackagingError when raw secrets are detected — export must never
    contain them.
    """
    manifest = parse_manifest(manifest_dict)
    leaks = config_schema.find_secret_values(manifest_dict)
    if leaks:
        paths = ", ".join(hit["path"] for hit in leaks[:5])
        raise PackagingError(
            f"export blocked: raw secrets detected at {paths}; "
            "convert them to credential_reference entries first"
        )
    files: dict[str, str] = {}
    canonical = manifest.model_dump()
    files["manifest.json"] = json.dumps(canonical, indent=2, sort_keys=True) + "\n"
    for resource in manifest.resources:
        kind = re.sub(r"[^A-Za-z0-9_-]", "_", resource.kind.lower()) or "misc"
        files[f"resources/{kind}/{resource.slug}.json"] = json.dumps(
            resource.model_dump(), indent=2, sort_keys=True
        ) + "\n"
    if manifest.configuration:
        files["schemas/configuration.json"] = json.dumps(
            manifest.configuration, indent=2, sort_keys=True
        ) + "\n"
    for kind in ("model_requirements", "memory_requirements", "browser_requirements",
                 "code_requirements", "evaluation"):
        payload = canonical.get(kind) or {}
        if payload:
            files[f"schemas/{kind}.json"] = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    integrity: dict[str, str] = {}
    for path, content in files.items():
        integrity[path] = hashlib.sha256(content.encode("utf-8")).hexdigest()
    integrity["manifest.json#content"] = content_hash(canonical)
    files["integrity.json"] = json.dumps(
        {"files": integrity, "manifest_hash": content_hash(canonical)}, indent=2, sort_keys=True
    ) + "\n"
    return files


def parse_import_files(files: dict[str, str]) -> dict[str, Any]:
    """Parse an imported file map; verify layout + integrity hashes."""
    if "manifest.json" not in files or "integrity.json" not in files:
        raise PackagingError("bundle must contain manifest.json and integrity.json")
    try:
        integrity_doc = json.loads(files["integrity.json"])
    except json.JSONDecodeError as exc:
        raise PackagingError(f"integrity.json is not valid JSON: {exc}") from exc
    expected: dict[str, str] = integrity_doc.get("files", {})
    for path, content in files.items():
        if path == "integrity.json":
            continue
        _check_safe_name(path.split("/")[-1])
        if ".." in path or path.startswith("/"):
            raise PackagingError(f"path traversal in bundle entry: {path!r}")
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if path in expected and expected[path] != digest:
            raise PackagingError(f"integrity mismatch for {path!r}")
    try:
        manifest_dict = json.loads(files["manifest.json"])
    except json.JSONDecodeError as exc:
        raise PackagingError(f"manifest.json is not valid JSON: {exc}") from exc
    manifest = parse_manifest(manifest_dict)
    if expected.get("manifest.json#content") and expected["manifest.json#content"] != content_hash(
        manifest.model_dump()
    ):
        raise PackagingError("manifest content hash does not match integrity record")
    return manifest_dict


def import_preview(
    files: dict[str, str],
    signature: SignatureRecord | None = None,
    verify_signature=None,
) -> dict[str, Any]:
    """Validate an import and preview pending changes (no writes)."""
    manifest_dict = parse_import_files(files)
    manifest = parse_manifest(manifest_dict)
    report = validation.validate_package(manifest_dict)
    signature_status = "absent"
    if signature is not None and verify_signature is not None:
        record = verify_signature(manifest_dict, signature)
        signature_status = "verified" if record.verified else "mismatch"
    return {
        "package": {
            "id": manifest.package.id,
            "name": manifest.package.name,
            "version": manifest.package.version,
            "type": manifest.package.type,
        },
        "resources_to_create": [
            {"kind": r.kind, "slug": r.slug, "name": r.name} for r in manifest.resources
        ],
        "dependencies": [d.model_dump() for d in manifest.dependencies],
        "required_configuration": config_schema.required_references(manifest.configuration or {}),
        "configuration_fields": config_schema.ui_fields(manifest.configuration or {}),
        "security_findings": report["findings"],
        "risk": report["risk"],
        "valid": report["passed"],
        "signature": signature_status,
        "estimated_changes": {
            "resources": len(manifest.resources),
            "dependencies": len(manifest.dependencies),
            "configuration_inputs": len((manifest.configuration or {}).get("inputs", {})),
        },
    }


def diff_manifests(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    """Compare two manifest dicts for the package diff view.

    Permission/security-relevant changes are always surfaced explicitly.
    """
    old_m, new_m = parse_manifest(old), parse_manifest(new)
    old_res = {(r.kind, r.slug): r for r in old_m.resources}
    new_res = {(r.kind, r.slug): r for r in new_m.resources}
    added = [r.model_dump() for k, r in new_res.items() if k not in old_res]
    removed = [r.model_dump() for k, r in old_res.items() if k not in new_res]
    changed = []
    for key in old_res.keys() & new_res.keys():
        if old_res[key].model_dump() != new_res[key].model_dump():
            changed.append(
                {"kind": key[0], "slug": key[1],
                 "before": old_res[key].model_dump(), "after": new_res[key].model_dump()}
            )
    old_deps = {(d.type, d.package): d.version for d in old_m.dependencies}
    new_deps = {(d.type, d.package): d.version for d in new_m.dependencies}
    dep_changes = {
        "added": [{"type": k[0], "package": k[1], "version": v} for k, v in new_deps.items() if k not in old_deps],
        "removed": [{"type": k[0], "package": k[1], "version": v} for k, v in old_deps.items() if k not in new_deps],
        "changed": [{"type": k[0], "package": k[1], "from": old_deps[k], "to": new_deps[k]}
                    for k in old_deps.keys() & new_deps.keys() if old_deps[k] != new_deps[k]],
    }
    old_approvals = set((old_m.security.required_approvals or []))
    new_approvals = set((new_m.security.required_approvals or []))
    return {
        "from_version": old_m.package.version,
        "to_version": new_m.package.version,
        "added_resources": added,
        "removed_resources": removed,
        "changed_resources": changed,
        "dependency_changes": dep_changes,
        "permission_changes": {
            "approvals_added": sorted(new_approvals - old_approvals),
            "approvals_removed": sorted(old_approvals - new_approvals),
        },
        "configuration_changed": old_m.configuration != new_m.configuration,
        "security_changed": old_m.security != new_m.security,
    }
