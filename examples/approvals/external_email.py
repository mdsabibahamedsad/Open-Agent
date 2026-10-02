"""Example 2 — External email: compose -> policy -> approval -> send.

The agent composes, but only a human-approved request sends. The approval is
bound to the exact recipients/subject hash; edits invalidate it.
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


# Tool execution is the central gate: HIGH-risk external action parks first.
res = call("POST", f"/api/v1/organizations/{ORG}/tools/execute", {
    "tool_id": os.environ["OPENAGENT_EMAIL_TOOL_ID"],
    "input": {"to": ["customer@example.com"], "subject": "Your invoice",
              "body": "Thanks for your business!"},
})
print("gate:", res["status"], res.get("metadata"))
assert res["status"] == "WAITING"
approval_id = res["metadata"]["approval_id"]
print(f"Approve at /approvals/{approval_id}, then re-run with approval_id.")

# After human approval, the exact same input executes exactly once.
# res2 = call("POST", f"/api/v1/organizations/{ORG}/tools/execute", {
#     "tool_id": os.environ["OPENAGENT_EMAIL_TOOL_ID"],
#     "input": {"to": ["customer@example.com"], "subject": "Your invoice",
#               "body": "Thanks for your business!"},
#     "approval_id": approval_id})
# print("sent:", res2["status"])
