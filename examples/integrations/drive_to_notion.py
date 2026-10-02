"""Google Drive doc -> extract -> AI summarize -> evaluate -> Notion page.

Requires a running API and env:
  OPENAGENT_API_URL, OPENAGENT_API_KEY, OPENAGENT_ORG_ID,
  OPENAGENT_DRIVE_CONNECTION_ID, OPENAGENT_NOTION_CONNECTION_ID
"""

import json
import os
import urllib.request

BASE = os.environ.get("OPENAGENT_API_URL", "http://localhost:8000")
ORG = os.environ["OPENAGENT_ORG_ID"]
KEY = os.environ.get("OPENAGENT_API_KEY", "")
DRIVE = os.environ["OPENAGENT_DRIVE_CONNECTION_ID"]
NOTION = os.environ["OPENAGENT_NOTION_CONNECTION_ID"]


def call(method: str, path: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(
        f"{BASE}{path}", data=json.dumps(body or {}).encode(), method=method,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {KEY}", "X-Organization-ID": ORG})
    with urllib.request.urlopen(req) as res:
        return json.load(res)


# 1. Find the source document (read-only).
found = call(
    "POST",
    f"/api/v1/organizations/{ORG}/integration-connections/{DRIVE}/execute",
    {"action_id": "google_drive.list_files",
     "input": {"q": "name contains 'Q3 review'", "page_size": 5}})
print("drive:", found["status"])

# 2. AI summarizes (elsewhere); the summary is evaluated against the source.
summary = "Q3 review: ship the SSO milestone first (mock summary)."
evaluation = call("POST", f"/api/v1/organizations/{ORG}/evaluations", {
    "evaluation_type": "COMPLETENESS",
    "goal": "Faithful summary of the Q3 review doc",
    "output_ref": {"summary": summary},
    "evidence": [{"evidence_type": "TOOL_RESULT", "content": found,
                  "source": "google_drive.list_files",
                  "source_type": "TOOL"}],
})
print("evaluation:", evaluation["id"], evaluation["status"])

# 3. Publish to Notion (MEDIUM write, verified page id).
page = call(
    "POST",
    f"/api/v1/organizations/{ORG}/integration-connections/{NOTION}/execute",
    {"action_id": "notion.create_page",
     "input": {"parent_id": "a" * 32, "title": "Q3 review summary",
               "content": summary}})
print("notion:", page["status"], page.get("result"))
