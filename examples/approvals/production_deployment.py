"""Example 1 — Production deployment with human approval.

Code Agent -> build -> tests -> deployment request (HIGH risk) -> persisted
approval -> human approves in Approval Center -> deployment runs once.

Requires a running API (`docker compose up`) and env:
  OPENAGENT_API_URL, OPENAGENT_API_KEY, OPENAGENT_ORG_ID
"""

import json
import os
import time
import urllib.request

BASE = os.environ.get("OPENAGENT_API_URL", "http://localhost:8000")
ORG = os.environ["OPENAGENT_ORG_ID"]
KEY = os.environ.get("OPENAGENT_API_KEY", "")


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


# 1. Simulate first: what will the guard decide? (never executes)
sim = call("POST", f"/api/v1/organizations/{ORG}/approvals/simulate", {
    "action_type": "sandbox.deploy", "action_category": "DEPLOY",
    "target_type": "environment", "target_id": "production",
    "environment": "production"})
print("simulation:", sim["decision"], sim["risk_level"], sim["reasons"])
assert sim["decision"] in ("REQUIRE_APPROVAL", "REQUIRE_MULTI_APPROVAL", "DENY")

# 2. Request the gated execution (parks for approval, does NOT run).
# (sandbox_id from your environment)
sandbox_id = os.environ["OPENAGENT_SANDBOX_ID"]
parked = call("POST", f"/api/v1/sandboxes/{sandbox_id}/execute", {
    "command": ["./deploy.sh", "--env", "production"],
    "target_environment": "production"})
print("parked:", parked["status"], "approval:", parked.get("approval_id"))
assert parked["status"] == "WAITING_FOR_APPROVAL"

# 3. Human approves in Approval Center (/approvals -> detail -> Approve).
approval_id = parked["approval_id"]
for _ in range(60):
    detail = call("GET", f"/api/v1/organizations/{ORG}/approvals/{approval_id}")
    if detail["status"] == "APPROVED":
        break
    time.sleep(10)
else:
    raise SystemExit("approval not granted in time")

# 4. Resume with the SAME command + approval_id (hash-verified, single-use).
done = call("POST", f"/api/v1/sandboxes/{sandbox_id}/execute", {
    "command": ["./deploy.sh", "--env", "production"],
    "target_environment": "production", "approval_id": approval_id})
print("executed:", done.get("status"))

# 5. Replaying the same approval is blocked.
try:
    call("POST", f"/api/v1/sandboxes/{sandbox_id}/execute", {
        "command": ["./deploy.sh", "--env", "production"],
        "target_environment": "production", "approval_id": approval_id})
    raise SystemExit("replay should have been rejected")
except urllib.error.HTTPError as exc:
    print("replay blocked as expected:", exc.code)
