"""Example 4 — Destructive sandbox command: risk -> approval -> execution.

Approval authorizes the exact command; it never weakens sandbox isolation,
network policy, resource limits, or credential handling.
"""

import json
import os
import urllib.request

BASE = os.environ.get("OPENAGENT_API_URL", "http://localhost:8000")
ORG = os.environ["OPENAGENT_ORG_ID"]
KEY = os.environ.get("OPENAGENT_API_KEY", "")


def call(method: str, path: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(
        f"{BASE}{path}", data=json.dumps(body or {}).encode(), method=method,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {KEY}", "X-Organization-ID": ORG})
    with urllib.request.urlopen(req) as res:
        return json.load(res)


sandbox_id = os.environ["OPENAGENT_SANDBOX_ID"]
parked = call("POST", f"/api/v1/sandboxes/{sandbox_id}/execute", {
    "command": "rm -rf /workspace/build-cache", "workdir": "/workspace"})
print("gate:", parked["status"], parked.get("risk_level"), parked.get("risk_reasons"))
assert parked["status"] == "WAITING_FOR_APPROVAL"

# A *different* command cannot reuse this approval (hash mismatch -> INVALIDATED).
# approved = <human approves parked["approval_id"]>
# bad = call("POST", f"/api/v1/sandboxes/{sandbox_id}/execute", {
#     "command": "rm -rf /workspace/src", "workdir": "/workspace",
#     "approval_id": parked["approval_id"]})  # -> 409 INVALID_APPROVAL
