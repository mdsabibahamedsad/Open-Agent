"""MP22: semantic version parsing, comparison and constraint matching.

Supports ``major.minor.patch[-prerelease]`` plus the constraint operators
used by template dependency declarations:

- exact: ``1.2.3`` or ``=1.2.3``
- caret (compatible): ``^1.2.0``
- tilde (patch-level): ``~1.2.0``
- ranges: ``>=1.2.0``, ``>1.2.0``, ``<=2.0.0``, ``<2.0.0``
  (advisory-style spaced operators like ``< 2.0.0`` also accepted)
- wildcard: ``*``, ``1.2.x``, ``1.x``
- unions via ``||`` and intersections via space/comma separated parts
  (e.g. ``>=1.2.0 <2.0.0``)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import total_ordering

_SEMVER_RE = re.compile(
    r"""^v?
    (?P<major>0|[1-9]\d*)\.
    (?P<minor>0|[1-9]\d*)\.
    (?P<patch>0|[1-9]\d*)
    (?:-(?P<prerelease>[0-9A-Za-z.\-]+))?
    (?:\+(?P<build>[0-9A-Za-z.\-]+))?
    $""",
    re.VERBOSE,
)


class VersionError(ValueError):
    """Raised when a version string or constraint is malformed."""


@total_ordering
@dataclass(frozen=True)
class SemanticVersion:
    major: int
    minor: int
    patch: int
    prerelease: str = ""
    build: str = ""

    def __str__(self) -> str:
        base = f"{self.major}.{self.minor}.{self.patch}"
        if self.prerelease:
            base += f"-{self.prerelease}"
        return base

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, SemanticVersion):
            return NotImplemented
        left = (self.major, self.minor, self.patch)
        right = (other.major, other.minor, other.patch)
        if left != right:
            return left < right
        # A prerelease is lower precedence than the plain release.
        if self.prerelease == other.prerelease:
            return False
        if not self.prerelease:
            return False
        if not other.prerelease:
            return True
        return self.prerelease < other.prerelease


def parse_version(raw: str) -> SemanticVersion:
    """Parse ``raw`` into a :class:`SemanticVersion` or raise VersionError."""
    if not isinstance(raw, str) or not raw.strip():
        raise VersionError("version must be a non-empty string")
    match = _SEMVER_RE.match(raw.strip())
    if not match:
        raise VersionError(f"invalid semantic version: {raw!r}")
    return SemanticVersion(
        major=int(match.group("major")),
        minor=int(match.group("minor")),
        patch=int(match.group("patch")),
        prerelease=match.group("prerelease") or "",
        build=match.group("build") or "",
    )


def is_valid_version(raw: str) -> bool:
    try:
        parse_version(raw)
        return True
    except VersionError:
        return False


def _caret_upper(version: SemanticVersion) -> SemanticVersion:
    if version.major > 0:
        return SemanticVersion(version.major + 1, 0, 0)
    if version.minor > 0:
        return SemanticVersion(0, version.minor + 1, 0)
    return SemanticVersion(0, 0, version.patch + 1)


def _match_single(version: SemanticVersion, clause: str) -> bool:
    clause = clause.strip()
    if not clause or clause == "*":
        return True
    # Wildcards: 1 / 1.2 / 1.2.x / 1.x
    wild = re.match(r"^v?(\d+)(?:\.(\d+|[xX*]))?(?:\.(\d+|[xX*]))?$", clause)
    if wild and any(g in ("x", "X", "*") for g in wild.groups() if g is not None):
        major = int(wild.group(1))
        minor_raw, patch_raw = wild.group(2), wild.group(3)
        if minor_raw in ("x", "X", "*"):
            return version.major == major
        if patch_raw in ("x", "X", "*"):
            return version.major == major and version.minor == int(minor_raw or 0)
        return False  # unreachable, keeps mypy honest
    if clause.startswith("^"):
        base = parse_version(clause[1:])
        return base <= version < _caret_upper(base)
    if clause.startswith("~"):
        base = parse_version(clause[1:])
        upper = SemanticVersion(base.major, base.minor + 1, 0)
        return base <= version < upper
    for operator in (">=", "<=", ">", "<", "=", "=="):
        if clause.startswith(operator):
            base = parse_version(clause[len(operator):].strip())
            if operator in ("=", "=="):
                return version == base
            if operator == ">=":
                return version >= base
            if operator == "<=":
                return version <= base
            if operator == ">":
                return version > base
            return version < base
    # Bare version means exact match.
    return version == parse_version(clause)


_LONE_OPERATORS = frozenset({">=", "<=", ">", "<", "=", "=="})


def _split_parts(union: str) -> list[str]:
    """Split a union member into clauses, joining lone operators.

    Accepts both compact (``<2.0.0``) and advisory-style spaced
    (``< 2.0.0``) constraints.
    """
    raw = [p for p in re.split(r"[,\s]+", union.strip()) if p]
    parts: list[str] = []
    index = 0
    while index < len(raw):
        token = raw[index]
        if token in _LONE_OPERATORS and index + 1 < len(raw):
            parts.append(token + raw[index + 1])
            index += 2
        else:
            parts.append(token)
            index += 1
    return parts


def satisfies(version: str, constraint: str) -> bool:
    """Return True when ``version`` satisfies ``constraint``.

    ``constraint`` may be a union of space/comma-joined intersections
    separated by ``||``. An empty constraint matches everything.
    """
    if not isinstance(constraint, str) or not constraint.strip():
        return True
    candidate = parse_version(version)
    for union in constraint.split("||"):
        parts = _split_parts(union)
        if not parts:
            continue
        try:
            if all(_match_single(candidate, part) for part in parts):
                return True
        except VersionError:
            continue
    return False


def validate_constraint(constraint: str) -> None:
    """Raise VersionError when ``constraint`` cannot be parsed."""
    if not isinstance(constraint, str) or not constraint.strip():
        raise VersionError("version constraint must be a non-empty string")
    for union in constraint.split("||"):
        parts = _split_parts(union)
        if not parts:
            raise VersionError(f"invalid version constraint: {constraint!r}")
        for part in parts:
            probe = SemanticVersion(0, 0, 0)
            try:
                _match_single(probe, part)
            except VersionError as exc:
                raise VersionError(
                    f"invalid version constraint {constraint!r}: {exc}"
                ) from exc


def select_best(candidates: list[str], constraint: str) -> str | None:
    """Pick the highest candidate satisfying ``constraint``, or None."""
    valid = [c for c in candidates if is_valid_version(c)]
    matching = [c for c in valid if satisfies(c, constraint)]
    if not matching:
        return None
    return str(max((parse_version(c) for c in matching)))


def bump(version: str, kind: str) -> str:
    """Bump ``version`` by one of major/minor/patch (drops prerelease)."""
    parsed = parse_version(version)
    if kind == "major":
        return f"{parsed.major + 1}.0.0"
    if kind == "minor":
        return f"{parsed.major}.{parsed.minor + 1}.0"
    if kind == "patch":
        return f"{parsed.major}.{parsed.minor}.{parsed.patch + 1}"
    raise VersionError(f"unknown bump kind: {kind!r}")


def is_breaking_change(old: str, new: str) -> bool:
    """True when ``old -> new`` is a breaking (major) change."""
    before, after = parse_version(old), parse_version(new)
    if after < before:
        return True  # downgrade treated as breaking for impact analysis
    return after.major != before.major
