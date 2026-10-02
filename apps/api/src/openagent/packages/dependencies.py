"""MP22: dependency declaration validation and graph resolution.

The resolver works against an injected *registry snapshot* — a callable
mapping ``package_slug -> list[available_versions]`` plus a callable
returning a version's own dependency list — so the same code resolves
both published packages and in-flight manifests. It detects:

- unavailable / revoked dependencies
- unsatisfiable version constraints
- version conflicts (two dependents requiring disjoint ranges)
- circular dependencies
- incompatible runtime requirements (surfaced as conflicts, not silent pins)

Organization security policy is enforced by an injected predicate:
``policy_allows(dep_type, package) -> (allowed, reason)``. A denied
dependency is a hard resolution failure, never an auto-install.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from openagent.packages.versioning import (
    VersionError,
    satisfies,
    select_best,
    validate_constraint,
)

#: Dependency ``type`` values understood by the resolver. Unknown types are
#: kept (forward compatibility) but flagged for review.
KNOWN_DEP_TYPES = frozenset(
    {
        "skill",
        "prompt",
        "tool",
        "connector",
        "model",
        "memory",
        "workflow",
        "agent",
        "package",
        "mcp",
        "preset",
    }
)


@dataclass
class DeclaredDependency:
    type: str
    package: str
    version: str = "*"
    optional: bool = False
    peer: bool = False


@dataclass
class ResolvedDependency:
    type: str
    package: str
    constraint: str
    resolved_version: str
    optional: bool = False
    peer: bool = False


@dataclass
class ResolutionFailure:
    code: str
    package: str
    message: str
    constraint: str = ""
    path: list[str] = field(default_factory=list)


@dataclass
class ResolutionResult:
    resolved: list[ResolvedDependency]
    failures: list[ResolutionFailure]
    warnings: list[str]
    install_order: list[str]

    @property
    def ok(self) -> bool:
        return not self.failures


def parse_declared(raw: dict[str, Any]) -> DeclaredDependency:
    """Validate one raw dependency declaration."""
    if not isinstance(raw, dict):
        raise VersionError("dependency must be an object")
    dtype = str(raw.get("type", "")).strip().lower()
    package = str(raw.get("package", "")).strip()
    constraint = str(raw.get("version", "*") or "*").strip()
    if not dtype:
        raise VersionError("dependency.type is required")
    if not package:
        raise VersionError("dependency.package is required")
    validate_constraint(constraint)
    return DeclaredDependency(
        type=dtype,
        package=package,
        version=constraint,
        optional=bool(raw.get("optional", False)),
        peer=bool(raw.get("peer", False)),
    )


def parse_all(raw_deps: Iterable[dict[str, Any]]) -> list[DeclaredDependency]:
    return [parse_declared(dict(item)) for item in raw_deps]


AvailableVersions = Callable[[str, str], list[str]]
"""``(dep_type, package_slug) -> sorted list of available version strings``."""

ChildDependencies = Callable[[str, str, str], list[DeclaredDependency]]
"""``(dep_type, package_slug, version) -> that version's own dependencies``."""

PolicyAllows = Callable[[str, str], tuple[bool, str]]
"""``(dep_type, package_slug) -> (allowed, reason)``."""


def _allow_all(_dtype: str, _package: str) -> tuple[bool, str]:
    return True, ""


def _no_children(_dtype: str, _package: str, _version: str) -> list[DeclaredDependency]:
    return []


