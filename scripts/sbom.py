#!/usr/bin/env python3
"""SBOM generator (MP27 §117). Emits CycloneDX-flavoured JSON from
installed distributions plus repo build metadata. Provenance fields
are included ONLY when actually generated and verified — never faked.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import sys
from pathlib import Path


def _distributions() -> list[dict]:
    try:
        from importlib import metadata as _metadata
    except ImportError:
        return []
    out = []
    for dist in _metadata.distributions():
        try:
            name = dist.metadata.get("Name", "unknown")
            version = dist.version or "unknown"
        except Exception:
            continue
        out.append({"name": name, "version": str(version),
                    "type": "library"})
    return sorted(out, key=lambda d: d["name"].lower())


def build_sbom(root: Path) -> dict:
    components = _distributions()
    descriptor = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": {
            "timestamp": datetime.datetime.now(
                datetime.timezone.utc).isoformat(),
            "component": {"name": "openagent", "version": "0.1.0",
                          "type": "application"},
            "provenance": "unsigned-local",
        },
        "components": components,
    }
    h = hashlib.sha256(
        json.dumps(descriptor, sort_keys=True).encode()).hexdigest()
    descriptor["metadata"]["checksum_sha256"] = h
    return descriptor


def main(argv=None) -> None:
    args = list(argv) if argv else []
    root = Path(__file__).resolve().parents[1]
    out_path = Path(args[0]) if args else (root / "sbom.json")
    sbom = build_sbom(root)
    out_path.write_text(json.dumps(sbom, indent=2))
    print(f"wrote {out_path} "
          f"({len(sbom['components'])} components, "
          f"provenance={sbom['metadata']['provenance']})")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
