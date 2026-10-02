"""MP22: publication validation engine.

Pipeline::

    Package
      -> Schema Validation -> Dependency Validation -> Permission Validation
      -> Security Validation -> Runtime Compatibility -> Policy Validation
      -> Integrity Validation -> Evaluation Validation -> Publish

Every finding is structured ``{code, path, severity, message}`` with
severities INFO / WARNING / ERROR / BLOCKER. ``ERROR`` or ``BLOCKER``
findings block publication.
"""

from __future__ import annotations

from typing import Any, Callable

from openagent.packages import config_schema, dependencies as dep_module
from openagent.packages import security as security_module
from openagent.packages.manifest import (
    ManifestError,
    PackageManifest,
    parse_manifest,
    validate_marketplace_metadata,
)
from openagent.packages.signing import content_hash
from openagent.packages.types import SEVERITY_RANK, Severity
from openagent.packages.versioning import VersionError


def _finding(code: str, path: str, severity: str, message: str) -> dict[str, str]:
    return {"code": code, "path": path, "severity": severity, "message": message}


def blocking(findings: list[dict[str, str]]) -> bool:
    """True when any ERROR/BLOCKER finding blocks publication."""
    return any(
        SEVERITY_RANK.get(item.get("severity", ""), 0)
        >= SEVERITY_RANK[Severity.ERROR.value]
        for item in findings
    )


def validate_schema_stage(raw: dict[str, Any]) -> tuple[PackageManifest | None, list[dict[str, str]]]:
    findings: list[dict[str, str]] = []
    try:
        manifest = parse_manifest(raw)
    except ManifestError as exc:
        return None, [_finding("SCHEMA_INVALID", "$", Severity.BLOCKER.value, str(exc))]
    schema_problems = config_schema.validate_config_schema(manifest.configuration or {})
    for problem in schema_problems:
        findings.append(_finding("CONFIG_SCHEMA_INVALID", "configuration", Severity.ERROR.value, problem))
    if not manifest.resources and manifest.package.type not in ("MODEL_PRESET", "AGENT_PRESET", "WORKFLOW_PRESET", "MEMORY_PRESET", "PROMPT", "SKILL"):
        findings.append(
            _finding("EMPTY_PACKAGE", "resources", Severity.WARNING.value,
                     "package declares no resources")
        )
    return manifest, findings


def validate_dependencies_stage(
    manifest: PackageManifest,
    available: dep_module.AvailableVersions | None = None,
    policy_allows: dep_module.PolicyAllows | None = None,
) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    declared: list[dep_module.DeclaredDependency] = []
    for index, dep in enumerate(manifest.dependencies):
        try:
            declared.append(
                dep_module.parse_declared(
                    {
                        "type": dep.type,
                        "package": dep.package,
                        "version": dep.version,
                        "optional": dep.optional,
                        "peer": dep.peer,
                    }
                )
            )
        except VersionError as exc:
            findings.append(
                _finding("DEPENDENCY_INVALID", f"dependencies[{index}]",
                         Severity.ERROR.value, str(exc))
            )
    if available is None:
        # Offline validation: structural only; availability is re-checked at
        # install time against the live registry.
        return findings
    result = dep_module.resolve_dependencies(declared, available, policy_allows=policy_allows)
    for failure in result.failures:
        severity = Severity.ERROR.value if failure.code != "POLICY_DENIED" else Severity.BLOCKER.value
        findings.append(_finding(failure.code, ".".join(failure.path) or "$", severity, failure.message))
    for warning in result.warnings:
        findings.append(_finding("DEPENDENCY_WARNING", "$", Severity.WARNING.value, warning))
    return findings


def validate_security_stage(raw: dict[str, Any]) -> list[dict[str, str]]:
    return security_module.scan_manifest_dict(raw)


