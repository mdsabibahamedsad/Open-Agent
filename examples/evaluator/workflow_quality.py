"""Example — Workflow with Verify -> Quality Gate -> correct/human branches.

Trigger -> AI Agent -> Tool -> Verify -> Quality Gate ->
  PASS -> continue | FAIL -> correction | UNCERTAIN -> human review.

Requires a running API and env:
  OPENAGENT_API_URL, OPENAGENT_API_KEY, OPENAGENT_ORG_ID,
  OPENAGENT_WORKFLOW_ID, OPENAGENT_EXECUTION_ID
"""

import json
import os
import urllib.request

BASE = os.environ.get("OPENAGENT_API_URL", "http://localhost:8000")
ORG = os.environ["OPENAGENT_ORG_ID"]
KEY = os.environ.get("OPENAGENT_API_KEY", "")
WORKFLOW = os.environ["OPENAGENT_WORKFLOW_ID"]
EXECUTION = os.environ["OPENAGENT_EXECUTION_ID"]


def call(method: str, path: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=json.dumps(body or {}).encode(),
        method=method,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {KEY}",
                 "X-Organization-ID": ORG},
    )
    with urllib.request.urlopen(req) as res:
        return json.load(res)


# Authoring (builder palette): verify -> quality_gate -> retry/correct/human.
verify_node = {"type": "verify",
               "config": {"checks": [
                   {"kind": "http_response", "name": "notify_ok",
                    "params": {"expected_status": 200}}]}}
gate_node = {"type": "quality_gate",
             "config": {"gate": "workflow_success_gate"}}
print("author nodes:", verify_node["type"], gate_node["type"])

# Runtime: verify the execution from node metadata (never from claims).
outcome = call(
    "POST",
    f"/api/v1/organizations/{ORG}/workflows/{WORKFLOW}/executions/{EXECUTION}/verify",
    {"required_nodes": ["agent", "tool"], "forbid_failed": True})
print("workflow decision:", outcome["decision"], outcome["score"])

if outcome["decision"] == "FAIL":
    print("branch: correction (bounded, budgeted)")
elif outcome["decision"] == "UNCERTAIN":
    print("branch: human review at", outcome.get("approval_id"))
else:
    print("branch: continue")
