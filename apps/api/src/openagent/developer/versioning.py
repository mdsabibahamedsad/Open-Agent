"""MP28: semantic versioning, constraints, compatibility, deprecations (§24-25)."""

from __future__ import annotations

import re
from dataclasses import dataclass

_SEMVER_RE = re.compile(
    r"^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-([0-9A-Za-z.\-]+))?(?:\+([0-9A-Za-z.\-]+))?$"
)

_CONSTRAINT_RE = re.compile(
    r"^\s*(\*|>=?\s*\d+\.\d+\.\d+|<=?\s*\d+\.\d+\.\d+|==?\s*\d+\.\d+\.\d+"
    r"|\^?\s*\d+\.\d+\.\d+|~?\s*\d+\.\d+\.\d+"
    r"(\s+<?>=?\s*\d+\.\d+\.\d+)*)\s*$"
)


class VersionError(ValueError):
    pass


@dataclass(frozen=True)
class SemVer:
    major: int
    minor: int
    patch: int
    prerelease: str = ""
    build: str = ""

    def __str__(self) -> str:
        base = f"{self.major}.{self.minor}.{self.patch}"
        if self.prerelease:
            base += f"-{self.prerelease}"
        if self.build:
            base += f"+{self.build}"
        return base


def validate_semver(version: str) -> SemVer:
    match = _SEMVER_RE.match(version.strip())
    if not match:
        raise VersionError(
            f"invalid semantic version '{version}': expected MAJOR.MINOR.PATCH"
        )
    major, minor, patch, prerelease, build = match.groups()
    return SemVer(int(major), int(minor), int(patch), prerelease or "", build or "")


def validate_constraint(constraint: str) -> str:
    text = (constraint or "").strip()
    if not text:
        raise VersionError("version constraint must not be empty")
    if text == "*":
        return text
    # Range form ">=1.0.0 <2.0.0"
    parts = text.split()
    if len(parts) == 2 and all(_CONSTRAINT_RE.match(p) for p in parts):
        return text
    if not _CONSTRAINT_RE.match(text):
        raise VersionError(
            f"invalid version constraint '{constraint}': "
            "use '*', '^1.2.3', '~1.2.3', '>=1.0.0 <2.0.0', or exact '1.2.3'"
        )
    return text


def _tuple(v: SemVer) -> tuple[int, int, int]:
    return (v.major, v.minor, v.patch)


def satisfies(version: str, constraint: str) -> bool:
    """Check whether a concrete version satisfies a constraint."""
    constraint = (constraint or "*").strip()
    if constraint == "*":
        return True
    ver = validate_semver(version)
    tokens = constraint.split()
    if len(tokens) == 2:  # range form
        return satisfies(version, tokens[0]) and satisfies(version, tokens[1])
    token = tokens[0]
    if token.startswith("^"):
        base = validate_semver(token[1:].strip())
        if base.major > 0:
            return _tuple(ver) >= _tuple(base) and ver.major == base.major
        if base.minor > 0:
            return _tuple(ver) >= _tuple(base) and (ver.major, ver.minor) == (0, base.minor)
        return _tuple(ver) >= _tuple(base) and _tuple(ver) == _tuple(base)
    if token.startswith("~"):
        base = validate_semver(token[1:].strip())
        return _tuple(ver) >= _tuple(base) and (ver.major, ver.minor) == (base.major, base.minor)
    if token.startswith(">="):
        return _tuple(ver) >= _tuple(validate_semver(token[2:].strip()))
    if token.startswith("<="):
        return _tuple(ver) <= _tuple(validate_semver(token[2:].strip()))
    if token.startswith(">"):
        return _tuple(ver) > _tuple(validate_semver(token[1:].strip()))
    if token.startswith("<"):
        return _tuple(ver) < _tuple(validate_semver(token[1:].strip()))
    if token.startswith("=="):
        return _tuple(ver) == _tuple(validate_semver(token[2:].strip()))
    if token.startswith("="):
        return _tuple(ver) == _tuple(validate_semver(token[1:].strip()))
    return _tuple(ver) == _tuple(validate_semver(token))


def bump(version: str, part: str) -> str:
    ver = validate_semver(version)
    if part == "major":
        return f"{ver.major + 1}.0.0"
    if part == "minor":
        return f"{ver.major}.{ver.minor + 1}.0"
    if part == "patch":
        return f"{ver.major}.{ver.minor}.{ver.patch + 1}"
    raise VersionError(f"unknown bump part '{part}': use major|minor|patch")


def is_breaking_change(from_version: str, to_version: str) -> bool:
    old = validate_semver(from_version)
    new = validate_semver(to_version)
    if _tuple(new) <= _tuple(old):
        return False
    if new.major != old.major:
        return True
    if old.major == 0 and (new.minor != old.minor or new.patch != old.patch):
        return True  # 0.x: any change may break
    return False


# ---------------------------------------------------------------------------
# Compatibility validation + deprecation metadata (§25, §61).
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Deprecation:
    name: str
    deprecated: bool = False
    sunset_at: str = ""
    replacement: str = ""
    migration_guide: str = ""


# Known deprecated SDK entry points with replacements (never silent).
DEPRECATIONS: tuple[Deprecation, ...] = (
    Deprecation(name="client.runs", deprecated=False),
    Deprecation(
        name="client.agents.create(legacy position args)",
        deprecated=True,
        replacement="client.agents.create({name, ...})",
        migration_guide="docs/developers/migrations/sdk-1x.md",
    ),
)


def check_compatibility(
    openagent_version: str,
    sdk_constraint: str,
    extension_api: str = "1.x",
) -> list[str]:
    """Return a list of human-readable compatibility problems (empty = OK)."""
    from openagent.developer.types import COMPATIBILITY_MATRIX

    problems: list[str] = []
    gen = COMPATIBILITY_MATRIX.get("1.x")
    assert gen is not None
    if extension_api != gen["extension_api"]:
        problems.append(
            f"extension_api '{extension_api}' is not supported "
            f"(supported: {gen['extension_api']})"
        )
    try:
        if not satisfies(openagent_version, gen["openagent"]):
            problems.append(
                f"openagent {openagent_version} is outside supported range {gen['openagent']}"
            )
    except VersionError as exc:
        problems.append(str(exc))
    try:
        validate_constraint(sdk_constraint)
    except VersionError as exc:
        problems.append(f"invalid sdk constraint: {exc}")
    return problems
