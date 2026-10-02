"""Gmail trigger -> AI summary -> evaluator -> approval -> Slack message.

Requires a running API and env:
  OPENAGENT_API_URL, OPENAGENT_API_KEY, OPENAGENT_ORG_ID,
  OPENAGENT_GMAIL_CONNECTION_ID, OPENAGENT_SLACK_CONNECTION_ID
"""

import json
import os
import urllib.request

BASE = os.environ.get("OPENAGENT_API_URL", "http://localhost:8000")
ORG = os.environ["OPENAGENT_ORG_ID"]
KEY = os.environ.get("OPENAGENT_API_KEY", "")
GMAIL = os.environ["OPENAGENT_GMAIL_CONNECTION_ID"]
SLACK = os.environ["OPENAGENT_SLACK_CONNECTION_ID"]


def call(method: str, path: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(
        f"{BASE}{path}", data=json.dumps(body or {}).encode(), method=method,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {KEY}", "X-Organization-ID": ORG})
    with urllib.request.urlopen(req) as res:
        return json.load(res)


# 1. Gmail trigger output becomes evaluation evidence (never a bare claim).
messages = call(
    "POST",
    f"/api/v1/organizations/{ORG}/integration-connections/{GMAIL}/execute",
    {"action_id": "gmail.list_messages",
     "input": {"q": "is:unread", "max_results": 5}})
print("gmail:", messages["status"])

# 2. Agent summarizes (elsewhere); the summary is verified before sending.
summary = "3 unread threads need replies (mock summary for example flow)."
evaluation = call("POST", f"/api/v1/organizations/{ORG}/evaluations", {
    "evaluation_type": "OUTPUT_QUALITY",
    "goal": "Faithful unread-mail digest",
    "output_ref": {"summary": summary},
    "evidence": [{"evidence_type": "TOOL_RESULT", "content": messages,
                  "source": "gmail.list_messages", "source_type": "TOOL"}],
})
print("evaluation:", evaluation["id"], evaluation["status"])

# 3. Slack send parks for approval (MEDIUM external side effect).
parked = call(
    "POST",
    f"/api/v1/organizations/{ORG}/integration-connections/{SLACK}/execute",
    {"action_id": "slack.send_message",
     "input": {"channel": "C012345", "text": summary}})
print("slack gate:", parked.get("status"), parked.get("approval_id"))
assert parked.get("status") == "WAITING_FOR_APPROVAL"
print(f"Approve at /approvals/{parked['approval_id']}, then re-run with approval_id.")
