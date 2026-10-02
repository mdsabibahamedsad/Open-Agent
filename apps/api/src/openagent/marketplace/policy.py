"""MP23: marketplace policy evaluation + license compatibility.

Policy never weakens platform/org/tool/sandbox/approval security: it can
only *add* requirements (scan required, max risk, verification, review,
license allow-list, blocked deps/permissions). License checks are advisory
by default (WARNING) or blocking (BLOCK) per policy — never legal advice.
"""

from __future__ import annotations

from typing import Any

DEFAULT_POLICY_RULES: dict[str, Any] = {
    "require_security_scan": True,
    "maximum_risk_level": "HIGH",
    "require_publisher_verification": False,
    "review_required": True,
    "allowed_licenses": [
        "Apache-2.0", "MIT", "BSD-3-Clause", "MPL-2.0", "Unlicense",
        "CC-BY-4.0", "CC-BY-SA-4.0", "Proprietary",
    ],
    "license_mode": "warning",  # "warning" | "block"
    "blocked_dependencies": [],
    "blocked_permissions": [],
    "allowed_package_types": [],
}

_RISK_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}

#: Conservative copyleft-mixing matrix. Pairs map to a warning explaining
#: the potential conflict; policy decides warning vs block. This is a
#: heuristic, not legal advice.
_LICENSE_CONFLICTS: tuple[tuple[frozenset[str], str], ...] = (
    (frozenset({"GPL-3.0-only", "Apache-2.0"}),
     "GPL-3.0-only combined with Apache-2.0 may impose copyleft obligations"),
    (frozenset({"GPL-3.0-only", "MIT"}),
     "GPL-3.0-only combined with MIT may impose copyleft obligations"),
    (frozenset({"AGPL-3.0", "Apache-2.0"}),
     "AGPL-3.0 combined with Apache-2.0 may impose network copyleft obligations"),
    (frozenset({"AGPL-3.0", "MIT"}),
     "AGPL-3.0 combined with MIT may impose network copyleft obligations"),
    (frozenset({"SSPL-1.0", "GPL-3.0-only"}),
     "SSPL-1.0 combined with GPL-3.0-only is likely incompatible"),
    (frozenset({"Proprietary", "GPL-3.0-only"}),
     "Proprietary code combined with GPL-3.0-only is likely incompatible"),
    (frozenset({"Proprietary", "AGPL-3.0"}),
     "Proprietary code combined with AGPL-3.0 is likely incompatible"),
)


def check_license_compatibility(licenses: list[str]) -> list[str]:
    """Return human-readable warnings for risky license combinations."""
    present = {str(lic).strip() for lic in licenses if str(lic).strip()}
    warnings: list[str] = []
    for pair, message in _LICENSE_CONFLICTS:
        if pair <= present:
            warnings.append(message + " (heuristic, not legal advice)")
    return warnings


def evaluate_listing_policy(
    *,
    rules: dict[str, Any] | None,
    package_license: str,
    dependency_licenses: list[str] | None = None,
    risk: str = "LOW",
    publisher_verified: bool = False,
    security_scan_passed: bool = False,
    dependencies: list[dict[str, Any]] | None = None,
    permissions: list[str] | None = None,
    package_type: str = "",
) -> dict[str, Any]:
    """Evaluate marketplace policy. Returns {passed, findings[]}.

    Findings use {code, severity, message}; severity ERROR blocks listing
    submission/publication, WARNING is advisory.
    """
    merged = dict(DEFAULT_POLICY_RULES)
    merged.update(rules or {})
    findings: list[dict[str, str]] = []

    def add(code: str, severity: str, message: str) -> None:
        findings.append({"code": code, "severity": severity, "message": message})

    if merged.get("require_security_scan") and not security_scan_passed:
        add("POLICY_NO_SCAN", "ERROR", "Marketplace policy requires a passing security scan")
    ceiling = str(merged.get("maximum_risk_level", "CRITICAL")).upper()
    if _RISK_ORDER.get(risk.upper(), 0) > _RISK_ORDER.get(ceiling, 3):
        add("POLICY_RISK_TOO_HIGH", "ERROR",
            f"Risk {risk} exceeds marketplace maximum {ceiling}")
    if merged.get("require_publisher_verification") and not publisher_verified:
        add("POLICY_UNVERIFIED_PUBLISHER", "ERROR",
            "Marketplace policy requires a verified publisher")
    allowed_licenses = merged.get("allowed_licenses") or []
    if allowed_licenses and package_license not in allowed_licenses:
        add("POLICY_LICENSE", "ERROR",
            f"License {package_license!r} is not allowed by marketplace policy")
    mode = str(merged.get("license_mode", "warning"))
    for warning in check_license_compatibility(
            [package_license, *(dependency_licenses or [])]):
        add("LICENSE_COMPAT", "ERROR" if mode == "block" else "WARNING", warning)
    blocked_deps = {str(d).lower() for d in (merged.get("blocked_dependencies") or [])}
    for dep in dependencies or []:
        name = str(dep.get("package", "")).lower()
        if name and name in blocked_deps:
            add("POLICY_BLOCKED_DEP", "ERROR",
                f"Dependency {dep.get('package')!r} is blocked by marketplace policy")
    blocked_perms = {str(p).lower() for p in (merged.get("blocked_permissions") or [])}
    for perm in permissions or []:
        if str(perm).lower() in blocked_perms:
            add("POLICY_BLOCKED_PERM", "ERROR",
                f"Permission {perm!r} is blocked by marketplace policy")
    allowed_types = merged.get("allowed_package_types") or []
    if allowed_types and package_type and package_type not in allowed_types:
        add("POLICY_TYPE", "ERROR",
            f"Package type {package_type!r} is not allowed by marketplace policy")

    errors = [f for f in findings if f["severity"] == "ERROR"]
    return {"passed": not errors, "findings": findings}
