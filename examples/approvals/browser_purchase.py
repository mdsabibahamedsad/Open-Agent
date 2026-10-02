"""Example 3 — Browser purchase: checkout -> approval -> human confirms -> submit.

High-impact browser actions park with an approval_id. The browser session stays
recoverable; CAPTCHAs park as WAITING_FOR_HUMAN (never auto-bypassed).
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


task_id = os.environ["OPENAGENT_BROWSER_TASK_ID"]
page_id = os.environ["OPENAGENT_BROWSER_PAGE_ID"]

# Checkout is high-impact: the service persists an approval and parks.
parked = call("POST", f"/api/v1/browser/tasks/{task_id}/actions", {
    "action_type": "CLICK", "page_id": page_id,
    "input": {"target": "checkout-button", "summary": "submit purchase"}})
print("gate:", parked)
assert parked.get("requiresApproval") is True
print(f"Confirm at /approvals/{parked.get('approval_id')} (form values stay masked).")

# After approval, submit with the approval_id (verified server-side):
# done = call("POST", f"/api/v1/browser/tasks/{task_id}/actions", {
#     "action_type": "CLICK", "page_id": page_id,
#     "input": {"target": "checkout-button", "summary": "submit purchase"},
#     "approval_id": parked["approval_id"]})
# print("submitted:", done.get("success"))