def resolve_dependencies(
    root: list[DeclaredDependency],
    available: AvailableVersions,
    children: ChildDependencies | None = None,
    policy_allows: PolicyAllows | None = None,
    revoked: Callable[[str, str], bool] | None = None,
) -> ResolutionResult:
    """Resolve ``root`` dependencies into a concrete, ordered install plan."""
    children_fn = children or _no_children
    policy_fn = policy_allows or _allow_all
    failures: list[ResolutionFailure] = []
    warnings: list[str] = []
    resolved: dict[tuple[str, str], ResolvedDependency] = {}
    constraints: dict[tuple[str, str], list[str]] = defaultdict(list)

    for dep in root:
        if dep.type not in KNOWN_DEP_TYPES:
            warnings.append(
                f"unknown dependency type {dep.type!r} for {dep.package!r}; kept for review"
            )

    def visit(dep: DeclaredDependency, trail: list[str]) -> str | None:
        key = (dep.type, dep.package)
        node = f"{dep.type}:{dep.package}"
        constraints[key].append(dep.version)
        if node in trail:
            failures.append(
                ResolutionFailure(
                    code="CIRCULAR_DEPENDENCY",
                    package=dep.package,
                    message=f"circular dependency detected: {' -> '.join([*trail, node])}",
                    constraint=dep.version,
                    path=[*trail, node],
                )
            )
            return None
        allowed, reason = policy_fn(dep.type, dep.package)
        if not allowed:
            failures.append(
                ResolutionFailure(
                    code="POLICY_DENIED",
                    package=dep.package,
                    message=f"organization policy denies {node}: {reason}",
                    constraint=dep.version,
                    path=[*trail, node],
                )
            )
            return None
        versions = available(dep.type, dep.package)
        if not versions:
            if dep.optional:
                warnings.append(f"optional dependency {node} is unavailable; skipping")
                return None
            failures.append(
                ResolutionFailure(
                    code="MISSING_DEPENDENCY",
                    package=dep.package,
                    message=f"dependency {node} is unavailable",
                    constraint=dep.version,
                    path=[*trail, node],
                )
            )
            return None
        # A previously resolved pin must still satisfy the new constraint —
        # otherwise the two dependents conflict.
        if key in resolved:
            if not satisfies(resolved[key].resolved_version, dep.version):
                failures.append(
                    ResolutionFailure(
                        code="DEPENDENCY_CONFLICT",
                        package=dep.package,
                        message=(
                            f"{node} pinned to {resolved[key].resolved_version} "
                            f"conflicts with constraint {dep.version!r}"
                        ),
                        constraint=dep.version,
                        path=[*trail, node],
                    )
                )
                return None
            return resolved[key].resolved_version
        best = select_best(list(versions), dep.version)
        if best is None:
            if dep.optional:
                warnings.append(
                    f"optional dependency {node} has no version matching "
                    f"{dep.version!r}; skipping"
                )
                return None
            failures.append(
                ResolutionFailure(
                    code="UNSATISFIABLE_CONSTRAINT",
                    package=dep.package,
                    message=(
                        f"no available version of {node} matches {dep.version!r} "
                        f"(available: {sorted(versions)!r})"
                    ),
                    constraint=dep.version,
                    path=[*trail, node],
                )
            )
            return None
        if revoked is not None and revoked(dep.package, best):
            failures.append(
                ResolutionFailure(
                    code="REVOKED_DEPENDENCY",
                    package=dep.package,
                    message=f"{node}@{best} has been revoked and cannot install",
                    constraint=dep.version,
                    path=[*trail, node],
                )
            )
            return None
        resolved[key] = ResolvedDependency(
            type=dep.type,
            package=dep.package,
            constraint=dep.version,
            resolved_version=best,
            optional=dep.optional,
            peer=dep.peer,
        )
        for child in children_fn(dep.type, dep.package, best):
            visit(child, [*trail, node])
        return best

    for dep in root:
        visit(dep, [])

    install_order = [f"{d.type}:{d.package}@{d.resolved_version}" for d in resolved.values()]
    # Post-order: children were added before parents only if resolver ran
    # depth-first; reverse so dependencies install first.
    install_order.reverse()
    ordered = sorted(resolved.values(), key=lambda d: install_order.index(f"{d.type}:{d.package}@{d.resolved_version}"))
    return ResolutionResult(
        resolved=ordered, failures=failures, warnings=warnings, install_order=install_order
    )


def detect_requirement_conflicts(requirements: list[dict[str, Any]]) -> list[str]:
    """Detect conflicting runtime/model/permission requirements across deps.

    Each requirement is ``{"source": str, "key": str, "value": str}``. Two
    entries with the same key but different values conflict.
    """
    seen: dict[str, str] = {}
    conflicts: list[str] = []
    for req in requirements:
        key = str(req.get("key", ""))
        value = str(req.get("value", ""))
        source = str(req.get("source", "unknown"))
        if not key:
            continue
        if key in seen and seen[key] != value:
            conflicts.append(
                f"conflicting requirement {key!r}: {seen[key]!r} vs {value!r} (from {source})"
            )
        else:
            seen[key] = value
    return conflicts
