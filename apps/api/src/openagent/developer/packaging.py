"""MP28: deterministic extension packaging (§22, §55, §87).

Format: `<name>-<version>.oaext` — a deterministic ZIP containing:

    manifest.json        canonical manifest (sorted keys)
    files/...            source/build artifacts (sorted, fixed mtime)
    SBOM.json            dependency inventory (spdx-lite)
    provenance.json      builder, source, digest metadata (SLSA-style fields)
    signatures.json      one or more Ed25519 signatures over content digest
    CHECKSUMS.sha256     per-file hashes + content digest

Determinism: sorted entries, fixed mtime (2019-01-01 unless
SOURCE_DATE_EPOCH is set), fixed permissions, no extra file attributes.
Install safety: the archive is inspectable; installation never executes
embedded scripts on the host (§87) — builds run in the sandbox.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import zipfile
from dataclasses import dataclass, field

FIXED_MTIME = (2019, 1, 1, 0, 0, 0)


@dataclass
class PackageFile:
    path: str  # archive-relative, e.g. files/src/index.ts
    content: bytes


@dataclass
class BuiltPackage:
    filename: str
    content: bytes
    content_digest: str
    checksums: dict[str, str]
    sbom: dict
    provenance: dict


def _mtime() -> tuple[int, int, int, int, int, int]:
    epoch = os.environ.get("SOURCE_DATE_EPOCH", "").strip()
    if epoch.isdigit():
        import datetime

        dt = datetime.datetime.fromtimestamp(int(epoch), tz=datetime.UTC)
        return (dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second)
    return FIXED_MTIME


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_package(
    *,
    name: str,
    version: str,
    manifest: dict,
    files: list[PackageFile],
    dependencies: list[dict] | None = None,
    builder: str = "openagent-cli",
    source: str = "",
) -> BuiltPackage:
    safe_name = "".join(c if (c.isalnum() or c in "._-") else "-" for c in name).strip(".-")
    filename = f"{safe_name}-{version}.oaext"
    ordered = sorted(files, key=lambda f: f.path)
    checksums: dict[str, str] = {}

    manifest_raw = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    checksums["manifest.json"] = _sha256(manifest_raw)
    for f in ordered:
        checksums[f.path] = _sha256(f.content)

    sbom = {
        "spdxVersion": "SPDX-2.3",
        "name": f"{name}@{version}",
        "packages": sorted(dependencies or [], key=lambda d: str(d.get("name", ""))),
    }
    sbom_raw = json.dumps(sbom, sort_keys=True, separators=(",", ":")).encode()
    checksums["SBOM.json"] = _sha256(sbom_raw)

    # Content digest covers manifest + all files + sbom (not provenance/signatures).
    digest_input = b"".join(
        [manifest_raw, sbom_raw]
        + [f.content for f in ordered]
        + [p.encode() for p in sorted(checksums.keys())]
    )
    content_digest = _sha256(digest_input)

    provenance = {
        "builder": builder,
        "source": source,
        "content_digest_sha256": content_digest,
        "format": "oaext/1",
        "build": {"deterministic": True, "mtime": "%04d-%02d-%02d" % _mtime()[:3]},
    }
    provenance_raw = json.dumps(provenance, sort_keys=True, separators=(",", ":")).encode()

    checksums_text = "".join(
        f"{digest}  {path}\n" for path, digest in sorted(checksums.items())
    )
    checksums_text += f"{content_digest}  CONTENT\n"

    buf = io.BytesIO()
    mtime = _mtime()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for arcname, raw in [
            ("manifest.json", manifest_raw),
            ("SBOM.json", sbom_raw),
            ("provenance.json", provenance_raw),
            ("CHECKSUMS.sha256", checksums_text.encode()),
            *[(f.path, f.content) for f in ordered],
        ]:
            info = zipfile.ZipInfo(arcname, date_time=mtime)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, raw)
        # Placeholder signatures file; real signatures appended via sign_package.
        info = zipfile.ZipInfo("signatures.json", date_time=mtime)
        info.external_attr = 0o644 << 16
        zf.writestr(info, json.dumps({"signatures": []}).encode())
    content = buf.getvalue()
    return BuiltPackage(
        filename=filename,
        content=content,
        content_digest=content_digest,
        checksums=checksums,
        sbom=sbom,
        provenance=provenance,
    )


def sign_package(built: BuiltPackage, signature: dict) -> BuiltPackage:
    """Return a copy of the archive with `signature` appended to signatures.json."""
    import copy

    buf = io.BytesIO(built.content)
    out = io.BytesIO()
    with zipfile.ZipFile(buf, "r") as zin, zipfile.ZipFile(
        out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "signatures.json":
                try:
                    existing = json.loads(data.decode())
                except Exception:
                    existing = {"signatures": []}
                sigs = list(existing.get("signatures", [])) + [signature]
                data = json.dumps({"signatures": sigs}, sort_keys=True).encode()
                item = zipfile.ZipInfo("signatures.json", date_time=_mtime())
                item.external_attr = 0o644 << 16
            zout.writestr(item, data)
    updated = copy.copy(built)
    object.__setattr__(updated, "content", out.getvalue())
    return updated


def inspect_package(content: bytes, *, max_files: int = 5000) -> dict:
    """Inspect an .oaext archive without executing anything."""
    buf = io.BytesIO(content)
    with zipfile.ZipFile(buf, "r") as zf:
        names = zf.namelist()
        if len(names) > max_files:
            raise ValueError(f"archive has too many entries ({len(names)})")
        # Zip-slip guard: reject absolute paths and .. segments.
        for entry in names:
            if entry.startswith("/") or ".." in entry.split("/"):
                raise ValueError(f"unsafe archive entry: {entry!r}")
        manifest_raw = zf.read("manifest.json")
        checksums_raw = zf.read("CHECKSUMS.sha256").decode()
        try:
            signatures = json.loads(zf.read("signatures.json").decode())
        except KeyError:
            signatures = {"signatures": []}
    manifest = json.loads(manifest_raw.decode())
    return {
        "manifest": manifest,
        "entries": sorted(names),
        "checksums": checksums_raw,
        "signatures": signatures.get("signatures", []),
        "size_bytes": len(content),
    }


def verify_checksums(content: bytes) -> tuple[bool, list[str]]:
    """Recompute per-file hashes against CHECKSUMS.sha256. Returns (ok, problems)."""
    problems: list[str] = []
    buf = io.BytesIO(content)
    with zipfile.ZipFile(buf, "r") as zf:
        expected: dict[str, str] = {}
        for line in zf.read("CHECKSUMS.sha256").decode().splitlines():
            digest, _, path = line.strip().partition("  ")
            if not digest or not path or path == "CONTENT":
                continue
            expected[path.strip()] = digest.strip()
        for path, digest in expected.items():
            try:
                actual = _sha256(zf.read(path))
            except KeyError:
                problems.append(f"missing archived file: {path}")
                continue
            if actual != digest:
                problems.append(f"checksum mismatch: {path}")
    return (not problems, problems)


@dataclass
class DependencyNode:
    name: str
    constraint: str
    optional: bool = False
    children: list[DependencyNode] = field(default_factory=list)


def resolve_dependencies(
    requested: list[dict],
    available: dict[str, list[str]],
) -> dict:
    """Resolve version constraints against an index {name: [versions]}.

    Returns {name: chosen_version}. Raises ValueError on conflict or
    missing package. Prefers the highest satisfying version.
    """
    from openagent.developer.versioning import satisfies, validate_semver

    resolved: dict[str, str] = {}
    conflicts: list[str] = []
    for dep in requested:
        name = str(dep.get("name", ""))
        constraint = str(dep.get("version", "*"))
        candidates = available.get(name, [])
        viable = []
        for cand in candidates:
            try:
                if satisfies(cand, constraint):
                    viable.append(cand)
            except Exception:
                continue
        if not viable:
            if dep.get("optional"):
                continue
            conflicts.append(f"{name}@{constraint}: no matching version")
            continue
        viable.sort(key=lambda v: validate_semver(v).major * 10**12
                    + validate_semver(v).minor * 10**6 + validate_semver(v).patch,
                    reverse=True)
        chosen = viable[0]
        if name in resolved and resolved[name] != chosen:
            conflicts.append(f"{name}: conflict ({resolved[name]} vs {chosen})")
        resolved[name] = chosen
    if conflicts:
        raise ValueError("dependency resolution failed: " + "; ".join(conflicts))
    return resolved
