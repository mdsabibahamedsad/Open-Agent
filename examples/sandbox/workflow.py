"""Sandbox workflow: code_test node executes through Tool Runtime -> Sandbox.

Posts a minimal workflow definition using the code_test node, then notes
that execution resolves `code.test.run` via the Tool Runtime executor,
which calls CodeService.run_tests -> Sandbox. No workflow node touches
the host.
"""

import os

import httpx

BASE = os.environ.get("OPENAGENT_API_URL", "http://localhost:8000")
HEADERS = {
    "Content-Type": "application/json",
    "X-Organization-ID": os.environ["OPENAGENT_ORG_ID"],
    **({"Authorization": f"Bearer {os.environ['OPENAGENT_API_KEY']}"}
       if os.environ.get("OPENAGENT_API_KEY") else {}),
}

definition = {
    "schema_version": "1.0",
    "triggers": [{"id": "trg_1", "type": "manual", "name": "Run", "config": {}}],
    "nodes": [
        {"id": "n_1", "type": "code_test", "name": "Run auth tests",
         "config": {"command": "pytest tests/unit/test_auth.py -q",
                    "profile": "TEST"}},
        {"id": "n_2", "type": "code_review", "name": "Review",
         "config": {"diff": ""}},
    ],
    "edges": [
        {"id": "e_1", "from": "trg_1", "to": "n_1", "condition": {"when": "success"}},
        {"id": "e_2", "from": "n_1", "to": "n_2", "condition": {"when": "success"}},
    ],
    "variables": [],
    "settings": {},
}

r = httpx.post(
    f"{BASE}/api/v1/organizations/{os.environ['OPENAGENT_ORG_ID']}/workflows/validate",
    json={"definition": definition}, headers=HEADERS, timeout=30.0)
print("validate:", r.status_code, r.text[:300])
