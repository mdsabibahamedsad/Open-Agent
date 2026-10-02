"""Example 5 — Multi-agent: CEO -> Developer -> Deployment Agent -> approval.

The Deployment Agent's gated task creates a real persisted approval. The
manager can summarize and escalate, but cannot fabricate approval: the run
only proceeds after a human approves the exact deployment task.
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


# 1. Plan an orchestration whose deploy task requires approval.
run = call("POST", f"/api/v1/organizations/{ORG}/orchestrations", {
    "objective": "Ship the billing fix: implement, test, then deploy to production",
})
print("run:", run.get("id") or run)

# 2. Executing parks the deploy task AND creates a persisted approval
#    (target_type=orchestration_task) visible in the Approval Center.
# exec_res = call("POST",
#     f"/api/v1/organizations/{ORG}/orchestrations/{run['id']}/execute", {})
# print("exec:", exec_res.get("status"))  # waiting while deploy needs approval

# 3. Human approves the deployment task at /approvals; re-executing the run
#    resumes the Deployment Agent, which reports back up to the CEO agent.
