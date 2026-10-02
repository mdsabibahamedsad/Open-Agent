#!/usr/bin/env python3
"""Scaffold a new connector package: `python scripts/connector-new.py github`.

Generates manifest/auth/client/actions/triggers/schemas/tests/docs skeleton
under integrations/connectors/<id>/. Output is data + thin client code;
security comes from the shared framework (never scaffolded per-connector).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9_.-]+", "_", value.strip().lower()).strip("._")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{1,63}", slug or ""):
        raise SystemExit(f"Invalid connector id: {value!r}")
    return slug


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: connector-new.py <connector-id> [Human Name]", file=sys.stderr)
        return 2
    slug = _slug(argv[1])
    name = argv[2] if len(argv) > 2 else slug.replace("_", " ").title()
    target = ROOT / "integrations" / "connectors" / slug
    if target.exists():
        raise SystemExit(f"Refusing to overwrite existing {target}")

    manifest = {
        "id": slug,
        "name": name,
        "version": "1.0.0",
        "category": "automation",
        "type": "CUSTOM",
        "trust": "CUSTOM",
        "description": f"{name} connector.",
        "publisher": "",
        "license": "",
        "documentation_url": "",
        "auth": {"type": "api_key"},
        "capabilities": [
            {"id": f"{slug}.items.read", "description": "Read items",
             "risk_level": "LOW"}
        ],
        "actions": [
            {"id": f"{slug}.list_items", "name": "List items",
             "description": "List items.",
             "input_schema": {"type": "object", "properties": {},
                              "required": []},
             "output_schema": {"type": "object"},
             "required_capabilities": [f"{slug}.items.read"],
             "risk_level": "LOW", "supports_idempotency": False,
             "timeout_seconds": 30, "rate_limit_per_minute": 60,
             "mutation": False}
        ],
        "triggers": [],
        "resources": [],
        "scopes": [],
        "rate_limits": {"per_minute": 60},
        "supported_environments": ["production"],
    }

    files = {
        "manifest.json": json.dumps(manifest, indent=2) + "\n",
        "auth.py": f'"""Auth notes for {name} (no secrets in code)."""\n\nAUTH_TYPE = "api_key"\n',
        "client.py": (
            f'"""Thin {name} client: base URL + auth headers only.\n\n'
            "All retries, SSRF gates, circuit breaking, and error mapping\n"
            "come from openagent.connectors.http_client (never reimplemented).\n"
            '"""\n\nBASE_URL = "https://api.example.com"\n'
        ),
        "actions/__init__.py": "",
        "triggers/__init__.py": "",
        "schemas/__init__.py": "",
        "tests/__init__.py": "",
        "tests/test_manifest.py": (
            "from openagent.connectors.manifest import validate_manifest\n"
            "import json, pathlib\n\n"
            "def test_manifest_validates():\n"
            "    raw = json.loads(pathlib.Path(__file__).with_name("
            "'../manifest.json').resolve().read_text())\n"
            "    parsed = validate_manifest(raw)\n"
            f"    assert parsed.id == {slug!r}\n"
        ),
        "README.md": (
            f"# {name} connector\n\n"
            "## Authentication\n\nDescribe how users connect (OAuth scopes or API key).\n\n"
            "## Actions\n\nList actions, risk levels, and idempotency.\n\n"
            "## Triggers\n\nWebhook events or polling intervals.\n\n"
            "## Rate limits\n\nProvider quotas and connector caps.\n\n"
            "## Security notes\n\nCredential scoping, PII handling, secret rotation.\n\n"
            "## Limitations\n\nKnown provider gaps.\n"
        ),
    }
    for relative, content in files.items():
        path = target / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    print(f"Scaffolded connector '{slug}' at {target}")
    print("Next: fill auth/actions, add tests on ConnectorTestHarness, "
          "register via POST /connectors (connector:admin).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