def validate_compatibility_stage(
    manifest: PackageManifest,
    platform_version: str = "*",
    api_version: str = "v1",
) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    compat = manifest.compatibility
    if platform_version != "*" and compat.openagent_version not in ("*", ""):
        from openagent.packages.versioning import satisfies

        try:
            if not satisfies(platform_version, compat.openagent_version):
                findings.append(
                    _finding("INCOMPATIBLE_PLATFORM", "compatibility.openagent_version",
                             Severity.ERROR.value,
                             f"package requires OpenAgent {compat.openagent_version!r}")
                )
        except VersionError as exc:
            findings.append(
                _finding("COMPATIBILITY_INVALID", "compatibility.openagent_version",
                         Severity.ERROR.value, str(exc))
            )
    if compat.api_version not in ("v1", "*"):
        findings.append(
            _finding("INCOMPATIBLE_API", "compatibility.api_version",
                     Severity.ERROR.value,
                     f"package requires API {compat.api_version!r}")
        )
    _ = api_version
    return findings


def validate_policy_stage(
    manifest: PackageManifest,
    policy_denies: Callable[[str], str | None] | None = None,
) -> list[dict[str, str]]:
    """Check package-declared capabilities against org policy denials.

    ``policy_denies(capability) -> reason | None``. Most-restrictive wins:
    any denial is a BLOCKER.
    """
    findings: list[dict[str, str]] = []
    if policy_denies is None:
        return findings
    capabilities: set[str] = set()
    for resource in manifest.resources:
        payload = resource.payload or {}
        for key in ("capabilities", "tools", "connectors", "permissions"):
            values = payload.get(key, [])
            if isinstance(values, list):
                capabilities.update(str(v) for v in values)
    for capability in sorted(capabilities):
        reason = policy_denies(capability)
        if reason:
            findings.append(
                _finding("POLICY_CONFLICT", "resources", Severity.BLOCKER.value,
                         f"capability {capability!r} denied by policy: {reason}")
            )
    return findings


def validate_integrity_stage(raw: dict[str, Any], expected_hash: str = "") -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    if not expected_hash:
        return findings
    actual = content_hash(raw)
    if actual != expected_hash:
        findings.append(
            _finding("INTEGRITY_MISMATCH", "$", Severity.BLOCKER.value,
                     "package content hash does not match integrity record")
        )
    return findings


def validate_evaluation_stage(manifest: PackageManifest) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    evaluation = manifest.evaluation or {}
    if not evaluation:
        findings.append(
            _finding("NO_EVALUATION", "evaluation", Severity.INFO.value,
                     "no evaluation criteria declared; quality gates cannot pre-check this package")
        )
        return findings
    for key in ("minimum_quality_score", "required_checks"):
        if key not in evaluation:
            findings.append(
                _finding("EVALUATION_INCOMPLETE", f"evaluation.{key}",
                         Severity.WARNING.value,
                         f"evaluation declares criteria but misses {key!r}")
            )
    return findings


def validate_package(
    raw: dict[str, Any],
    *,
    available: dep_module.AvailableVersions | None = None,
    policy_allows: dep_module.PolicyAllows | None = None,
    policy_denies: Callable[[str], str | None] | None = None,
    expected_hash: str = "",
    platform_version: str = "*",
    api_version: str = "v1",
) -> dict[str, Any]:
    """Run the full validation pipeline; return a serializable report."""
    manifest, schema_findings = validate_schema_stage(raw)
    stages: dict[str, list[dict[str, str]]] = {"schema": schema_findings}
    if manifest is None:
        all_findings = schema_findings
        return {
            "passed": False,
            "findings": all_findings,
            "stages": stages,
            "risk": "CRITICAL",
            "metadata_warnings": [],
        }
    stages["dependencies"] = validate_dependencies_stage(manifest, available, policy_allows)
    stages["security"] = validate_security_stage(raw)
    stages["compatibility"] = validate_compatibility_stage(manifest, platform_version, api_version)
    stages["policy"] = validate_policy_stage(manifest, policy_denies)
    stages["integrity"] = validate_integrity_stage(raw, expected_hash)
    stages["evaluation"] = validate_evaluation_stage(manifest)
    all_findings = [item for items in stages.values() for item in items]
    return {
        "passed": not blocking(all_findings),
        "findings": all_findings,
        "stages": stages,
        "risk": security_module.risk_level(stages["security"]),
        "metadata_warnings": validate_marketplace_metadata(manifest),
    }
